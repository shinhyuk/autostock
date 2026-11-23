"""1분봉으로 계산하는 간단한 지표."""
from __future__ import annotations

from .models import Bar


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = losses = 0.0
    for a, b in zip(values[:period], values[1:period + 1]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / period, losses / period
    for a, b in zip(values[period:], values[period + 1:]):
        d = b - a
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + max(-d, 0)) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def vwap(bars: list[Bar], since=None) -> float | None:
    """세션 시작(since) 이후 봉으로 계산한 VWAP. since 가 없으면 마지막 봉 날짜의 09:30 이후."""
    if not bars:
        return None
    if since is None:
        since = bars[-1].ts.replace(hour=9, minute=30, second=0, microsecond=0)
    pv = vol = 0.0
    for b in bars:
        if b.ts >= since:
            pv += (b.high + b.low + b.close) / 3 * b.volume
            vol += b.volume
    return pv / vol if vol else None


def atr_pct(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1:], bars[-period:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / period / bars[-1].close * 100


def ret_pct(closes: list[float], minutes: int) -> float | None:
    if len(closes) <= minutes:
        return None
    return (closes[-1] / closes[-1 - minutes] - 1) * 100


def summarize(bars: list[Bar], since=None) -> dict:
    closes = [b.close for b in bars]
    r = lambda x: None if x is None else round(x, 3)  # noqa: E731
    return {
        "ema9": r(ema(closes, 9)),
        "ema20": r(ema(closes, 20)),
        "rsi14": r(rsi(closes, 14)),
        "vwap": r(vwap(bars, since)),
        "atr14_pct": r(atr_pct(bars)),
        "ret_5m_pct": r(ret_pct(closes, 5)),
        "ret_15m_pct": r(ret_pct(closes, 15)),
        "ret_60m_pct": r(ret_pct(closes, 60)),
    }
