from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from autostock.brain import ClaudeBrain
from autostock.brokers.kis import KISBroker, KISClient, KISMarket
from autostock.brokers.paper import PaperBroker
from autostock.config import Settings
from autostock.engine import Engine
from autostock.market_hours import ET
from autostock.models import Bar, Decision, Quote
from autostock.risk import Risk
from autostock.state import DayState, OpenTrade


def dec(action="BUY", symbol="SOXL", conf=0.9, size=100, stop=1.0, take=2.0):
    return Decision(action=action, symbol=symbol, confidence=conf, size_pct=size,
                    stop_loss_pct=stop, take_profit_pct=take, reason="t")


class Market:
    def __init__(self, now):
        self.now, self.px = now, {"SOXL": 30.0, "SOXS": 15.0}

    def quote(self, s):
        return Quote(s, self.px[s], self.px[s])

    def bars(self, s, n=120):
        p = self.px[s]
        return [Bar(self.now - timedelta(minutes=i), p, p, p, p, 1000) for i in range(40, 0, -1)]


class Brain:
    def __init__(self, *ds):
        self.ds, self.snaps = list(ds), []

    def decide(self, snap):
        self.snaps.append(snap)
        return self.ds.pop(0) if self.ds else dec("HOLD", "")


@pytest.fixture
def rig(tmp_path):
    def make(*decisions, at=(11, 0), **over):
        cfg = dataclasses.replace(Settings(), **{"data_dir": str(tmp_path), "decision_interval_sec": 60,
                                                 "fee_pct": 0.0, **over})
        m = Market(datetime(2026, 1, 5, *at, tzinfo=ET))
        brain = Brain(*decisions)
        e = Engine(cfg, m, PaperBroker(slippage_pct=0), brain, clock=lambda: m.now)
        return e, m, brain
    return make


def step(e, m, minutes=1, **px):
    m.now += timedelta(minutes=minutes)
    m.px.update(px)
    e.tick()


def test_buy_then_stop_loss(rig):
    e, m, _ = rig(dec(stop=1.0))
    e.tick()
    assert e.st.open.symbol == "SOXL" and e.st.open.qty == 23       # $714 / $30
    step(e, m, SOXL=29.69)                                           # -1.03%
    assert e.st.open is None and e.st.losses == 1 and e.st.realized_usd < 0
    assert e.broker.position("SOXL") is None


def test_take_profit_and_daily_target_halts(rig):
    e, m, brain = rig(dec(take=9.0), dec(), daily_target_krw=20_000)  # 목표 ≈ $14.3
    e.tick()
    step(e, m, SOXL=30.7)                                            # +$16.1 → 목표 달성
    assert e.st.open is None and e.st.halted == "일일 목표 달성"
    step(e, m, 5)
    assert e.st.open is None and len(brain.snaps) == 1               # 종료 후엔 AI도 안 부름


def test_daily_loss_limit_caps_size_and_halts(rig):
    e, m, _ = rig(dec(stop=2.0), daily_max_loss_krw=7_000, max_stop_loss_pct=2.0)   # 한도 $5
    e.tick()
    assert e.st.open.qty == 8                                        # 5 / (30*2%) = 8주로 축소
    step(e, m, SOXL=29.3)
    assert e.st.halted == "일일 손실 한도" and e.st.realized_usd >= -6


def test_entry_guards(rig):
    for kw, d in [({"at": (9, 32)}, dec()), ({"at": (15, 50)}, dec()),
                  ({}, dec(conf=0.3)), ({}, dec(symbol="TSLA"))]:
        e, _, _ = rig(d, **kw)
        e.tick()
        assert e.st.open is None and "rejected" in e.recent_decisions[-1]


def test_stale_quotes_block_entry(rig):
    e, m, _ = rig(dec())
    m.bars = lambda s, n=120: [Bar(m.now - timedelta(minutes=30), 30, 30, 30, 30, 1)] * 30
    e.tick()
    assert e.st.open is None


