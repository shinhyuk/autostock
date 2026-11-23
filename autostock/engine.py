"""메인 루프: 빠른 주기로 손절/익절을 감시하고, 느린 주기로 AI에게 판단을 묻는다."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable

from . import indicators
from .config import Settings
from . import market_hours
from .market_hours import CLOSE, is_open, minutes_since_open, minutes_to_close, now_et
from .models import Broker, Decision, MarketData
from .risk import Risk
from .state import DayState, OpenTrade

log = logging.getLogger("engine")


def order_test(cfg: Settings, market: MarketData, broker: Broker, out=log.info) -> bool:
    """1주 매수 → 즉시 매도로 실제 주문 경로를 확인한다. 수수료와 호가 차이만큼 소액 손실이 난다."""
    sym = cfg.order_test_symbol or cfg.bull
    if broker.position(sym):
        out(f"이미 {sym} 보유 중이라 주문 테스트를 하지 않습니다.")
        return False
    last = market.quote(sym).last
    out(f"[{cfg.mode}] 주문 테스트: {sym} 현재가 ${last} — 1주 매수…")
    buy = broker.buy(sym, 1, last)
    if not buy:
        out("[FAIL] 매수가 체결되지 않아 취소됐습니다. 잔고(달러/통합증거금)와 해외주식 거래 신청을 확인하세요.")
        return False
    out(f"[OK]   매수 체결 {buy.qty}주 @ ${buy.price}")
    if not cfg.order_test_sell:
        out("매도는 하지 않고 보유합니다. 이후 손절·익절·AI 판단·세션 마감 청산으로 관리됩니다.")
        return True
    for attempt in range(3):
        sell = broker.sell(sym, 1, market.quote(sym).last)
        if sell:
            out(f"[OK]   매도 체결 {sell.qty}주 @ ${sell.price}  (차이 ${sell.price - buy.price:+.2f}, 수수료 별도)")
            return True
        out(f"매도 미체결, 재시도 {attempt + 1}/3…")
    out(f"[FAIL] 매도가 체결되지 않았습니다. {sym} 1주가 계좌에 남아 있습니다.")
    return False


class Engine:
    def __init__(self, cfg: Settings, market: MarketData, broker: Broker, brain,
                 clock: Callable[[], datetime] = now_et, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.market, self.broker, self.brain = cfg, market, broker, brain
        self.clock, self.sleep = clock, sleep
        self.risk = Risk(cfg)
        self.state_path = os.path.join(cfg.data_dir, f"state_{cfg.mode}.json")
        self.log_path = os.path.join(cfg.data_dir, f"journal_{cfg.mode}.jsonl")
        self.live_path = os.path.join(cfg.data_dir, f"live_{cfg.mode}.json")
        self._last_price: float | None = None
        self.st = DayState.load(self.state_path)
        self._refresh_halt()
        self.last_decision_at: datetime | None = None
        self.recent_decisions: list[dict] = []
        self._waiting_logged = ""
        self.orb: dict[str, dict] = {}               # 세션별 개장 범위와 동조 종목 시가
        self.orb_status = ""
        self._orb_minute: datetime | None = None
        self.ref_prices: dict[str, float] = {}       # 직전 AI 판단 때의 가격 (급변 감지용)
        self.trigger = "scheduled"

    def _refresh_halt(self) -> None:
        """목표·손실 한도·연속 손실로 멈춘 상태는 현재 설정으로 다시 판단한다 (설정을 바꾸고 재시작한 경우)."""
        h = self.st.halted
        if h in ("일일 목표 달성", "일일 손실 한도") or h.endswith("연속 손실"):
            new = self.risk.halt_reason(self.st)
            if new != h:
                log.info("중단 상태 재평가: %s → %s", h, new or "매매 재개")
                self.st.halted = new
                self.st.save(self.state_path)

    # ── 기록 ────────────────────────────────────────────────
    def _journal(self, kind: str, **data) -> None:
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.clock().isoformat(), "kind": kind, **data},
                               ensure_ascii=False) + "\n")

    def _beat(self, now: datetime, status: str) -> None:
        """결과 페이지가 읽는 현재 상태(봇이 살아 있는지, 현재가, 평가손익)."""
        t, last = self.st.open, self._last_price
        data = {"ts": now.isoformat(), "status": status, "model": getattr(self.cfg, "model", ""),
                "last": last, "unrealized_usd": round(self.risk.unrealized(t, last), 2) if t and last else None}
        if self.cfg.strategy == "orb":
            o = self.orb.get(market_hours.session_key(now)) or {}
            data["orb"] = {"minutes": self.cfg.orb_minutes, "hh": o.get("hh"), "ll": o.get("ll"),
                           "status": self.orb_status, "symbol": self.cfg.bull}
        sess = market_hours.current(now)
        data["session"] = sess.name if sess else ""
        data["strategy"] = self._strategy(now) if sess else ""
        try:
            os.makedirs(self.cfg.data_dir, exist_ok=True)
            tmp = self.live_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.live_path)
        except OSError:
            pass

    def _krw(self, usd: float) -> str:
        return f"{usd * self.cfg.usdkrw:+,.0f}원"

    # ── 시작 시 계좌와 상태 맞추기 ──────────────────────────
    def reconcile(self) -> None:
        held = [p for s in self.cfg.symbols if (p := self.broker.position(s))]
        t = self.st.open
        if t and not any(p.symbol == t.symbol for p in held):
            log.warning("상태에는 %s 보유인데 계좌에 없음 → 상태 정리", t.symbol)
            self.st.open = None
        if held and not self.st.open:
            p = held[0]
            log.warning("계좌에 기존 %s %d주 발견 → 기본 손절/익절로 관리 시작", p.symbol, p.qty)
            self.st.open = OpenTrade(p.symbol, p.qty, p.avg_price, self.clock().isoformat(),
                                     self.cfg.max_stop_loss_pct, self.cfg.default_take_profit_pct,
                                     self.risk.fee(p.avg_price, p.qty))
        elif self.st.open:
            self.st.open.qty = next(p.qty for p in held if p.symbol == self.st.open.symbol)
        self.st.save(self.state_path)

    # ── 실주문 모드의 사전 점검 ─────────────────────────────
    def _ok_file(self, mode: str, session: str = "regular") -> str:
        suffix = "" if session == "regular" else f"_{session}"
        return os.path.join(self.cfg.data_dir, f"ordertest_{mode}{suffix}.ok")

    def preflight(self, now: datetime) -> bool:
        """kis-demo / live 는 1주 왕복 주문 테스트를 통과해야 매매를 시작한다(통과하면 다음부터 생략).
        세션(정규장/프리마켓/주간거래)마다 주문 방식이 달라 따로 확인한다. 실패하면 1분 뒤 재시도."""
        c = self.cfg
        sess = market_hours.current(now)
        sname = sess.name if sess else "regular"
        if c.mode == "kis-demo" and sname != "regular":
            return False             # 모의투자는 정규장에서만 돌린다(주간거래·프리마켓 주문 미지원)
        if c.mode not in ("kis-demo", "live") or os.path.exists(self._ok_file(c.mode, sname)):
            return True
        if self.st.halted or minutes_since_open(now) < c.no_entry_after_open_min:
            return False
        if minutes_to_close(now) < c.no_entry_before_close_min:
            return False
        st = self.st
        if st.test_last_ts and (now - datetime.fromisoformat(st.test_last_ts)).total_seconds() < 60:
            return False             # 실패 후 1분 뒤 재시도
        lines: list[str] = []

        def out(msg: str) -> None:
            lines.append(msg)
            log.info(msg)

        try:
            ok = order_test(c, self.market, self.broker, out=out)
        except Exception as e:
            log.exception("주문 테스트 중 오류")
            lines.append(f"오류: {type(e).__name__}: {e}")
            ok = False
        st.test_attempts += 1
        st.test_last_ts = now.isoformat()
        st.test_symbol = c.order_test_symbol or c.bull
        self._journal("ordertest", ok=ok, session=sname, attempt=st.test_attempts, detail=" / ".join(lines))
        if ok:
            with open(self._ok_file(c.mode, sname), "w") as f:
                f.write(now.isoformat())
            log.info("주문 테스트 통과 — %s (%s 세션) 매매를 시작합니다.", c.mode, sname)
            if not c.order_test_sell:
                self.reconcile()     # 테스트로 산 1주를 보유 포지션으로 넘겨받는다
                if t := self.st.open:
                    self._journal("buy", symbol=t.symbol, qty=t.qty, price=t.entry_price, stop_pct=t.stop_pct,
                                  take_pct=t.take_pct, reason="주문 테스트 매수 (보유로 전환)")
        elif any("APBK16" in x for x in lines):
            # 계좌 요건(거래 신청, 교육 이수, 기본예탁금 등) 거절은 재시도해도 같으므로 이번 세션은 멈춘다
            st.halted = "계좌 요건 미충족으로 주문 거절"
            log.error("계좌 요건 미충족으로 주문이 거절됨 — 이번 세션 %s 매매 중단, 다음 세션에 다시 확인", c.mode)
        else:
            if st.test_attempts >= 200:
                st.halted = "주문 테스트 반복 실패"
                log.error("주문 테스트 200회 실패 — 이번 세션 %s 매매는 하지 않습니다.", c.mode)
            else:
                log.error("주문 테스트 실패 (%d회차) — 1분 뒤 다시 시도합니다.", st.test_attempts)
            self.reconcile()         # 테스트로 산 1주가 남았다면 손절/익절/마감청산으로 관리
        st.save(self.state_path)
        return ok

    # ── 주문 ────────────────────────────────────────────────
    def _enter(self, d: Decision, last: float, atr_pct: float | None = None, trail: float | None = None) -> None:
        qty = self.risk.size(self.st, d, last)
        if qty < 1:
            self._reject(d, "수량 0 (자금 또는 손실 여유 부족)")
            return
        fill = self.broker.buy(d.symbol, qty, last)
        if not fill:
            self._reject(d, "매수 미체결")
            return
        stop, take = self.risk.stops(d)
        trail = trail if trail is not None else self.risk.trail(stop, atr_pct)
        self.st.open = OpenTrade(d.symbol, fill.qty, fill.price, self.clock().isoformat(),
                                 stop, take, self.risk.fee(fill.price, fill.qty), fill.price, trail)
        self.st.save(self.state_path)
        log.info("▶ 매수 %s %d주 @ $%.2f  (손절 -%.1f%% / 익절 +%.1f%% / 추적 %.1f%%)  %s",
                 d.symbol, fill.qty, fill.price, stop, take, trail, d.reason)
        self._journal("buy", symbol=d.symbol, qty=fill.qty, price=fill.price,
                      stop_pct=stop, take_pct=take, reason=d.reason)

    def _close(self, reason: str, last: float) -> bool:
        t = self.st.open
        assert t is not None
        fill = self.broker.sell(t.symbol, t.qty, last)
        if not fill:
            log.error("매도 미체결(%s) — 다음 틱에 재시도", reason)
            return False
        share = fill.qty / t.qty
        pnl = (fill.price - t.entry_price) * fill.qty - t.buy_fee * share - self.risk.fee(fill.price, fill.qty)
        st = self.st
        st.realized_usd += pnl
        if fill.qty < t.qty:        # 부분 체결: 남은 수량은 계속 보유
            t.buy_fee *= 1 - share
            t.qty -= fill.qty
        else:
            st.open = None
            st.trades += 1
            if pnl >= 0:
                st.wins, st.consecutive_losses = st.wins + 1, 0
            else:
                st.losses, st.consecutive_losses = st.losses + 1, st.consecutive_losses + 1
                st.last_loss_ts, st.last_loss_symbol = self.clock().isoformat(), t.symbol
        st.history.append({"symbol": t.symbol, "qty": fill.qty, "entry": t.entry_price,
                           "exit": fill.price, "pnl_usd": round(pnl, 2), "reason": reason,
                           "ts": self.clock().strftime("%H:%M")})
        log.info("◀ 매도 %s %d주 @ $%.2f  손익 $%+.2f (%s)  [%s]  당일 누적 $%+.2f (%s)",
                 t.symbol, fill.qty, fill.price, pnl, self._krw(pnl), reason,
                 st.realized_usd, self._krw(st.realized_usd))
        self._journal("sell", symbol=t.symbol, qty=fill.qty, price=fill.price,
                      pnl_usd=round(pnl, 2), reason=reason, day_usd=round(st.realized_usd, 2))
        if not st.halted and (h := self.risk.halt_reason(st)):
            st.halted = h
            log.info("■ 당일 매매 종료: %s", h)
        st.save(self.state_path)
        return st.open is None

    def _reject(self, d: Decision, why: str) -> None:
        log.info("진입 거부: %s  (AI: %s %s)", why, d.action, d.symbol)
        if self.recent_decisions:
            self.recent_decisions[-1]["rejected"] = why

    # ── AI 판단 ─────────────────────────────────────────────
    def snapshot(self, now: datetime) -> dict:
        c, st = self.cfg, self.st
        sess = market_hours.current(now)
        since = sess.open if sess else None
        market = {}
        for s in c.symbols:
            q, bars = self.market.quote(s), self.market.bars(s, 120)
            today = [b for b in bars if since and b.ts >= since]
            market[s] = {
                "last": q.last,
                "day_change_pct": round((q.last / q.prev_close - 1) * 100, 2) if q.prev_close else None,
                "day_high": max((b.high for b in today), default=None),
                "day_low": min((b.low for b in today), default=None),
                **indicators.summarize(bars, since),
                "last_bar_age_min": round((now - bars[-1].ts).total_seconds() / 60, 1) if bars else None,
            }
            if s == c.bull:   # 봉 데이터는 한 종목만(반대 종목은 거의 거울상)
                market[s]["bars_1m"] = {
                    "columns": "HH:MM,open,high,low,close,volume",
                    "rows": [f"{b.ts:%H:%M},{b.open:.2f},{b.high:.2f},{b.low:.2f},{b.close:.2f},{b.volume:.0f}"
                             for b in bars[-40:]]}
        sector = {}                                  # 주변 종목: 실패해도 판단은 계속한다
        for i, s in enumerate(c.context):
            try:
                q = self.market.quote(s)
                row = {"last": q.last,
                       "day_change_pct": round((q.last / q.prev_close - 1) * 100, 2) if q.prev_close else None}
                if i < c.context_bars:
                    b = self.market.bars(s, 120)
                    full = indicators.summarize(b)
                    row.update({k: full[k] for k in ("ret_5m_pct", "ret_15m_pct", "ret_60m_pct", "rsi14")})
                sector[s] = row
            except Exception as e:
                log.warning("주변 종목 %s 시세 실패: %s", s, e)
        pos = None
        if t := st.open:
            last = market[t.symbol]["last"]
            pos = {"symbol": t.symbol, "qty": t.qty, "entry_price": t.entry_price,
                   "change_pct": round((last / t.entry_price - 1) * 100, 2),
                   "unrealized_usd": round(self.risk.unrealized(t, last), 2),
                   "held_min": round((now - datetime.fromisoformat(t.entry_ts)).total_seconds() / 60),
                   "peak_change_pct": round((max(t.peak_price, last) / t.entry_price - 1) * 100, 2),
                   "stop_loss_pct": t.stop_pct, "take_profit_pct": t.take_pct,
                   "trailing_stop_pct": t.trail_pct}
        return {
            "time_et": now.strftime("%Y-%m-%d %H:%M"),
            "trigger": self.trigger,
            "session": {"day": "daytime_korea_hours", "pre": "us_premarket", "post": "us_afterhours"}.get(
                sess.name if sess else "", "us_regular"),
            "minutes_since_open": round(minutes_since_open(now)),
            "minutes_to_close": round(minutes_to_close(now)),
            "market": market,
            "sector": sector,
            "account": {
                "capital_usd": round(c.capital_usd, 2),
                "day_realized_usd": round(st.realized_usd, 2),
                "day_target_usd": round(c.target_usd, 2),
                "day_max_loss_usd": round(c.max_loss_usd, 2),
                "trades_today": st.trades, "max_trades": c.max_trades_per_day,
                "wins": st.wins, "losses": st.losses,
                "round_trip_fee_pct": c.fee_pct * 2,
                "max_stop_loss_pct": c.max_stop_loss_pct,
                "min_confidence_to_enter": c.min_confidence,
                "take_profit_cap_pct": min(10.0, c.take_profit_max_pct),
                "max_hold_min": c.max_hold_min or None,
                "position": pos,
            },
            "closed_trades_today": st.history[-6:],
            "recent_decisions": self.recent_decisions[-6:],
        }

    def _ask_ai(self, now: datetime) -> None:
        snap = self.snapshot(now)
        self.ref_prices = {s: m["last"] for s, m in snap["market"].items()}
        d: Decision = self.brain.decide(snap)
        log.info("AI: %s %s (확신 %.2f) — %s", d.action, d.symbol, d.confidence, d.reason)
        self.recent_decisions.append({"time": now.strftime("%H:%M"), "action": d.action,
                                      "symbol": d.symbol, "reason": d.reason})
        del self.recent_decisions[:-20]
        self._journal("decision", **d.model_dump())
        t = self.st.open

        if d.action == "HOLD":
            return
        if d.action == "SELL":
            if t:
                self._close("AI 청산: " + d.reason, self.market.quote(t.symbol).last)
            return
        # BUY
        if t and t.symbol == d.symbol:
            return                                   # 추가 매수(물타기) 없음
        if why := self.risk.entry_block(self.st, now, d):
            self._reject(d, why)
            return
        ages = [m["last_bar_age_min"] for m in snap["market"].values()]
        stale = 6 if snap["session"] != "us_regular" else 3
        if any(a is None or a > stale for a in ages):
            self._reject(d, "시세가 갱신되지 않음(휴장/지연 추정)")
            return
        if t and not self._close("반대 방향 전환: " + d.reason, self.market.quote(t.symbol).last):
            return
        if self.st.halted:
            return
        last = self.market.quote(d.symbol).last      # 판단에 걸린 시간 동안 가격이 달아났는지 확인
        if abs(last / snap["market"][d.symbol]["last"] - 1) * 100 > 0.5:
            self._reject(d, "판단 중 가격이 0.5% 이상 움직임")
            return
        self._enter(d, last, snap["market"][d.symbol].get("atr14_pct"))

    def _strategy(self, now: datetime) -> str:
        sess = market_hours.current(now)
        if sess and sess.name != "regular" and self.cfg.ext_strategy:
            return self.cfg.ext_strategy
        return self.cfg.strategy

    # ── 개장 범위 돌파(ORB) 전략 ────────────────────────────
    def _orb_tick(self, now: datetime) -> None:
        """개장 후 orb_minutes 분의 고가·저가를 범위로 잡고, 1분봉 종가가 범위를 벗어나면 그 방향으로 진입한다.
        엔비디아·SOXX 가 개장가 대비 같은 방향이어야 한다. 청산은 손절·익절·추적 손절·장 마감 청산(코드).
        최근 20거래일 백테스트에서 고른 규칙이다(research/README.md)."""
        c = self.cfg
        sess = market_hours.current(now)
        if not sess or sess.name != "regular":
            self.orb_status = "정규장에서만 매매"
            return
        since = minutes_since_open(now)
        if since < c.orb_minutes:
            self.orb_status = f"범위 형성 중 ({c.orb_minutes - since:.0f}분 남음)"
            return
        minute = now.replace(second=0, microsecond=0)
        if self._orb_minute == minute:               # 1분봉 기준이라 분당 한 번만 본다
            return
        self._orb_minute = minute
        o = self.orb.get(sess.key)
        if o is None:
            end = sess.open + timedelta(minutes=c.orb_minutes)
            rb = [b for b in self.market.bars(c.bull, 120) if sess.open <= b.ts < end]
            if len(rb) < c.orb_minutes * 0.7:
                self.orb_status = "개장 범위 데이터 부족"
                log.warning("개장 범위 봉이 부족함 (%d개)", len(rb))
                return
            o = {"hh": max(b.high for b in rb), "ll": min(b.low for b in rb), "peers": {}}
            for p in c.orb_peers:
                try:
                    pb = [b for b in self.market.bars(p, 120) if b.ts >= sess.open]
                    o["peers"][p] = pb[0].open if pb else None
                except Exception as e:
                    log.warning("동조 종목 %s 시가 조회 실패: %s", p, e)
                    o["peers"][p] = None
            self.orb[sess.key] = o
            log.info("개장 %d분 범위: $%.2f ~ $%.2f", c.orb_minutes, o["ll"], o["hh"])
        if self.st.open:
            self.orb_status = "보유 중"
            return
        if self.st.halted:
            self.orb_status = f"종료 ({self.st.halted})"
            return
        if since > c.orb_window_min:
            self.orb_status = "오늘 신규 진입 마감"
            return
        if self.st.trades >= c.orb_max_trades:
            self.orb_status = f"오늘 {c.orb_max_trades}회 모두 사용"
            return
        done = [b for b in self.market.bars(c.bull, 5) if b.ts < minute]
        if not done or (now - done[-1].ts).total_seconds() > 240:
            self.orb_status = "시세 지연"
            return
        close = done[-1].close
        sg = 1 if close > o["hh"] else -1 if close < o["ll"] else 0
        if not sg:
            self.orb_status = "돌파 대기"
            return
        side = c.bull if sg > 0 else c.bear
        if not side:                                 # 하락 쪽 종목이 없으면 상단 돌파만
            self.orb_status = "돌파 대기 (하락 종목 없음)"
            return
        lag = []
        for p, p0 in o["peers"].items():
            if p0:
                chg = (self.market.quote(p).last / p0 - 1) * 100
                if sg * chg <= 0:
                    lag.append(f"{p} {chg:+.2f}%")
        if lag:
            self.orb_status = f"{'상단' if sg > 0 else '하단'} 돌파했지만 동조 안 됨: {', '.join(lag)}"
            return
        last = self.market.quote(side).last
        d = Decision(action="BUY", symbol=side, confidence=1.0, size_pct=100,
                     stop_loss_pct=c.orb_stop_pct, take_profit_pct=c.orb_take_pct,
                     reason=f"개장 {c.orb_minutes}분 범위(${o['ll']:.2f}~${o['hh']:.2f}) "
                            f"{'상단' if sg > 0 else '하단'} 돌파, 종가 ${close:.2f}, 동조 종목 같은 방향")
        self.recent_decisions.append({"time": now.strftime("%H:%M"), "action": "BUY", "symbol": side,
                                      "reason": d.reason})
        self._enter(d, last, trail=c.orb_trail_pct)
        if self.st.open:
            self.orb_status = "보유 중"
            self._ai_review(now)

    def _ai_review(self, now: datetime) -> None:
        """규칙이 방금 들어간 진입을 Claude 가 검토한다. 주문에는 반영하지 않고 기록만 한다
        (Claude 의 판단이 실제로 도움이 되는지 쌓인 기록으로 확인한 뒤에 반영하기 위해)."""
        try:
            snap = self.snapshot(now)
            snap["trigger"] = "orb_entry_review"
            d = self.brain.decide(snap)
        except Exception as e:
            log.warning("AI 검토 실패: %s", e)
            return
        agree = d.action != "SELL"
        log.info("AI 검토: %s — %s", "동의" if agree else "반대", d.reason)
        self._journal("decision", **{**d.model_dump(), "action": "AGREE" if agree else "DISAGREE", "review": True})

    # ── 루프 ────────────────────────────────────────────────
    def tick(self) -> None:
        now = self.clock()
        if self.st.roll(market_hours.session_key(now)):
            log.info("새 거래일 %s 시작 — 목표 %s / 손실한도 %s", self.st.date,
                     self._krw(self.cfg.target_usd), self._krw(-self.cfg.max_loss_usd))
            self.recent_decisions.clear()
            self.st.save(self.state_path)

        watch = self.cfg.bull
        last = None
        if t := self.st.open:                        # 1) 보유 포지션 보호가 항상 먼저
            watch = t.symbol
            last = self._last_price = self.market.quote(t.symbol).last
            if last > t.peak_price:
                t.peak_price = last
                self.st.save(self.state_path)
            if why := self.risk.exit_reason(self.st, now, last):
                if self._close(why, last) and not self.st.halted:
                    self.last_decision_at = None     # 코드가 청산했으면 바로 다음 틱에 AI 에게 다음 수를 묻는다
                    self.trigger = "after_exit"
                return
        if self.st.halted in ("주문 테스트 실패", "주문 테스트 3회 실패"):   # 예전 버전이 남긴 중단 → 재시도 허용
            self.st.halted, self.st.test_last_ts = "", ""
        if (self.st.halted == "계좌 요건 미충족으로 주문 거절"
                and self.st.test_symbol != (self.cfg.order_test_symbol or self.cfg.bull)):
            self.st.halted, self.st.test_last_ts = "", ""       # 테스트 종목이 바뀌었으면 다시 확인
        if self.st.halted and not self.st.open:
            return
        if not self.preflight(now):
            return
        if self._strategy(now) == "orb":
            self._orb_tick(now)
            return
        since = None if self.last_decision_at is None else (now - self.last_decision_at).total_seconds()
        due = since is None or since >= self.cfg.decision_interval_sec
        if not due and since >= 45 and (ref := self.ref_prices.get(watch)):
            if last is None:
                last = self.market.quote(watch).last
            if abs(last / ref - 1) * 100 >= self.cfg.surge_pct:
                due, self.trigger = True, "price_move"
        if due:                                      # 2) 주기가 됐거나 가격이 급변했으면 AI에게 묻기
            self.last_decision_at = now
            try:
                self._ask_ai(now)
            finally:
                self.trigger = "scheduled"

    def run(self, max_minutes: float = 0, exit_when_closed: bool = False) -> str:
        """exit_when_closed: 장이 끝났거나 개장이 2시간 넘게 남았으면 "closed"를 반환하고 끝낸다.
        max_minutes: 실행 시간이 이만큼 지나면 "handoff"를 반환한다(다음 실행이 이어받음).
        둘 다 GitHub Actions처럼 실행 시간이 제한된 환경을 위한 것."""
        self.reconcile()
        started = time.monotonic()
        was_open = None
        errors = 0
        while True:
            now = self.clock()
            if max_minutes and (time.monotonic() - started) / 60 >= max_minutes:
                return "handoff"
            if not is_open(now):
                if exit_when_closed and (now.weekday() >= 5 or now.time() >= CLOSE
                                         or minutes_since_open(now) < -120):
                    log.info("장 종료(또는 개장까지 2시간 이상) — 실행 종료")
                    return "closed"
                if was_open is not False:
                    nxt = market_hours.next_open(now)
                    log.info("장 시간이 아님 (ET %s). 다음 개장: 한국시간 %s", now.strftime("%a %H:%M"),
                             nxt.astimezone(market_hours.KST).strftime("%m-%d %H:%M") if nxt else "?")
                    was_open = False
                self._beat(now, "closed")
                self.sleep(30)
                continue
            if was_open is not True:
                log.info("장 진행 중 (%s 세션) — 매매 루프 시작", market_hours.current(now).name)
                was_open = True
            try:
                self.tick()
                errors = 0
                self._beat(now, "halted" if self.st.halted and not self.st.open else "running")
            except Exception:                        # 시세/주문 오류로 루프가 죽으면 포지션이 방치된다
                errors += 1
                log.exception("틱 처리 오류 (%d회 연속)", errors)
                if errors in (1, 30) or errors % 180 == 0:      # 결과 페이지에서 원인을 볼 수 있게 가끔 기록
                    import traceback
                    self._journal("error", detail=traceback.format_exc(limit=1).strip().splitlines()[-1][:300])
                self._beat(now, "error")
                if errors >= 30:
                    log.critical("오류가 계속됨 — 계좌를 직접 확인하세요. 보유: %s", self.st.open)
            self.sleep(self.cfg.tick_sec)
