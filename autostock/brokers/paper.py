"""가상 체결 브로커와 시뮬레이션용 가짜 시세."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from ..market_hours import ET
from ..models import Bar, Fill, Position, Quote


class PaperBroker:
    """주문을 내보내지 않고 기준가 ± 슬리피지로 즉시 체결된 것으로 처리한다."""

    def __init__(self, slippage_pct: float = 0.05):
        self.slip = slippage_pct / 100
        self.positions: dict[str, Position] = {}

    def position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def restore(self, symbol: str, qty: int, avg_price: float) -> None:
        self.positions[symbol] = Position(symbol, qty, avg_price)

    def buy(self, symbol: str, qty: int, ref_price: float) -> Fill | None:
        price = round(ref_price * (1 + self.slip), 4)
        p = self.positions.get(symbol)
        if p:
            p.avg_price = (p.avg_price * p.qty + price * qty) / (p.qty + qty)
            p.qty += qty
        else:
            self.positions[symbol] = Position(symbol, qty, price)
        return Fill(symbol, "buy", qty, price)

    def sell(self, symbol: str, qty: int, ref_price: float) -> Fill | None:
        p = self.positions.get(symbol)
        if not p:
            return None
        qty = min(qty, p.qty)
        p.qty -= qty
        if p.qty == 0:
            del self.positions[symbol]
        return Fill(symbol, "sell", qty, round(ref_price * (1 - self.slip), 4))


class FakeMarket:
    """--simulate 용 랜덤워크 시세. bull/bear는 서로 반대로 움직인다.
    step()을 부를 때마다 가상 시계가 1분 전진한다."""

    def __init__(self, bull: str, bear: str, seed: int | None = None, vol_pct: float = 0.35):
        self.bull, self.bear = bull, bear
        self.rng = random.Random(seed)
        self.vol = vol_pct / 100
        self.now = datetime(2026, 1, 5, 9, 30, tzinfo=ET)   # 월요일 개장
        self.prev = {bull: 30.0, bear: 15.0}
        self._bars: dict[str, list[Bar]] = {bull: [], bear: []}
        self.px = dict(self.prev)
        self.drift = 0.0
        for _ in range(30):
            self.step()

    def step(self) -> None:
        self.drift = 0.9 * self.drift + self.rng.gauss(0, self.vol * 0.3)
        r = self.drift + self.rng.gauss(0, self.vol)
        for sym, sign in ((self.bull, 1), (self.bear, -1)):
            o = self.px[sym]
            c = o * (1 + sign * r)
            hi, lo = max(o, c) * (1 + abs(self.rng.gauss(0, self.vol / 3))), min(o, c) * (1 - abs(self.rng.gauss(0, self.vol / 3)))
            self._bars[sym].append(Bar(self.now, o, hi, lo, c, self.rng.randint(50_000, 500_000)))
            self.px[sym] = c
        self.now += timedelta(minutes=1)

    def quote(self, symbol: str) -> Quote:
        return Quote(symbol, round(self.px[symbol], 4), self.prev[symbol])

    def bars(self, symbol: str, n: int = 120) -> list[Bar]:
        return self._bars[symbol][-n:]