def test_flatten_before_close_and_switch_side(rig):
    e, m, _ = rig(dec(), dec(symbol="SOXS"), at=(15, 0))
    e.tick()
    step(e, m)
    assert e.st.open.symbol == "SOXS" and e.st.trades == 1           # SOXL 청산 후 SOXS 진입
    step(e, m, 55)                                                   # 15:56
    assert e.st.open is None and e.st.history[-1]["reason"] == "장 마감 전 강제 청산"


def test_cooldown_after_loss_and_state_persists(rig):
    e, m, _ = rig(dec(stop=1.0), dec(), dec())
    e.tick()
    step(e, m, SOXL=29.6)
    step(e, m, 2)
    assert e.st.open is None and "쿨다운" in e.recent_decisions[-1]["rejected"]
    again = DayState.load(e.state_path)
    assert again.losses == 1 and again.realized_usd == e.st.realized_usd
    assert not again.roll(e.st.date) and again.roll("2026-01-06") and again.trades == 0


def test_fees_reduce_pnl():
    r = Risk(dataclasses.replace(Settings(), fee_pct=0.25))
    t = OpenTrade("SOXL", 10, 30.0, "", 1, 2, r.fee(30.0, 10))
    assert r.unrealized(t, 30.0) == pytest.approx(-1.5)             # 왕복 0.5%


# ── Claude ────────────────────────────────────────────────
def test_claude_brain_request_and_failsafe():
    calls = {}

    def parse(**kw):
        calls.update(kw)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=dec(),
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    b = ClaudeBrain(Settings(), client=client)
    assert b.decide({"a": 1}).action == "BUY"
    assert calls["model"] == "claude-opus-5-5" and calls["output_format"] is Decision
    assert calls["fallbacks"] == "default" and "thinking" not in calls

    def refuse(**kw):
        return SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None)

    def boom(**kw):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    for fn in (refuse, boom):
        client.beta.messages.parse = fn
        assert b.decide({}).action == "HOLD"


def test_decision_schema_accepted_by_sdk():
    """SDK가 Decision 스키마를 구조화 출력용으로 변환할 수 있는지."""
    sent = {}

    def handler(req: httpx.Request):
        import json
        sent.update(json.loads(req.content))
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": dec().model_dump_json()}]})

    c = anthropic.Anthropic(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    d = ClaudeBrain(Settings(), client=c).decide({"x": 1})
    assert d.action == "BUY" and d.symbol == "SOXL"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["effort"] == "medium" and sent["fallbacks"] == "default"

    sent.clear()                                                     # Haiku: fallbacks 없이 일반 엔드포인트
    cfg = dataclasses.replace(Settings(), model="claude-haiku-5-5", effort="high")
    assert ClaudeBrain(cfg, client=c).decide({"x": 1}).action == "BUY"
    assert sent["model"] == "claude-haiku-5-5" and "fallbacks" not in sent
    assert sent["output_config"]["effort"] == "high" and sent["output_config"]["format"]["type"] == "json_schema"


# ── KIS ───────────────────────────────────────────────────
class FakeHTTP:
    """KIS 서버 흉내: 주문하면 2번째 잔고 조회부터 체결된 것으로 보인다."""

    def __init__(self, fill=True):
        self.fill, self.qty, self.pending, self.calls = fill, 0, 0, []

    def _resp(self, j):
        return SimpleNamespace(status_code=200, json=lambda: {"rt_cd": "0", **j}, text="")

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url.rsplit("/", 1)[-1], (headers or {}).get("tr_id"), json))
        if url.endswith("tokenP"):
            return self._resp({"access_token": "T", "expires_in": 86400})
        if url.endswith("/order") or url.endswith("/daytime-order"):
            sell = json.get("SLL_TYPE") == "00" or (headers or {}).get("tr_id") == "TTTS6037U"
            self.pending = int(json["ORD_QTY"]) * (-1 if sell else 1)
            return self._resp({"output": {"ODNO": "77"}})
        self.pending = 0
        return self._resp({"output": {}})

    def get(self, url, headers=None, params=None, timeout=None):
        name = url.rsplit("/", 1)[-1]
        self.calls.append((name, headers["tr_id"], params))
        if name == "price":
            return self._resp({"output": {"last": "30.10", "base": "29.00"}})
        if name == "inquire-time-itemchartprice":
            return self._resp({"output2": [
                {"xymd": "20260105", "xhms": "100100", "open": "2", "high": "3", "low": "1", "last": "2.5", "evol": "9"},
                {"xymd": "20260105", "xhms": "100000", "open": "1", "high": "2", "low": "1", "last": "2", "evol": "5"}]})
        if name == "inquire-balance":
            if self.fill and self.pending:
                self.qty, self.pending = self.qty + self.pending, 0
            rows = [{"ovrs_pdno": "SOXL", "ovrs_cblc_qty": str(self.qty), "pchs_avg_pric": "30.15"}] if self.qty else []
            return self._resp({"output1": rows})
        if name == "inquire-asking-price":
            return self._resp({"output2": {}})
        if name == "inquire-ccnl":
            return self._resp({"output": [{"odno": "77", "ft_ccld_unpr3": "30.05"}]})
        raise AssertionError(name)


