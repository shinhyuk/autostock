"""AI 판단과 무관하게 코드가 강제하는 한도. AI는 이 한도 안에서만 움직인다."""
from __future__ import annotations

from datetime import datetime

from .config import Settings
from .market_hours import minutes_since_open, minutes_to_close
from .models import Decision
from .state import DayState, OpenTrade


class Risk:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def fee(self, price: float, qty: int) -> float:
        return price * qty * self.cfg.fee_pct / 100

    def unrealized(self, t: OpenTrade, last: float) -> float:
        """지금 청산한다고 가정한 순손익(USD, 왕복 수수료 차감)."""
        return (last - t.entry_price) * t.qty - t.buy_fee - self.fee(last, t.qty)

    # ── 진입 ────────────────────────────────────────────────
    def entry_block(self, st: DayState, now: datetime, d: Decision) -> str:
        """진입 불가 사유. 빈 문자열이면 진입 가능."""
        c = self.cfg
        if st.halted:
            return f"당일 종료({st.halted})"
        if d.symbol not in c.symbols:
            return f"허용되지 않은 종목 {d.symbol!r}"
        if d.confidence < c.min_confidence:
            return f"확신도 부족 {d.confidence:.2f} < {c.min_confidence}"
        if st.trades >= c.max_trades_per_day:
            return "일일 최대 거래 횟수 도달"
        if minutes_since_open(now) < c.no_entry_after_open_min:
            return "장 시작 직후 진입 금지 구간"
        if minutes_to_close(now) < c.no_entry_before_close_min:
            return "장 마감 전 진입 금지 구간"
        if st.last_loss_ts and d.symbol == st.last_loss_symbol:     # 반대 종목으로 갈아타는 것은 허용
            mins = (now - datetime.fromisoformat(st.last_loss_ts)).total_seconds() / 60
            if mins < c.cooldown_after_loss_min:
                return f"같은 종목 손절 후 쿨다운 {c.cooldown_after_loss_min - mins:.0f}분 남음"
        return ""

    def stops(self, d: Decision) -> tuple[float, float]:
        """AI가 제안한 손절/익절폭을 허용 범위로 자른다."""
        c = self.cfg
        stop = min(max(d.stop_loss_pct or c.max_stop_loss_pct, 0.3), c.max_stop_loss_pct)
        floor = max(0.5, 2 * c.fee_pct + 0.3)                   # 왕복 수수료보다는 크게
        take = min(max(d.take_profit_pct or c.default_take_profit_pct, floor), min(10.0, c.take_profit_max_pct))
        return stop, take

    def trail(self, stop_pct: float, atr_pct: float | None) -> float:
        """추적 손절 폭(%). 최근 1분 변동성에 비례하되 손절폭보다 넓지 않게."""
        c = self.cfg
        return round(min(max((atr_pct or 0) * c.trail_atr_mult, c.trail_min_pct), stop_pct), 2)

    def size(self, st: DayState, d: Decision, price: float) -> int:
        """매수 수량. 운용자금(+당일 실현손익) 범위 안에서, 손절 시 일일 손실한도를 넘지 않게."""
        c = self.cfg
        budget = (c.capital_usd + min(st.realized_usd, 0)) * min(max(d.size_pct, 50), 100) / 100
        qty = int(budget / (price * (1 + c.fee_pct / 100)))
        stop, _ = self.stops(d)
        room = c.max_loss_usd + st.realized_usd          # 남은 손실 여유
        per_share_risk = price * (stop + 2 * c.fee_pct) / 100
        if per_share_risk > 0:
            qty = min(qty, int(room / per_share_risk))
        return max(qty, 0)

    # ── 청산 ────────────────────────────────────────────────
    def exit_reason(self, st: DayState, now: datetime, last: float) -> str:
        """보유 포지션을 지금 강제 청산해야 하는 사유. 빈 문자열이면 유지."""
        t, c = st.open, self.cfg
        if t is None:
            return ""
        chg = (last / t.entry_price - 1) * 100
        total = st.realized_usd + self.unrealized(t, last)
        if total >= c.target_usd:
            return "일일 목표 달성"
        if total <= -c.max_loss_usd:
            return "일일 손실 한도"
        if chg <= -t.stop_pct:
            return f"손절 {chg:.2f}%"
        if chg >= t.take_pct:
            return f"익절 {chg:.2f}%"
        if t.trail_pct and t.peak_price:
            # 최고 수익이 '추적 폭 + 왕복 수수료'를 넘은 뒤부터 작동 → 발동해도 수수료 이상은 남긴다
            peak_gain = (t.peak_price / t.entry_price - 1) * 100
            if peak_gain >= t.trail_pct + 2 * c.fee_pct and last <= t.peak_price * (1 - t.trail_pct / 100):
                return f"추적 손절 (고점 +{peak_gain:.2f}% → 현재 {chg:+.2f}%)"
        if c.max_hold_min:
            try:
                held = (now - datetime.fromisoformat(t.entry_ts)).total_seconds() / 60
            except ValueError:
                held = 0
            if held >= c.max_hold_min and chg < 2 * c.fee_pct + 0.1:
                return f"시간 청산 ({held:.0f}분 보유, {chg:+.2f}%)"
        if minutes_to_close(now) <= c.flatten_before_close_min:
            return "장 마감 전 강제 청산"
        return ""

    def halt_reason(self, st: DayState) -> str:
        c = self.cfg
        if st.realized_usd >= c.target_usd:
            return "일일 목표 달성"
        if st.realized_usd <= -c.max_loss_usd:
            return "일일 손실 한도"
        if st.consecutive_losses >= c.max_consecutive_losses:
            return f"{c.max_consecutive_losses}연속 손실"
        return ""
