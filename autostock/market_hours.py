"""거래 세션 시간 계산.

- regular: 미국 정규장 09:30~16:00 ET (평일)
- pre    : 미국 프리마켓 04:00~09:25 ET (한국시간 겨울 18:00~23:25). 정규장 직전에 끝낸다.
- day    : 한국 낮의 미국주식 주간거래. 한국시간 평일 10:00 시작, 미국 동부 03:15 에 끝난 것으로 본다
           (실제 마감은 04:00 ET 이지만 증권사 마감이 더 이를 수 있어 여유를 둠. 겨울 17:15, 여름 16:15 KST).

휴장일/조기폐장은 모르므로 엔진이 '최근 봉이 오래됨' 검사로 별도 방어한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
OPEN, CLOSE = time(9, 30), time(16, 0)
ENABLED: tuple[str, ...] = ("regular",)      # 설정(SESSIONS)에 따라 실행 시작 시 바뀐다


@dataclass(frozen=True)
class Session:
    name: str            # regular | pre | day
    open: datetime
    close: datetime

    @property
    def key(self) -> str:
        """일일 손익·한도를 묶는 단위. 주간거래는 한국 날짜 기준으로 따로 센다."""
        if self.name == "day":
            return self.open.astimezone(KST).strftime("%Y-%m-%d") + "D"
        return self.open.strftime("%Y-%m-%d") + ("P" if self.name == "pre" else "")


def now_et() -> datetime:
    return datetime.now(ET)


def _sessions(now: datetime):
    base = now.astimezone(ET).date()
    for off in range(-1, 5):
        d = base + timedelta(days=off)
        if d.weekday() >= 5:
            continue
        if "regular" in ENABLED:
            yield Session("regular", datetime.combine(d, OPEN, ET), datetime.combine(d, CLOSE, ET))
        if "pre" in ENABLED:
            yield Session("pre", datetime.combine(d, time(4, 0), ET), datetime.combine(d, time(9, 25), ET))
        if "day" in ENABLED:
            yield Session("day", datetime.combine(d, time(10, 0), KST).astimezone(ET),
                          datetime.combine(d, time(3, 15), ET))


def current(now: datetime) -> Session | None:
    return next((s for s in _sessions(now) if s.open <= now < s.close), None)


def next_open(now: datetime) -> datetime | None:
    return min((s.open for s in _sessions(now) if s.open > now), default=None)


def last_session(now: datetime) -> Session | None:
    """지금 진행 중이거나 가장 최근에 열렸던 세션."""
    past = [s for s in _sessions(now - timedelta(days=4)) if s.open <= now] + \
           [s for s in _sessions(now) if s.open <= now]
    return max(past, key=lambda s: s.open, default=None)


def is_open(now: datetime) -> bool:
    return current(now) is not None


def session_key(now: datetime) -> str:
    s = current(now)
    return s.key if s else now.strftime("%Y-%m-%d")


def minutes_since_open(now: datetime) -> float:
    s = current(now)
    start = s.open if s else now.replace(hour=9, minute=30, second=0, microsecond=0)
    return (now - start).total_seconds() / 60


def minutes_to_close(now: datetime) -> float:
    s = current(now)
    end = s.close if s else now.replace(hour=16, minute=0, second=0, microsecond=0)
    return (end - now).total_seconds() / 60
