from __future__ import annotations

import json
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
    assert "초단타(스캘핑) 모드" in ClaudeBrain(paper, client=SimpleNamespace()).system
    assert "초단타(스캘핑) 모드" not in ClaudeBrain(demo, client=SimpleNamespace()).system


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


def test_halt_is_reevaluated_with_new_settings(tmp_path):
    st = DayState(date="2026-01-05", consecutive_losses=4, losses=4, realized_usd=-3.0, halted="4연속 손실")
    st.save(str(tmp_path / "state_paper.json"))
    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path), max_consecutive_losses=100)
    e = Engine(cfg, Market(datetime(2026, 1, 5, 11, 0, tzinfo=ET)), PaperBroker(), Brain())
    assert e.st.halted == "" and DayState.load(e.state_path).halted == ""
    st.halted, st.realized_usd = "일일 목표 달성", 80.0                # 여전히 해당되면 유지
    st.save(str(tmp_path / "state_paper.json"))
    e = Engine(cfg, Market(datetime(2026, 1, 5, 11, 0, tzinfo=ET)), PaperBroker(), Brain())
    assert e.st.halted == "일일 목표 달성"


def test_scalp_exits(rig):
    e, m, _ = rig(dec(stop=1.0, take=3.0), take_profit_max_pct=1.2, max_hold_min=8)
    e.tick()
    assert e.st.open.take_pct == 1.2                                 # 익절 상한
    step(e, m, 9)                                                    # 9분 동안 제자리
    assert e.st.open is None and "시간 청산" in e.st.history[-1]["reason"]

    r = Risk(dataclasses.replace(Settings(), fee_pct=0.25))
    t = OpenTrade("SOXL", 10, 30.0, "2026-01-05T11:00:00-05:00", 1.0, 5.0, 0.0, 30.18, 0.3)
    st = DayState(open=t)
    now = datetime(2026, 1, 5, 11, 1, tzinfo=ET)
    assert r.exit_reason(st, now, 30.08) == ""                       # 고점 +0.6%: 수수료 감안 전이라 미발동
    t.peak_price = 30.27                                             # 고점 +0.9%
    assert "추적 손절" in r.exit_reason(st, now, 30.17)              # 고점에서 -0.33% → 청산, 여전히 +0.57%


def test_indicators_entry_timing_fields():
    from autostock import indicators
    bars = [Bar(datetime(2026, 1, 5, 10, i, tzinfo=ET), p, p, p, p, 1) for i, p in enumerate([30.0] * 20 + [30.6])]
    s = indicators.summarize(bars)
    assert s["ret_1m_pct"] == 2.0 and s["ext_ema9_pct"] > 1.5


def test_kis_get_retries_after_dropped_connection(kis):
    import requests
    c, _ = kis()
    real_get, n = c.http.get, {"n": 0}

    def drop_once(url, **kw):
        n["n"] += 1
        if n["n"] == 1:
            raise requests.ConnectionError("Remote end closed connection without response")
        return real_get(url, **kw)
    c.http.get = drop_once
    fake = c.http
    orig_session = requests.Session
    requests.Session = lambda: fake                                  # 재연결 시 같은 가짜 서버 사용
    try:
        assert KISMarket(c).quote("SOXL").last == 30.10 and n["n"] == 2
    finally:
        requests.Session = orig_session


