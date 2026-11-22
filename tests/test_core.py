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
        cfg = dataclasses.replace(Settings(), data_dir=str(tmp_path), decision_interval_sec=60,
                                  fee_pct=0.0, **over)
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
        if url.endswith("/order"):
            self.pending = int(json["ORD_QTY"]) * (1 if json["SLL_TYPE"] == "" else -1)
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
    assert "최근 AI 판단" in page and "&lt;script&gt;" in page and "<script>x" not in page
    assert "아직 기록이 없습니다" in web.render(cfg, "live", "tok")


def test_preflight_gates_real_order_modes(rig, monkeypatch):
    import os
    e, m, brain = rig(dec(), mode="live", modes=("kis-demo", "live"))
    e.tick()
    assert e.st.open is None and not brain.snaps                    # 모의투자 테스트 통과 전: 대기
    open(e._ok_file("kis-demo"), "w").close()
    e.tick()                                                         # 실계좌 테스트(1주 왕복) 후 매매 시작
    assert os.path.exists(e._ok_file("live")) and e.st.open and e.st.open.qty > 1

    e2, m2, brain2 = rig(dec(), mode="kis-demo", modes=("kis-demo",))
    os.remove(e2._ok_file("kis-demo"))
    e2.broker.buy = lambda *a: None                                  # 매수 미체결
    e2.tick()
    assert e2.st.halted == "주문 테스트 실패" and not brain2.snaps
    assert not e2.st.roll(e2.st.date) and e2.st.roll("2026-01-06") and e2.st.halted == ""