@pytest.fixture
def kis(tmp_path, monkeypatch):
    monkeypatch.setattr("autostock.brokers.kis.time.sleep", lambda s: None)

    def make(env="demo", fill=True):
        c = KISClient("key123456", "sec", env, str(tmp_path))
        c.http = FakeHTTP(fill)
        return c, KISBroker(c, "12345678", fill_timeout=0.05)
    return make


def test_kis_market_parsing(kis):
    c, _ = kis()
    m = KISMarket(c)
    assert m.quote("SOXL") == Quote("SOXL", 30.10, 29.00)
    bars = m.bars("SOXL")
    assert [b.close for b in bars] == [2.0, 2.5] and bars[0].ts.hour == 10
    assert c.http.calls[1][2]["EXCD"] == "AMS"


@pytest.mark.parametrize("env,buy_tr,sell_tr", [("demo", "VTTT1002U", "VTTT1001U"),
                                                ("real", "TTTT1002U", "TTTT1006U")])
def test_kis_order_round_trip(kis, env, buy_tr, sell_tr):
    c, b = kis(env)
    f = b.buy("SOXL", 5, 30.0)
    assert (f.qty, f.price) == (5, 30.15)                           # 잔고 평균단가
    f = b.sell("SOXL", 5, 30.0)
    assert (f.qty, f.price) == (5, 30.05)                           # 체결내역 단가
    orders = [x for x in c.http.calls if x[0] == "order"]
    assert [o[1] for o in orders] == [buy_tr, sell_tr]
    assert orders[0][2]["OVRS_ORD_UNPR"] == "30.09" and orders[0][2]["OVRS_EXCG_CD"] == "AMEX"
    assert orders[1][2]["OVRS_ORD_UNPR"] == "29.91" and orders[1][2]["SLL_TYPE"] == "00"


def test_kis_unfilled_order_is_cancelled(kis):
    c, b = kis(fill=False)
    assert b.buy("SOXL", 5, 30.0) is None
    cancel = [x for x in c.http.calls if x[0] == "order-rvsecncl"]
    assert cancel and cancel[0][1] == "VTTT1004U" and cancel[0][2]["ORGN_ODNO"] == "77"


def test_run_exit_modes(rig):
    e, m, _ = rig(at=(16, 5))
    assert e.run(exit_when_closed=True) == "closed"                  # 장 종료 후
    e, m, _ = rig(at=(5, 0))
    assert e.run(exit_when_closed=True) == "closed"                  # 개장 4시간 반 전
    e, m, _ = rig(at=(11, 0))
    e.sleep = lambda s: None
    assert e.run(max_minutes=1e-9, exit_when_closed=True) == "handoff"