class OrbMarket:
    """개장 후 20분 동안 SOXL 29.5~30.5 범위, 그 뒤 가격을 테스트가 정한다. 1분봉은 끝난 봉만 준다."""
    def __init__(self, now):
        self.now, self.px = now, {"SOXL": 30.0, "SOXS": 15.0, "NVDA": 130.0, "SOXX": 250.0}
        self.opens = {"NVDA": 129.0, "SOXX": 248.0}
        self.after = []                                              # 20분 이후 봉 종가

    def quote(self, s):
        return Quote(s, self.px[s], self.px[s])

    def bars(self, s, n=120):
        o = self.now.replace(hour=9, minute=30, second=0, microsecond=0)
        out = []
        for k in range(int((self.now - o).total_seconds() // 60)):
            ts = o + timedelta(minutes=k)
            if s == getattr(self, "bars_sym", "SOXL"):
                c = (30.5 if k % 2 else 29.5) if k < 20 else (self.after[k - 20] if k - 20 < len(self.after) else self.px[s])
                out.append(Bar(ts, c, c, c, c, 1000))
            else:
                p0 = self.opens.get(s, self.px[s])
                out.append(Bar(ts, p0 if k == 0 else self.px[s], self.px[s], self.px[s], self.px[s], 1000))
        return out[-n:]


@pytest.fixture
def orb_rig(tmp_path):
    def make(**over):
        cfg = dataclasses.replace(Settings(), **{"data_dir": str(tmp_path), "strategy": "orb", "fee_pct": 0.0,
                                                 "max_stop_loss_pct": 1.5, "take_profit_max_pct": 10, **over})
        m = OrbMarket(datetime(2026, 1, 5, 9, 50, 30, tzinfo=ET))
        brain = Brain(dec("HOLD", ""))
        return Engine(cfg, m, PaperBroker(slippage_pct=0), brain, clock=lambda: m.now), m, brain
    return make


def test_orb_enters_on_breakout_with_peers(orb_rig):
    e, m, brain = orb_rig()
    e.tick()
    assert e.orb["2026-01-05"]["hh"] == 30.5 and e.st.open is None and "돌파 대기" in e.orb_status
    m.after = [30.8]
    m.px["SOXL"] = 30.8
    m.now += timedelta(minutes=1)
    e.tick()                                                         # 9:51 — 9:50 봉 종가 30.8 > 30.5
    t = e.st.open
    assert t.symbol == "SOXL" and t.stop_pct == 1.5 and t.take_pct == 10 and t.trail_pct == 3
    assert brain.snaps and brain.snaps[0]["trigger"] == "orb_entry_review"
    import json
    ev = [json.loads(x) for x in open(e.log_path)]
    assert any(x.get("review") and x["action"] == "AGREE" for x in ev)


def test_orb_requires_peer_agreement_and_window(orb_rig):
    e, m, _ = orb_rig()
    m.opens["NVDA"] = 131.0                                          # 엔비디아는 개장가보다 아래
    m.after, m.px["SOXL"] = [30.8], 30.8
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None and "동조 안 됨" in e.orb_status and "NVDA" in e.orb_status

    e2, m2, _ = orb_rig(orb_window_min=15, data_dir=e.cfg.data_dir + "/b")
    m2.after, m2.px["SOXL"] = [30.8], 30.8
    m2.now += timedelta(minutes=1)
    e2.tick()
    assert e2.st.open is None and "마감" in e2.orb_status


def test_orb_downside_buys_bear_and_respects_max_trades(orb_rig):
    e, m, _ = orb_rig(orb_max_trades=1)
    m.opens.update(NVDA=131.0, SOXX=251.0)                           # 동조 종목도 하락
    m.after, m.px["SOXL"] = [29.2], 29.2
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open.symbol == "SOXS"
    m.px["SOXS"] = 14.7                                              # -2% → 손절
    m.now += timedelta(seconds=10)
    e.tick()
    assert e.st.open is None and e.st.trades == 1
    m.after.append(29.0)
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None and "모두 사용" in e.orb_status


def test_round_trips_pair_buys_and_sells():
    from autostock import webdata
    ev = [{"kind": "buy", "symbol": "SOXL", "qty": 10, "price": 30.0, "ts": "2026-01-05T10:00:00-05:00", "reason": "a"},
          {"kind": "decision", "action": "HOLD"},
          {"kind": "sell", "symbol": "SOXL", "qty": 4, "price": 31.0, "ts": "2026-01-05T10:10:00-05:00", "pnl_usd": 3.7},
          {"kind": "sell", "symbol": "SOXL", "qty": 6, "price": 29.0, "ts": "2026-01-05T10:30:00-05:00", "pnl_usd": -6.4},
          {"kind": "buy", "symbol": "SOXS", "qty": 5, "price": 15.0, "ts": "2026-01-05T11:00:00-05:00"},
          {"kind": "sell", "symbol": "INTC", "qty": 1, "price": 25.0, "ts": "2026-01-05T11:05:00-05:00", "pnl_usd": 0.1}]
    trips, still = webdata.round_trips(ev, 0.25)
    assert [(t["symbol"], t["qty"], t["buy_px"], t["sell_px"]) for t in trips] == \
        [("SOXL", 4, 30.0, 31.0), ("SOXL", 6, 30.0, 29.0), ("INTC", 1, None, 25.0)]
    assert trips[0]["hold_min"] == 10 and trips[1]["hold_min"] == 30
    assert trips[0]["buy_amt"] == 120 and round(trips[0]["fees"], 4) == round((120 + 124) * 0.0025, 4)
    assert trips[0]["pnl"] == 3.7 and trips[2]["pct"] is None
    assert still == [{"symbol": "SOXS", "qty": 5, "price": 15.0, "ts": "2026-01-05T11:00:00-05:00", "reason": ""}]


def test_bar_store_merges_and_chart_payload(tmp_path, monkeypatch):
    from autostock import market_hours, webdata
    store = webdata.BarStore(str(tmp_path / "bars.json"))
    d0 = datetime.now(ET) - timedelta(days=1)                        # 저장소는 4일 지난 봉을 지우므로 최근 평일 사용
    while d0.weekday() >= 5:
        d0 -= timedelta(days=1)
    t0 = d0.replace(hour=9, minute=30, second=0, microsecond=0)
    store.merge("SOXL", [Bar(t0 + timedelta(minutes=i), 30, 30.2, 29.9, 30 + i / 100, 100) for i in range(5)])
    store.merge("SOXL", [Bar(t0 + timedelta(minutes=i), 30, 30.2, 29.9, 31, 100) for i in range(3, 8)])
    store.save()
    again = webdata.BarStore(str(tmp_path / "bars.json"))
    bars = again.get("SOXL", 0)
    assert len(bars) == 8 and bars[3][4] == 31                       # 같은 분은 새 값으로 덮어씀
    monkeypatch.setattr(market_hours, "now_et", lambda: t0 + timedelta(minutes=8))
    monkeypatch.setattr(webdata, "market", lambda cfg: None)
    state = {"open": {"symbol": "SOXL", "qty": 10, "entry_price": 30.0, "entry_ts": t0.isoformat(), "stop_pct": 1.5,
                      "take_pct": 10.0, "buy_fee": 0, "peak_price": 31.2, "trail_pct": 3.0}}
    ev = [{"kind": "buy", "symbol": "SOXL", "qty": 10, "price": 30.0, "ts": (t0 + timedelta(minutes=1)).isoformat()}]
    d = webdata.chart(Settings(), "paper", "SOXL", 0, again, state, {"orb": {"hh": 30.5, "ll": 29.5, "symbol": "SOXL"}}, ev)
    assert len(d["bars"]) == 8 and d["vwap"][0] is not None and d["range"] == [29.5, 30.5]
    kinds = {x["k"]: x["v"] for x in d["lines"]}
    assert kinds["stop"] == 29.55 and kinds["take"] == 33.0 and kinds["trail"] == 30.264  # 고점 +4% → 청산선 31.2×0.97
    assert d["marks"][0]["k"] == "buy" and d["marks"][0]["q"] == 10
    assert webdata.chart(Settings(), "paper", "TSLA", 0, again, state, None, ev)["error"]


def test_kis_holdings_merge_and_page_renders(kis, tmp_path):
    from autostock import web, webdata
    c, b = kis("real")
    c.http.qty = 3
    h = b.holdings()
    assert h[0]["symbol"] == "SOXL" and h[0]["qty"] == 3 and h[0]["avg"] == 30.15
    assert [x[2]["OVRS_EXCG_CD"] for x in c.http.calls if x[0] == "inquire-balance"] == ["NASD"]   # 실전은 미국 전체 한 번
    c2, b2 = kis("demo")
    c2.http.qty = 2
    assert len(b2.holdings()) == 1
    assert [x[2]["OVRS_EXCG_CD"] for x in c2.http.calls if x[0] == "inquire-balance"] == ["NASD", "NYSE", "AMEX"]
    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path), modes=("paper",))
    webdata._acct_cache.clear()
    assert webdata.account(cfg, "live", None, None).get("loading")             # 아직 조회 전이면 기다리지 않고 바로 반환
    webdata._acct_cache["live"] = {"source": "x", "holdings": [{"symbol": "INTC", "qty": 2, "avg": 50.0}], "at": 0}
    acct = webdata.account(cfg, "live", {"open": {"symbol": "INTC", "qty": 2}}, None)
    assert acct["holdings"][0]["bot"] and "mismatch" not in acct
    assert "불러오는 중" in web.render(dataclasses.replace(cfg, modes=("live",)), "kis-demo", "t")
    page = web.render(cfg, "paper", "t")
    assert "보유 종목 없음" in page and 'id=chart' in page and "</main>" in page


