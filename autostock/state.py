"""하루 단위 매매 상태. 재시작해도 손익/한도가 초기화되지 않도록 파일에 저장한다."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class OpenTrade:
    symbol: str
    qty: int
    entry_price: float
    entry_ts: str            # ISO (ET)
    stop_pct: float
    take_pct: float
    buy_fee: float
    peak_price: float = 0.0  # 진입 후 최고가 (추적 손절 기준)
    trail_pct: float = 0.0   # 최고가 대비 이만큼 밀리면 청산. 0이면 추적 손절 없음


@dataclass
class DayState:
    date: str = ""           # 거래일 (ET, YYYY-MM-DD)
    realized_usd: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    last_loss_ts: str = ""
    last_loss_symbol: str = ""
    test_attempts: int = 0   # 이번 세션의 주문 테스트 시도 횟수
    test_last_ts: str = ""
    test_symbol: str = ""    # 마지막 주문 테스트에 쓴 종목
    halted: str = ""         # 비어있지 않으면 당일 신규 진입 중단 사유
    open: OpenTrade | None = None
    history: list[dict] = field(default_factory=list)   # 당일 청산 내역

    @classmethod
    def load(cls, path: str) -> "DayState":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        o = d.pop("open", None)
        return cls(**d, open=OpenTrade(**o) if o else None)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def roll(self, date: str) -> bool:
        """거래일이 바뀌면 일일 카운터를 초기화(보유 포지션 정보는 유지)."""
        if self.date == date:
            return False
        keep = self.open
        self.__init__(date=date, open=keep)  # type: ignore[misc]
        return True