def test_kis_credential_profiles(monkeypatch):
    from autostock import config
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ENV", "KIS_REAL_APP_KEY", "KIS_DEMO_APP_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KIS_REAL_APP_KEY", "R")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "RS")
    monkeypatch.setenv("KIS_DEMO_APP_KEY", "D")
    monkeypatch.setenv("KIS_DEMO_APP_SECRET", "DS")
    monkeypatch.setenv("KIS_DEMO_ACCOUNT_NO", "50001234")
    c = config.load()
    assert c.kis_real.ok and c.kis_real.app_key == "R" and c.kis_real.env == "real"
    assert c.kis_demo.app_key == "D" and c.kis_demo.account_no == "50001234"
    monkeypatch.delenv("KIS_DEMO_APP_KEY")                 # 예전 방식도 인식
    monkeypatch.setenv("KIS_APP_KEY", "OLD")
    monkeypatch.setenv("KIS_APP_SECRET", "S")
    monkeypatch.setenv("KIS_ENV", "demo")
    c = config.load()
    assert c.kis_demo.app_key == "OLD" and c.kis_real.app_key == "R"


def test_kis_retries_on_rate_limit(kis):
    c, _ = kis()
    real_get, n = c.http.get, {"n": 0}

    def flaky(url, **kw):
        n["n"] += 1
        if n["n"] <= 2:
            return SimpleNamespace(status_code=500, text="", json=lambda: {
                "rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."})
        return real_get(url, **kw)

    c.http.get = flaky
    assert KISMarket(c).quote("SOXL").last == 30.10 and n["n"] == 3


def test_web_page_renders_and_escapes(rig):
    from autostock import web
    e, m, _ = rig(dec(stop=1.0))
    e.tick()
    e.st.open = None
    e._journal("decision", action="HOLD", symbol="", confidence=0.5, reason="<script>x</script>")
    cfg = e.cfg
    page = web.render(cfg, "paper", "tok")
    assert "AI 판단 기록" in page and "&lt;script&gt;" in page and "<script>x" not in page
    assert "아직 기록이 없습니다" in web.render(cfg, "live", "tok")


def test_preflight_gates_real_order_modes(rig, monkeypatch):
    import os
    e, m, brain = rig(dec(), mode="live", modes=("kis-demo", "live"))
    e.tick()                                                         # 실계좌 테스트(1주 왕복) 후 매매 시작
    assert os.path.exists(e._ok_file("live")) and e.st.open and e.st.open.qty > 1

    e2, m2, brain2 = rig(dec(), mode="kis-demo", modes=("kis-demo",))
    assert not os.path.exists(e2._ok_file("kis-demo"))
    e2.broker.buy = lambda *a: None                                  # 매수 미체결
    e2.tick()
    assert e2.st.halted == "" and e2.st.test_attempts == 1 and not brain2.snaps
    step(e2, m2)
    assert e2.st.test_attempts == 2 and e2.st.halted == ""           # 1분 뒤 재시도
    e2.st.test_attempts = 199
    step(e2, m2)
    assert e2.st.halted == "주문 테스트 반복 실패"
    from autostock import web
    assert "주문 테스트 실패" in web.render(e2.cfg, "kis-demo", "t")
    assert e2.st.roll("2026-01-06") and e2.st.halted == "" and e2.st.test_attempts == 0


def test_snapshot_includes_sector_context(rig):
    e, m, brain = rig(context=("NVDA", "SOXX", "AMD", "BROKEN"), context_bars=2)
    m.px.update(NVDA=180.0, SOXX=250.0, AMD=160.0)
    e.tick()
    sec = brain.snaps[0]["sector"]
    assert set(sec) == {"NVDA", "SOXX", "AMD"}                       # 실패한 종목은 빠지고 판단은 계속
    assert "ret_15m_pct" in sec["NVDA"] and "ret_15m_pct" not in sec["AMD"]


