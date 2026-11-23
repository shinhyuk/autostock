"""노이즈 영역 돌파 (Zarattini·Aziz·Barbon 2024) 계산용 기록.

하루마다 정규장 시가, 개장 후 30분 간격 시점의 가격, 종가를 남겨 두고,
'지난 14일 같은 시점에 시가에서 평균 얼마나 움직였나'(시그마)를 계산한다.
처음에는 기록이 없으므로 야후 5분봉으로 채워 시작하고, 이후로는 봇이 직접 기록한다.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime

from .market_hours import ET

log = logging.getLogger("noise")


class NoiseBook:
    def __init__(self, path: str):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.days: dict[str, dict] = json.load(f)
        except (FileNotFoundError, ValueError):
            self.days = {}

    def save(self) -> None:
        keep = dict(sorted(self.days.items())[-40:])
        self.days = keep
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(keep, f)
        os.replace(tmp, self.path)

    def record(self, day: str, open_: float | None = None, offset: int | None = None,
               price: float | None = None, close: float | None = None) -> None:
        d = self.days.setdefault(day, {"open": None, "close": None, "m": {}})
        if open_ and not d["open"]:
            d["open"] = open_
        if offset is not None and price:
            d["m"][str(offset)] = price
        if close:
            d["close"] = close

    def _past(self, day: str) -> list[dict]:
        return [v for k, v in sorted(self.days.items()) if k < day and v.get("open")]

    def count(self, day: str, offset: int) -> int:
        return sum(1 for v in self._past(day) if str(offset) in v["m"])

    def sigma(self, day: str, offset: int, lookback: int = 14) -> float | None:
        rows = [abs(v["m"][str(offset)] / v["open"] - 1) for v in self._past(day) if str(offset) in v["m"]][-lookback:]
        return sum(rows) / len(rows) if len(rows) >= lookback else None

    def prev_close(self, day: str) -> float | None:
        past = [v for v in self._past(day) if v.get("close")]
        return past[-1]["close"] if past else None

    def bootstrap_yahoo(self, symbol: str, every: int = 30, timeout: float = 10) -> int:
        """야후 5분봉(최근 60일)으로 기록에 없는 날을 채운다. 비공식 API 라 실패할 수 있다. 채운 날 수를 돌려준다."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=60d"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=timeout) as r:
                j = json.load(r)
            res = j["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
        except Exception as e:
            log.warning("야후 5분봉으로 노이즈 기록 채우기 실패: %s", e)
            return 0
        today = datetime.now(ET).strftime("%Y-%m-%d")
        bydate: dict[str, list] = {}
        for i, t in enumerate(res.get("timestamp") or []):
            if q["close"][i] is None or q["open"][i] is None:
                continue
            ts = datetime.fromtimestamp(t, ET)
            if not ((9, 30) <= (ts.hour, ts.minute) < (16, 0)):
                continue
            bydate.setdefault(ts.strftime("%Y-%m-%d"), []).append((ts, q["open"][i], q["close"][i]))
        added = 0
        for day, bars in bydate.items():
            if day >= today or day in self.days or len(bars) < 70:
                continue
            open_ts = bars[0][0].replace(hour=9, minute=30)
            if bars[0][0] != open_ts:
                continue
            self.record(day, open_=bars[0][1], close=bars[-1][2])
            for ts, o, c in bars:                    # 5분봉이 끝나는 시각 = 개장 후 분
                off = int((ts - open_ts).total_seconds() // 60) + 5
                if off % every == 0:
                    self.record(day, offset=off, price=c)
            added += 1
        if added:
            self.save()
            log.info("야후 5분봉으로 노이즈 기록 %d일 채움", added)
        return added