def test_afterhours_session_and_per_session_strategy(monkeypatch, tmp_path):
    from autostock import market_hours as mh
    from zoneinfo import ZoneInfo
    K = ZoneInfo("Asia/Seoul")
    monkeypatch.setattr(mh, "ENABLED", ("regular", "pre", "post", "day"))
    s = mh.current(datetime(2026, 11, 24, 7, 0, tzinfo=K))          # 화 07:00 KST = 월 17:00 ET
    assert s.name == "post" and s.key == "2026-11-23A"
    assert mh.current(datetime(2026, 11, 24, 9, 58, tzinfo=K)) is None
    assert mh.current(datetime(2026, 11, 24, 10, 1, tzinfo=K)).name == "day"
    assert mh.session_of("2026-11-23T17:00:00-05:00") == "post" and mh.session_of("2026-11-23T10:00:00-05:00") == "regular"
    assert mh.last_session(datetime(2026, 11, 24, 9, 58, tzinfo=K)).name == "post"

    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path), strategy="orb", ext_strategy="ai",
                              sessions=("regular", "pre", "post", "day"))
    m = Market(datetime(2026, 1, 5, 17, 0, tzinfo=ET))               # 애프터마켓
    brain = Brain(dec())
    e = Engine(cfg, m, PaperBroker(slippage_pct=0), brain, clock=lambda: m.now)
    e.tick()
    assert brain.snaps and brain.snaps[0]["session"] == "us_afterhours" and e.st.open   # Claude 가 판단해 진입
    m2 = Market(datetime(2026, 1, 5, 11, 0, tzinfo=ET))              # 정규장은 규칙 전략
    e2 = Engine(dataclasses.replace(cfg, data_dir=str(tmp_path / "b")), m2, PaperBroker(), Brain(dec()), clock=lambda: m2.now)
    assert e2._strategy(m2.now) == "orb" and e._strategy(m.now) == "ai"
    b = ClaudeBrain(cfg, client=SimpleNamespace())
    assert "규칙 전략 검토 모드" in b.review_system and "규칙 전략 검토 모드" not in b.system