def test_trailing_stop_locks_in_gain(rig):
    e, m, _ = rig(dec(stop=1.5, take=9.0))
    e.tick()
    assert e.st.open.trail_pct == 0.6                                # ATR 0 → 최소폭
    step(e, m, SOXL=30.12)                                           # +0.4%: 아직 발동 조건 전
    step(e, m, SOXL=29.95)
    assert e.st.open is not None                                     # 고점 수익이 추적폭 미만이면 그냥 보유
    step(e, m, SOXL=30.45)                                           # +1.5% 고점
    assert e.st.open.peak_price == 30.45
    step(e, m, SOXL=30.25)                                           # 고점 대비 -0.66%
    assert e.st.open is None and "추적 손절" in e.st.history[-1]["reason"] and e.st.realized_usd > 0


def test_price_move_and_exit_trigger_extra_decisions(rig):
    e, m, brain = rig(decision_interval_sec=600, surge_pct=1.0)
    e.tick()                                                         # 첫 판단 (HOLD)
    step(e, m, SOXL=30.1)
    assert len(brain.snaps) == 1                                     # 주기 전, 움직임 작음
    step(e, m, SOXL=30.4)                                            # 직전 판단 대비 +1.3%
    assert len(brain.snaps) == 2 and brain.snaps[1]["trigger"] == "price_move"

    e, m, brain = rig(dec(stop=1.0), dec(symbol="SOXS"), decision_interval_sec=600)
    e.tick()
    step(e, m, SOXL=29.6)                                            # 손절
    step(e, m)                                                       # 바로 다음 틱에 AI 호출 → 반대 종목 진입
    assert brain.snaps[1]["trigger"] == "after_exit" and e.st.open.symbol == "SOXS"


def test_old_state_file_still_loads(tmp_path):
    import json
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"date": "2026-01-05", "realized_usd": 1.0, "trades": 1, "wins": 1, "losses": 0,
                             "consecutive_losses": 0, "last_loss_ts": "", "halted": "", "history": [],
                             "open": {"symbol": "SOXL", "qty": 3, "entry_price": 30.0, "entry_ts": "x",
                                      "stop_pct": 2.0, "take_pct": 3.0, "buy_fee": 0.1}}))
    st = DayState.load(str(p))
    assert st.open.trail_pct == 0 and st.last_loss_symbol == ""


def test_sessions_regular_and_day(monkeypatch):
    from autostock import market_hours as mh
    from zoneinfo import ZoneInfo
    K = ZoneInfo("Asia/Seoul")
    monkeypatch.setattr(mh, "ENABLED", ("regular", "day"))
    at = lambda *a: datetime(*a, tzinfo=K)                           # noqa: E731
    s = mh.current(at(2026, 11, 23, 10, 30))                         # 월요일 낮 (겨울)
    assert s.name == "day" and s.key == "2026-11-23D"
    assert mh.minutes_since_open(at(2026, 11, 23, 10, 30)) == 30
    assert mh.current(at(2026, 11, 23, 9, 59)) is None
    assert mh.current(at(2026, 11, 23, 17, 14)).name == "day"        # 03:14 ET
    assert mh.current(at(2026, 11, 23, 17, 16)) is None
    r = mh.current(at(2026, 11, 23, 23, 45))
    assert r.name == "regular" and r.key == "2026-11-23"
    assert mh.current(at(2026, 11, 28, 11, 0)) is None               # 토요일
    assert mh.current(at(2026, 7, 6, 16, 14)).name == "day"          # 여름: 03:14 EDT
    assert mh.current(at(2026, 7, 6, 16, 16)) is None
    assert mh.next_open(at(2026, 11, 23, 17, 30)).astimezone(K).hour == 23
    monkeypatch.setattr(mh, "ENABLED", ("regular",))
    assert mh.current(at(2026, 11, 23, 10, 30)) is None


