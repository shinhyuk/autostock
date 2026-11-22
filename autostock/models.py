from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


@dataclass
class Bar:
    ts: datetime          # 미국 동부시간(ET)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Quote:
    symbol: str
    last: float
    prev_close: float


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float


@dataclass
class Fill:
    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    price: float


class Decision(BaseModel):
    """Claude가 돌려주는 매매 판단."""

    action: Literal["BUY", "SELL", "HOLD"] = Field(
        description="BUY=symbol 신규 진입, SELL=현재 포지션 전량 청산, HOLD=아무것도 안 함")
    symbol: str = Field(description="BUY일 때 매수할 종목. 그 외에는 빈 문자열")
    confidence: float = Field(description="0~1 사이 확신도")
    size_pct: float = Field(description="BUY일 때 운용자금 대비 투입 비중(%) 10~100")
    stop_loss_pct: float = Field(description="진입가 대비 손절폭(%) 양수")
    take_profit_pct: float = Field(description="진입가 대비 익절폭(%) 양수")
    reason: str = Field(description="판단 근거 한두 문장 (한국어)")


HOLD = Decision(action="HOLD", symbol="", confidence=0, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0, reason="")


class MarketData(Protocol):
    def quote(self, symbol: str) -> Quote: ...
    def bars(self, symbol: str, n: int = 120) -> list[Bar]: ...


class Broker(Protocol):
    def position(self, symbol: str) -> Position | None: ...
    def buy(self, symbol: str, qty: int, ref_price: float) -> Fill | None: ...
    def sell(self, symbol: str, qty: int, ref_price: float) -> Fill | None: ...