def test_order_test_shared_between_regular_and_extended(rig):
    import os
    e, m, _ = rig(mode="live", modes=("live",))
    open(e._ok_file("live", "pre"), "w").close()                    # 프리마켓에서 통과했으면
    assert e.preflight(m.now) and not os.path.exists(e._ok_file("live"))   # 정규장은 다시 안 함


def test_orb_long_only_skips_downside(orb_rig):
    e, m, _ = orb_rig(bull="INTC", bear="", orb_peers=("SOXX",))
    m.px["INTC"] = 30.0
    m.bars_sym = "INTC"
    m.opens["SOXX"] = 251.0
    m.after, m.px["INTC"] = [29.2], 29.2
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None


def test_activity_log_once_per_minute(orb_rig, rig):
    import json
    from autostock import web, webdata
    e, m, _ = orb_rig()
    e.tick()
    m.now += timedelta(seconds=20)
    e.tick()                                                         # 같은 분: 추가 기록 없음
    m.after, m.px["SOXL"] = [30.8], 30.8
    m.now += timedelta(minutes=1)
    e.tick()
    acts = [json.loads(x) for x in open(e.act_path)]
    assert len(acts) == 2 and "돌파 대기" in acts[0]["msg"] and "범위 $29.50~$30.50" in acts[0]["msg"]
    assert acts[1]["msg"].startswith("보유 SOXL") and acts[1]["strategy"] == "개장 범위 돌파"
    assert [a["msg"] for a in webdata.activity(e.cfg, "paper", 1)] == [acts[1]["msg"]]
    assert "활동 로그" in web.render(e.cfg, "paper", "t")

    e2, m2, _ = rig(data_dir=e.cfg.data_dir + "/ai")                 # AI 전략: 다음 판단 시각과 직전 판단
    e2.tick()
    m2.now += timedelta(minutes=1)
    e2.tick()
    last = json.loads(open(e2.act_path).read().splitlines()[-1])
    assert "현금 대기" in last["msg"] and "다음 판단" in last["msg"] and "직전 판단" in last["msg"]


def test_polls_faster_while_holding(rig):
    e, m, _ = rig(dec(), tick_sec=10, hold_tick_sec=3)
    waits = []

    def sleep(s):
        waits.append(s)
        if len(waits) >= 2:
            raise KeyboardInterrupt
    e.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        e.run()
    assert waits[0] == 3                                             # 첫 틱에서 진입 → 3초 간격