def test_kis_daytime_uses_separate_order_api(kis, monkeypatch):
    from autostock.brokers import kis as k
    monkeypatch.setattr(k, "_is_day", lambda: True)
    monkeypatch.setattr(k, "_extended", lambda: True)
    c, b = kis("real")
    f = b.buy("SOXL", 1, 30.0)
    assert f.qty == 1
    order = next(x for x in c.http.calls if x[0] == "daytime-order")
    assert order[1] == "TTTS6036U" and "SLL_TYPE" not in order[2] and order[2]["OVRS_ORD_UNPR"] == "30.15"
    KISMarket(c).quote("NVDA")
    assert c.http.calls[-1][2]["EXCD"] == "BAQ"
    KISMarket(c).quote("SOXL")
    assert c.http.calls[-1][2]["EXCD"] == "BAA"
    c2, b2 = kis("demo")
    with pytest.raises(k.KISError):
        b2.buy("SOXL", 1, 30.0)                                      # 모의투자는 주간거래 불가


def test_day_session_has_separate_day_state_and_order_test(rig, monkeypatch):
    import os
    from autostock import market_hours as mh
    monkeypatch.setattr(mh, "ENABLED", ("regular", "day"))
    e, m, _ = rig(dec(), mode="live", modes=("live",), at=(22, 0))  # 22:00 ET 일요일밤 = 월요일 12:00 KST
    m.now = datetime(2026, 1, 4, 22, 0, tzinfo=ET)
    open(e._ok_file("live"), "w").close()                            # 정규장 테스트 통과 상태여도
    e.tick()
    assert e.st.date == "2026-01-05D"
    assert os.path.exists(e._ok_file("live", "day")) and e.st.open   # 주간거래는 따로 테스트 후 진입


def test_kis_limit_follows_the_book_within_a_cap(kis):
    c, b = kis("real")
    b.book = lambda s: (29.90, 30.20)                                # 호가가 현재가 여유(30.09)보다 멀다
    assert b._limit("buy", "SOXL", 30.0) == 30.20 and b._limit("sell", "SOXL", 30.0) == 29.90
    b.book = lambda s: (28.0, 32.0)                                  # 너무 벌어지면 상한(0.8%)까지만
    assert b._limit("buy", "SOXL", 30.0) == 30.24 and b._limit("sell", "SOXL", 30.0) == 29.76
    b.book = lambda s: None
    assert b._limit("buy", "SOXL", 30.0) == 30.09
    assert KISMarket(c).book("SOXL") is None                         # 응답에 호가가 없으면 None


def test_premarket_session(monkeypatch):
    from autostock import market_hours as mh
    from zoneinfo import ZoneInfo
    K = ZoneInfo("Asia/Seoul")
    monkeypatch.setattr(mh, "ENABLED", ("regular", "day", "pre"))
    s = mh.current(datetime(2026, 11, 23, 18, 30, tzinfo=K))
    assert s.name == "pre" and s.key == "2026-11-23P"
    assert mh.current(datetime(2026, 11, 23, 23, 26, tzinfo=K)) is None      # 정규장 직전 5분은 비움
    assert mh.current(datetime(2026, 11, 23, 23, 31, tzinfo=K)).name == "regular"
    assert mh.current(datetime(2026, 11, 23, 17, 30, tzinfo=K)) is None


def test_account_requirement_rejection_halts_session(rig):
    e, m, brain = rig(dec(), mode="live", modes=("live",))

    def reject(*a):
        raise RuntimeError("[APBK1681] 해당종목은 기본예탁금 충족한 계좌만 매수주문가능합니다")
    e.broker.buy = reject
    e.tick()
    assert e.st.halted == "계좌 요건 미충족으로 주문 거절" and e.st.test_attempts == 1
    step(e, m, 5)
    assert e.st.test_attempts == 1 and not brain.snaps               # 같은 세션에서는 더 두드리지 않음


