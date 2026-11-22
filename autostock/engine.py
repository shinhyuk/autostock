"""메인 루프: 빠른 주기로 손절/익절을 감시하고, 느린 주기로 AI에게 판단을 묻는다."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Callable

from . import indicators
from .config import Settings
from .market_hours import is_open, minutes_since_open, minutes_to_close, now_et
from .models import Broker, Decision, MarketData
from .risk import Risk
from .state import DayState, OpenTrade

log = logging.getLogger("engine")


class Engine:
    def __init__(self, cfg: Settings, market: MarketData, broker: Broker, brain,
                 clock: Callable[[], datetime] = now_et, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.market, self.broker, self.brain = cfg, market, broker, brain
        self.clock, self.sleep = clock, sleep
        self.risk = Risk(cfg)
        self.state_path = os.path.join(cfg.data_dir, f"state_{cfg.mode}.json")
        self.log_path = os.path.join(cfg.data_dir, f"journal_{cfg.mode}.jsonl")
        self.st = DayState.load(self.state_path)
        self.last_decision_at: datetime | None = None
        self.recent_decisions: list[dict] = []

    # ── 기록 ────────────────────────────────────────────────
    def _journal(self, kind: str, **data) -> None:
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.clock().isoformat(), "kind": kind, **data},
                               ensure_ascii=False) + "\n")

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

    # ── 주문 ────────────────────────────────────────────────
    def _enter(self, d: Decision, last: float) -> None:
        qty = self.risk.size(self.st, d, last)
        if qty < 1:
            self._reject(d, "수량 0 (자금 또는 손실 여유 부족)")
            return
        fill = self.broker.buy(d.symbol, qty, last)
        if not fill:
            self._reject(d, "매수 미체결")
            return
        stop, take = self.risk.stops(d)
        self.st.open = OpenTrade(d.symbol, fill.qty, fill.price, self.clock().isoformat(),
                                 stop, take, self.risk.fee(fill.price, fill.qty))
        self.st.save(self.state_path)
        log.info("▶ 매수 %s %d주 @ $%.2f  (손절 -%.1f%% / 익절 +%.1f%%)  %s",
                 d.symbol, fill.qty, fill.price, stop, take, d.reason)
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
                st.last_loss_ts = self.clock().isoformat()
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
        market = {}
        for s in c.symbols:
            q, bars = self.market.quote(s), self.market.bars(s, 120)
            today = [b for b in bars if b.ts.date() == bars[-1].ts.date()] if bars else []
            market[s] = {
                "last": q.last,
                "day_change_pct": round((q.last / q.prev_close - 1) * 100, 2) if q.prev_close else None,
                "day_high": max((b.high for b in today), default=None),
                "day_low": min((b.low for b in today), default=None),
                **indicators.summarize(bars),
                "last_bar_age_min": round((now - bars[-1].ts).total_seconds() / 60, 1) if bars else None,
            }
            if s == c.bull:   # 봉 데이터는 한 종목만(반대 종목은 거의 거울상)
                market[s]["bars_1m"] = {
                    "columns": "HH:MM,open,high,low,close,volume",
                    "rows": [f"{b.ts:%H:%M},{b.open:.2f},{b.high:.2f},{b.low:.2f},{b.close:.2f},{b.volume:.0f}"
                             for b in bars[-40:]]}
        pos = None
        if t := st.open:
            last = market[t.symbol]["last"]
            pos = {"symbol": t.symbol, "qty": t.qty, "entry_price": t.entry_price,
                   "change_pct": round((last / t.entry_price - 1) * 100, 2),
                   "unrealized_usd": round(self.risk.unrealized(t, last), 2),
                   "held_min": round((now - datetime.fromisoformat(t.entry_ts)).total_seconds() / 60),
                   "stop_loss_pct": t.stop_pct, "take_profit_pct": t.take_pct}
        return {
            "time_et": now.strftime("%Y-%m-%d %H:%M"),
            "minutes_since_open": round(minutes_since_open(now)),
            "minutes_to_close": round(minutes_to_close(now)),
            "market": market,
            "account": {
                "capital_usd": round(c.capital_usd, 2),
                "day_realized_usd": round(st.realized_usd, 2),
                "day_target_usd": round(c.target_usd, 2),
                "day_max_loss_usd": round(c.max_loss_usd, 2),
                "trades_today": st.trades, "max_trades": c.max_trades_per_day,
                "wins": st.wins, "losses": st.losses,
                "round_trip_fee_pct": c.fee_pct * 2,
                "max_stop_loss_pct": c.max_stop_loss_pct,
                "position": pos,
            },
            "closed_trades_today": st.history[-6:],
            "recent_decisions": self.recent_decisions[-6:],
        }

    def _ask_ai(self, now: datetime) -> None:
        snap = self.snapshot(now)
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
        if any(a is None or a > 3 for a in ages):
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
        self._enter(d, last)

    # ── 루프 ────────────────────────────────────────────────
    def tick(self) -> None:
        now = self.clock()
        if self.st.roll(now.strftime("%Y-%m-%d")):
            log.info("새 거래일 %s 시작 — 목표 %s / 손실한도 %s", self.st.date,
                     self._krw(self.cfg.target_usd), self._krw(-self.cfg.max_loss_usd))
            self.recent_decisions.clear()
            self.st.save(self.state_path)

        if t := self.st.open:                        # 1) 보유 포지션 보호가 항상 먼저
            last = self.market.quote(t.symbol).last
            if why := self.risk.exit_reason(self.st, now, last):
                self._close(why, last)
                return
        if self.st.halted and not self.st.open:
            return
        due = (self.last_decision_at is None or
               (now - self.last_decision_at).total_seconds() >= self.cfg.decision_interval_sec)
        if due:                                      # 2) 주기가 되면 AI에게 묻기
            self.last_decision_at = now
            self._ask_ai(now)

    def run(self) -> None:
        self.reconcile()
        was_open = None
        errors = 0
        while True:
            now = self.clock()
            if not is_open(now):
                if was_open is not False:
                    log.info("장 시간이 아님 (ET %s). 정규장 09:30~16:00 ET 대기 중…", now.strftime("%a %H:%M"))
                    was_open = False
                self.sleep(30)
                continue
            if was_open is not True:
                log.info("정규장 진행 중 — 매매 루프 시작")
                was_open = True
            try:
                self.tick()
                errors = 0
            except Exception:                        # 시세/주문 오류로 루프가 죽으면 포지션이 방치된다
                errors += 1
                log.exception("틱 처리 오류 (%d회 연속)", errors)
                if errors >= 30:
                    log.critical("오류가 계속됨 — 계좌를 직접 확인하세요. 보유: %s", self.st.open)
            self.sleep(self.cfg.tick_sec)