def test_box_trade_inside_range_and_mid_stop(orb_rig):
    import json
    # 범위 29.5~30.5 (폭 3.3%) → 박스권 최소 폭 3% 로 낮춰 시험
    e, m, _ = orb_rig(box=True, box_min_width=3.0, box_zone=0.2, box_target=0.8, box_stop=0.1, box_max=1,
                      orb_stop_mode="mid", max_stop_loss_pct=6)

    class B:  # 아래 경계 근처에서 반등한 봉
        def __init__(self, ts, o, h, l, c): self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, 1
    real_bars = m.bars

    def bars(s, n=120):
        out = real_bars(s, n)
        if s == "SOXL" and m.now.minute >= 51:
            out[-1] = B(out[-1].ts, 29.55, 29.75, 29.55, 29.70)
        return out
    m.bars = bars
    m.now += timedelta(minutes=1)
    m.px["SOXL"] = 29.70
    e.tick()
    t = e.st.open
    assert t.symbol == "SOXL" and t.kind == "box" and t.trail_pct == 0
    assert abs(t.take_pct - (30.30 / 29.70 - 1) * 100) < 0.01          # 아래 경계 + 폭의 80% = 30.30
    assert abs(t.stop_pct - (1 - 29.40 / 29.70) * 100) < 0.01          # 아래 경계 - 폭의 10% = 29.40
    m.px["SOXL"] = 30.35
    m.now += timedelta(seconds=10)
    e.tick()
    assert e.st.open is None and e.st.history[-1]["kind"] == "box" and e.st.realized_usd > 0
    ev = [json.loads(x) for x in open(e.log_path)]
    assert any(x.get("entry_kind") == "box" for x in ev if x["kind"] == "buy")
    # 같은 세션 두 번째 박스권은 없음
    m.px["SOXL"] = 29.70
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None and "박스권 1회 모두 사용" in e.orb_status

    # 범위 돌파: 중간값 손절
    m.bars = real_bars
    m.after = [30.0, 30.0, 30.0, 31.0]
    m.px["SOXL"] = 31.0
    m.now = m.now.replace(minute=54, second=30)
    e.tick()
    t = e.st.open
    assert t.kind == "orb" and abs(t.stop_pct - (31.0 / 30.0 - 1) * 100) < 0.01 and t.trail_pct == 3.0


def test_box_skipped_when_range_narrow_or_broken(orb_rig):
    e, m, _ = orb_rig(box=True, box_min_width=5.0)
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None and "박스권 안 함" in e.orb_status


def test_volatility_filter_and_risk_sizing(orb_rig, kis):
    import json
    # 증권사 일봉: 최근 5일 평균 4% → 기준 8% 미만이라 쉼
    e, m, _ = orb_rig(vol_filter_min=8)
    m.daily_ranges = lambda s, n=8: [("20260105", 20.0)] + [(f"2026010{d}", 4.0) for d in (2, 1)] + [("20251231", 4.0), ("20251230", 4.0)]
    m.after, m.px["SOXL"] = [30.8], 30.8
    m.now += timedelta(minutes=1)
    e.tick()
    assert e.st.open is None and "오늘 쉼" in e.orb_status and "4.0%" in e.orb_status   # 오늘(1/5) 값은 제외

    # 일봉 조회 실패 → 봇 기록으로, 그것도 부족하면 필터 없이 매매
    e2, m2, _ = orb_rig(vol_filter_min=8, data_dir=e.cfg.data_dir + "/b")
    def boom(*a, **k):
        raise RuntimeError("no daily")
    m2.daily_ranges = boom
    m2.after, m2.px["SOXL"] = [30.8], 30.8
    m2.now += timedelta(minutes=1)
    e2.tick()
    assert e2.st.open is not None and "필터 없이" in e2.orb["2026-01-05"]["vol_src"]
    rec = json.load(open(e2._ranges_path()))
    assert rec["2026-01-05"] > 0                                     # 오늘 변동폭을 직접 기록
    json.dump({"2026-01-01": 12, "2026-01-02": 10, "2026-01-03": 11, **rec}, open(e2._ranges_path(), "w"))
    vol, src = e2._vol5(SimpleNamespace(open=datetime(2026, 1, 6, 9, 30, tzinfo=ET), key="2026-01-06"))
    assert src == "봇 기록" and vol > 8

    # 손절 폭에 맞춘 수량: 자본 $714, 손절 5% → 3% 위험이면 $21.4 / ($30 × 5%) = 14주
    r = Risk(dataclasses.replace(Settings(), risk_per_trade_pct=3, max_stop_loss_pct=6, fee_pct=0))
    assert r.size(DayState(), dec(stop=5.0), 30.0) == 14
    assert Risk(dataclasses.replace(Settings(), max_stop_loss_pct=6, fee_pct=0)).size(DayState(), dec(stop=5.0), 30.0) == 23

    # KIS 일봉 파싱
    c, _ = kis("real")
    orig = c.http.get
    c.http.get = lambda url, **kw: (SimpleNamespace(status_code=200, text="", json=lambda: {"rt_cd": "0", "output2": [
        {"xymd": "20260105", "open": "30", "high": "33", "low": "30"}, {"xymd": "20260102", "open": "0", "clos": "40", "high": "42", "low": "38"}]})
        if url.endswith("dailyprice") else orig(url, **kw))
    assert KISMarket(c).daily_ranges("SOXL") == [("20260105", 10.0), ("20260102", 10.0)]