def test_single_symbol_long_only_mode(monkeypatch, rig):
    from autostock import config
    from autostock.brokers import kis as k
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("BULL_SYMBOL", "nvda")
    monkeypatch.setenv("BEAR_SYMBOL", "NONE")
    c = config.load()
    assert c.symbols == ("NVDA",) and "NVDA" not in c.context and "SOXX" in c.context
    assert k.EXCD_ORDER["NVDA"] == "NASD" and k.EXCD_ORDER["SOXL"] == "AMEX" and k.EXCD_ORDER["TSM"] == "NYSE"
    b = ClaudeBrain(c, client=SimpleNamespace())
    assert "NVDA" in b.system and "매수만 가능" in b.system and "{" not in b.system

    e, m, brain = rig(dec(symbol="NVDA", stop=1.0), bull="NVDA", bear="", capital_krw=400_000)
    m.px["NVDA"] = 130.0
    e.tick()
    assert e.st.open.symbol == "NVDA" and e.st.open.qty == 2          # $285 / $130
    assert list(brain.snaps[0]["market"]) == ["NVDA"]
    e2, m2, _ = rig(dec(symbol="NVDA"), bull="NVDA", bear="", capital_krw=170_000,
                    data_dir=e.cfg.data_dir + "/b")                  # 17만원으로는 1주도 못 삼
    m2.px["NVDA"] = 130.0
    e2.tick()
    assert e2.st.open is None and "수량 0" in e2.recent_decisions[-1]["rejected"]


def test_per_mode_overrides(monkeypatch):
    from autostock import config
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for k, v in {"MODE": "paper,kis-demo,live", "BULL_SYMBOL": "NVDA", "BEAR_SYMBOL": "NONE", "CAPITAL_KRW": "170000",
                 "DEMO__BULL_SYMBOL": "SOXL", "DEMO__BEAR_SYMBOL": "SOXS", "DEMO__CAPITAL_KRW": "1000000",
                 "PAPER__BULL_SYMBOL": "SOXL", "PAPER__BEAR_SYMBOL": "SOXS", "PAPER__STYLE": "aggressive",
                 "PAPER__DECISION_INTERVAL_SEC": "60"}.items():
        monkeypatch.setenv(k, v)
    live, demo, paper = config.load("live"), config.load("kis-demo"), config.load("paper")
    assert live.symbols == ("NVDA",) and live.capital_krw == 170000 and live.style == "normal"
    assert demo.symbols == ("SOXL", "SOXS") and demo.capital_krw == 1000000 and demo.decision_interval_sec == 180
    assert paper.style == "aggressive" and paper.decision_interval_sec == 60 and paper.capital_krw == 170000
    assert config.load().mode == "paper" and live.modes == ("paper", "kis-demo", "live")
    assert "초단타 실험 모드" in ClaudeBrain(paper, client=SimpleNamespace()).system
    assert "초단타 실험 모드" not in ClaudeBrain(demo, client=SimpleNamespace()).system


def test_order_test_symbol_and_rehalt_clears_when_symbol_changes(rig):
    e, m, _ = rig(mode="live", modes=("live",), order_test_symbol="INTC")
    m.px["INTC"] = 25.0
    e.st.halted, e.st.test_symbol = "계좌 요건 미충족으로 주문 거절", "SOXL"
    bought = []
    orig = e.broker.buy
    e.broker.buy = lambda s, q, p: bought.append((s, q)) or orig(s, q, p)
    e.tick()
    assert bought[0] == ("INTC", 1) and e.st.halted == "" and e.st.test_symbol == "INTC"
    import os
    assert os.path.exists(e._ok_file("live")) and e.broker.position("INTC") is None


def test_order_test_can_buy_and_hold(rig):
    e, m, brain = rig(mode="live", modes=("live",), bull="INTC", bear="", order_test_sell=False)
    m.px["INTC"] = 25.0
    e.tick()
    assert e.broker.position("INTC").qty == 1                        # 팔지 않고 보유
    assert e.st.open.symbol == "INTC" and e.st.open.qty == 1 and e.st.open.entry_price == 25.0
    step(e, m, INTC=24.4)                                            # -2.4% → 기본 손절로 관리됨
    assert e.st.open is None
