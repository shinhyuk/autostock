"""미국 정규장(09:30~16:00 ET) 시간 계산. 휴장일/조기폐장은 모르므로
엔진이 '최근 봉이 오래됨' 검사로 별도 방어한다."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)


def now_et() -> datetime:
    return datetime.now(ET)


def is_open(now: datetime) -> bool:
    return now.weekday() < 5 and OPEN <= now.time() < CLOSE


def minutes_since_open(now: datetime) -> float:
    return (now - now.replace(hour=9, minute=30, second=0, microsecond=0)).total_seconds() / 60


def minutes_to_close(now: datetime) -> float:
    return (now.replace(hour=16, minute=0, second=0, microsecond=0) - now).total_seconds() / 60