def test_noise_book_sigma_and_engine_entry_exit(orb_rig, monkeypatch, tmp_path):
    from autostock.noise import NoiseBook
    b = NoiseBook(str(tmp_path / "n.json"))
    for k in range(14):                                              # 14일 모두 30분 시점에 +2% 움직였던 기록
        day = f"2025-12-{k + 10:02d}"
        b.record(day, open_=30.0, offset=30, price=30.6, close=30.0)
    b.save()
    assert abs(NoiseBook(str(tmp_path / "n.json")).sigma("2026-01-05", 30) - 0.02) < 1e-9
    assert b.sigma("2026-01-05", 60) is None and b.prev_close("2026-01-05") == 30.0

    e, m, _ = orb_rig(noise=True, max_stop_loss_pct=6)
    e.noise_book = b
    m.now = datetime(2026, 1, 5, 10, 0, 20, tzinfo=ET)                # 개장 후 30분 확인 시점
    m.after = [30.0] * 9 + [30.9]                                    # 9:59 봉 종가 30.9 > 30.0×1.02
    m.px["SOXL"] = 30.9
    e.tick()
    t = e.st.open
    assert t and t.kind == "noise" and t.symbol == "SOXL" and t.stop_pct == 6.0
    assert b.days["2026-01-05"]["m"]["30"] == 30.9                   # 오늘 기록도 남김
    m.now = datetime(2026, 1, 5, 10, 15, 20, tzinfo=ET)              # 확인 시점 아님: 그대로 보유
    e.tick()
    assert e.st.open and "노이즈" in e.orb_status
    for k in range(14):
        b.record(f"2025-12-{k + 10:02d}", offset=60, price=30.6)
    m.after = [30.0] * 39 + [30.3]                                   # 10:29 봉 30.3 < 상단 30.6 → 청산
    m.px["SOXL"] = 30.3
    m.now = datetime(2026, 1, 5, 10, 30, 20, tzinfo=ET)
    e.tick()
    assert e.st.open is None and "노이즈 영역 복귀" in e.st.history[-1]["reason"] and e.st.history[-1]["kind"] == "noise"


def test_noise_bootstrap_from_yahoo_payload(tmp_path, monkeypatch):
    import io
    import urllib.request
    from autostock.noise import NoiseBook
    t0 = int(datetime(2026, 1, 2, 9, 30, tzinfo=ET).timestamp())
    ts = [t0 + 300 * i for i in range(78)]
    payload = {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{
        "open": [30.0 + i * 0.01 for i in range(78)], "close": [30.0 + (i + 1) * 0.01 for i in range(78)]}]}}]}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))
    b = NoiseBook(str(tmp_path / "n.json"))
    assert b.bootstrap_yahoo("SOXL") == 1
    d = b.days["2026-01-02"]
    assert d["open"] == 30.0 and d["m"]["30"] == 30.06 and d["m"]["360"] == 30.72 and d["close"] == 30.78


def test_ledger_compounds_and_resets_on_capital_change(rig):
    import json
    e, m, _ = rig(dec(stop=1.0), dec())
    e.tick()
    assert e.st.open.qty == 23                                       # $714 / $30
    step(e, m, SOXL=29.6)                                            # 손절
    loss = e.ledger["realized_usd"]
    assert loss < 0 and json.load(open(e.ledger_path))["realized_usd"] == loss
    e2 = Engine(e.cfg, m, PaperBroker(slippage_pct=0), Brain(dec()), clock=lambda: m.now)   # 다음 날·재시작
    assert e2.equity_usd == e.cfg.capital_usd + loss                 # 채우지 않음
    e2.st.roll("2026-01-06")
    m.px["SOXL"] = 30.0
    m.now += timedelta(days=1)
    e2.tick()
    assert e2.st.open.qty == int((e.cfg.capital_usd + loss) / 30.0)  # 줄어든 자산 기준 수량
    e3 = Engine(dataclasses.replace(e.cfg, capital_krw=2_000_000), m, PaperBroker(), Brain(), clock=lambda: m.now)
    assert e3.ledger["realized_usd"] == 0                            # 시작 자금이 바뀌면 새로 시작


def test_chart_shows_bounds_on_soxl_only(tmp_path, monkeypatch):
    from autostock import market_hours, webdata
    store = webdata.BarStore(str(tmp_path / "b.json"))
    d0 = datetime.now(ET) - timedelta(days=1)
    while d0.weekday() >= 5:
        d0 -= timedelta(days=1)
    t0 = d0.replace(hour=9, minute=30, second=0, microsecond=0)
    for s_ in ("SOXL", "SOXS"):
        store.merge(s_, [Bar(t0 + timedelta(minutes=i), 40, 40, 40, 40, 1) for i in range(5)])
    monkeypatch.setattr(market_hours, "now_et", lambda: t0 + timedelta(minutes=6))
    monkeypatch.setattr(webdata, "market", lambda cfg: None)
    live = {"orb": {"hh": 42.0, "ll": 38.0, "symbol": "SOXL", "box": [38.8, 41.2], "noise": [30.0, 50.0]}}
    d = webdata.chart(Settings(), "paper", "SOXS", 0, store, None, live, [])
    assert d["lines"] == [] and d["range"] is None
    d = webdata.chart(Settings(), "paper", "SOXL", 0, store, None, live, [])
    assert [x["k"] for x in d["lines"]] == ["rng", "rng", "box", "box"]              # 노이즈 선 없음

def test_chart_draws_range_without_bot_state(tmp_path, monkeypatch):
    from autostock import market_hours, webdata
    from autostock.noise import NoiseBook
    store = webdata.BarStore(str(tmp_path / "b.json"))
    d0 = datetime.now(ET) - timedelta(days=1)
    while d0.weekday() >= 5:
        d0 -= timedelta(days=1)
    t0 = d0.replace(hour=9, minute=30, second=0, microsecond=0)
    store.merge("SOXL", [Bar(t0 + timedelta(minutes=i), 40, 40 + (i % 5) / 10, 40 - (i % 3) / 10, 40, 1) for i in range(40)])
    book = NoiseBook(str(tmp_path / "noise_SOXL.json"))
    for k in range(14):
        book.record((d0 - timedelta(days=20 - k)).strftime("%Y-%m-%d"), open_=40.0, offset=30, price=40.8, close=40.0)
    book.save()
    monkeypatch.setattr(market_hours, "now_et", lambda: t0 + timedelta(minutes=40))
    monkeypatch.setattr(webdata, "market", lambda cfg: None)
    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path), strategy="orb", box=True, box_min_width=0.5, noise=True)
    d = webdata.chart(cfg, "paper", "SOXL", 0, store, None, None, [])      # 봇 상태 파일 없음
    v = {x["l"]: x["v"] for x in d["lines"]}
    assert d["range"] == [39.8, 40.4] and v["범위 상단"] == 40.4 and v["범위 하단"] == 39.8
    assert "박스 SOXL 매수 구간 (이 아래)" in v
    assert not any("노이즈" in k for k in v)


def _ext_history(path):
    """매일 애프터 16:00 에 박스 하단으로 내려왔다가 다음 5분에 +1% 넘게 오르는 가짜 5분봉 40일."""
    rows, d = [], datetime(2026, 9, 1, tzinfo=ET)
    while len({r[0] // 86400 for r in rows}) < 40:
        if d.weekday() < 5:
            t = d.replace(hour=15, minute=0)
            for i in range(12):
                rows.append([int((t + timedelta(minutes=5 * i)).timestamp()), 100, 101, 99, 100])
            t16 = int(d.replace(hour=16).timestamp())
            rows.append([t16, 100, 100, 99.1, 99.2])
            rows.append([t16 + 300, 99.2, 100.3, 99.2, 100.2])
        d += timedelta(days=1)
    with open(path, "w") as f:
        json.dump(rows, f)


def test_ext_box_zone_and_history_odds(tmp_path):
    from autostock import extbox
    assert extbox.session(datetime(2026, 11, 23, 5, 0, tzinfo=ET))[0] == "pre"
    assert extbox.session(datetime(2026, 11, 23, 17, 0, tzinfo=ET))[0] == "post"
    assert extbox.session(datetime(2026, 11, 23, 12, 0, tzinfo=ET)) is None
    assert extbox.session(datetime(2026, 11, 22, 5, 0, tzinfo=ET)) is None                 # 일요일
    assert extbox.next_session(datetime(2026, 11, 23, 12, 0, tzinfo=ET))[0] == "post"
    assert [extbox.zone(p, 101, 99) for p in (101.5, 100.8, 100, 99.2, 98)] == ["above", "top", "mid", "bottom", "below"]
    t0 = int(datetime(2026, 11, 23, 16, 0, tzinfo=ET).timestamp() * 1000)
    bars = [[t0 + i * 60000, 100, 101, 99, 100, 1] for i in range(60)] + [[t0 + 60 * 60000, 100, 102, 100, 101.8, 1]]
    assert extbox.live_box(bars) == (101, 99)                                               # 지금 봉은 박스에서 뺌
    assert extbox.live_box(bars[-10:]) is None                                              # 자료 부족
    p = str(tmp_path / "h.json")
    _ext_history(p)
    st = extbox.stats(p, 1.0)
    b = st["by"]["post"]["bottom"]
    assert b["up"] == 40 and b["dn"] == 0 and st["days"] == 40
    assert b["ev_up"] == pytest.approx(1.0 - 0.7) and b["ev_dn"] == pytest.approx(-1.0 - 0.7)
    assert extbox.verdict(b)[0] == "up"
    assert extbox.verdict({**b, "old": [3, 0]})[0] == ""                                   # 한쪽 기간 사례가 적으면 고르지 않음
    assert extbox.verdict({**b, "up": 16, "dn": 14})[0] == ""                              # 비슷하면 관망


def test_ext_tab_chart_card_and_page(tmp_path, monkeypatch):
    from autostock import extbox, market_hours, web, webdata
    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path))
    _ext_history(webdata.ext_hist_path(cfg))
    store = webdata.BarStore(str(tmp_path / "b.json"))
    now = datetime(2026, 11, 23, 16, 50, 20, tzinfo=ET)
    t0 = now.replace(second=0) - timedelta(minutes=65)
    store.merge("SOXL", [Bar(t0 + timedelta(minutes=i), 100, 101, 99, 100, 1) for i in range(65)]
                + [Bar(now.replace(second=0), 100, 100, 99.1, 99.2, 1)])
    store.merge("SOXS", [Bar(now.replace(second=0), 20, 20, 20, 20, 1)])
    monkeypatch.setattr(market_hours, "now_et", lambda: now)
    monkeypatch.setattr(webdata, "market", lambda c: None)
    d = webdata.ext_chart(cfg, "SOXL", 120, store, 1.0)
    adv = d.pop("advice")
    assert adv["zone"] == "bottom" and adv["side"] == "up" and d["range"] == [99, 101]
    assert [x["l"] for x in d["lines"]] == ["박스 상단 (직전 60분 고가)", "박스 하단 (직전 60분 저가)", "목표 +1%", "손절 -1%"]
    assert d["lines"][2]["v"] == pytest.approx(99.2 * 1.01)
    s = webdata.ext_chart(cfg, "SOXS", 120, store, 1.0)
    assert s["lines"] == [] and s["range"] is None                                         # SOXS 차트에는 박스 없음
    html_ = web.ext_card(adv, cfg)
    assert "박스 하단 구간" in html_ and "확률이 더 높은 쪽: SOXL 매수" in html_ and "$100.19" in html_
    assert "맞힐 확률이 85%" in html_
    page = web.render_ext(cfg, "tok", now.astimezone(web.KST))
    assert "시간외 직접 매매" in page and "data-mode='ext'" in page and "애프터마켓" in page
    assert "mode=ext" in web.render(cfg, "paper", "tok")                                   # 다른 탭에서도 이동 가능
    monkeypatch.setattr(extbox, "yahoo_1m", lambda sym: [])                               # 야후도 새 봉이 없을 때
    monkeypatch.setattr(market_hours, "now_et", lambda: now + timedelta(minutes=10))       # 시세가 멈추면 판단 안 함
    adv = webdata.ext_chart(cfg, "SOXL", 120, store, 1.0)["advice"]
    assert "side" not in adv and "멈춰" in web.ext_card(adv, cfg)


def test_ext_tab_falls_back_to_yahoo_bars(tmp_path, monkeypatch):
    from autostock import extbox, market_hours, webdata
    cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path))
    store = webdata.BarStore(str(tmp_path / "b.json"))
    now = datetime(2026, 11, 23, 5, 30, 10, tzinfo=ET)
    t0 = now.replace(second=0) - timedelta(minutes=70)
    calls = []

    def fake(sym):
        calls.append(sym)
        px = 100 if sym == "SOXL" else 20
        return [Bar(t0 + timedelta(minutes=i), px, px + 1, px - 1, px, 1) for i in range(71)]
    monkeypatch.setattr(extbox, "yahoo_1m", fake)
    monkeypatch.setattr(market_hours, "now_et", lambda: now)
    monkeypatch.setattr(webdata, "market", lambda c: None)
    webdata._yahoo_at.clear()
    d = webdata.ext_chart(cfg, "SOXL", 120, store, 1.0)
    assert calls == ["SOXL", "SOXS"] and d["advice"]["zone"] == "mid" and "야후" in d["note"]
    webdata.ext_chart(cfg, "SOXL", 120, store, 1.0)
    assert calls == ["SOXL", "SOXS"]                                                       # 이미 채워졌으면 다시 안 부름
