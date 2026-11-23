"""시간외(프리·애프터) 직접 매매 도우미. 주문은 하지 않는다.

- 박스: 직전 60분의 고가·저가.
- 위치: 박스 위로 돌파 / 상단 구간(위 25%) / 가운데 / 하단 구간(아래 25%) / 아래로 이탈.
- 확률: 과거 약 60일(야후 5분봉, 시간외 포함)에서 같은 시간대에 SOXL 이 같은 위치에 들어왔을 때,
  +X% 와 -X% 중 어느 쪽에 먼저 닿았는지 센다 (최대 2시간, 그 시간대가 끝나면 거기까지).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("extbox")
ET = ZoneInfo("America/New_York")
BOX_MIN = 60
ZONE = 0.25
HORIZON_MIN = 120
SLIP_PCT = 0.1                       # 시간외 호가 차이 (편도 가정)
X_CHOICES = (1.0, 1.5, 2.0)
SESS = {"pre": (dtime(4, 0), dtime(9, 30)), "post": (dtime(16, 0), dtime(20, 0))}
SLABEL = {"pre": "프리마켓", "post": "애프터마켓"}
ZONES = ("above", "top", "mid", "bottom", "below")
ZLABEL = {"above": "박스 위로 돌파", "top": "박스 상단 구간", "mid": "박스 가운데",
          "bottom": "박스 하단 구간", "below": "박스 아래로 이탈"}
ZSHORT = {"above": "위로 돌파", "top": "상단 구간", "mid": "가운데", "bottom": "하단 구간", "below": "아래로 이탈"}


def session(now: datetime):
    """지금이 프리·애프터면 (이름, 시작, 끝), 아니면 None. 미국 휴장일은 모른다."""
    t = now.astimezone(ET)
    if t.weekday() >= 5:
        return None
    for name, (a, b) in SESS.items():
        o, c = datetime.combine(t.date(), a, ET), datetime.combine(t.date(), b, ET)
        if o <= t < c:
            return name, o, c
    return None


def next_session(now: datetime):
    t = now.astimezone(ET)
    for d in range(0, 6):
        day = t.date() + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for name in ("pre", "post"):
            o = datetime.combine(day, SESS[name][0], ET)
            if o > t:
                return name, o
    return None


def zone(p: float, hi: float, lo: float) -> str:
    w = hi - lo
    if p > hi:
        return "above"
    if p < lo:
        return "below"
    if p >= hi - ZONE * w:
        return "top"
    if p <= lo + ZONE * w:
        return "bottom"
    return "mid"


def live_box(bars: list[list], minutes: int = BOX_MIN):
    """1분봉 [[ms,o,h,l,c,v]] 에서 마지막 봉(지금 가격) 직전 minutes 분의 (고가, 저가). 자료가 모자라면 None.
    과거 통계와 같게, 지금 봉은 박스에 넣지 않는다 (넣으면 돌파를 알 수 없다)."""
    if len(bars) < 2:
        return None
    cur = bars[-1][0] / 1000
    win = [b for b in bars[:-1] if cur - minutes * 60 <= b[0] / 1000 < cur]
    if len(win) < minutes / 3 or win[0][0] / 1000 > cur - minutes * 0.75 * 60:
        return None
    return max(b[2] for b in win), min(b[3] for b in win)


# ── 과거 자료 (야후 5분봉, 시간외 포함)
def fetch_history(symbol: str, path: str, timeout: float = 20) -> int:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=60d&includePrePost=true"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = [[t, q["open"][i], q["high"][i], q["low"][i], q["close"][i]]
            for i, t in enumerate(res.get("timestamp") or [])
            if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i])]
    if len(rows) < 1000:
        raise ValueError(f"{symbol} 5분봉이 너무 적음: {len(rows)}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    os.replace(tmp, path)
    return len(rows)


def history_refresher(symbol: str, path: str, stop: threading.Event, every: float = 6 * 3600) -> None:
    while not stop.is_set():
        try:
            age = time.time() - os.path.getmtime(path) if os.path.exists(path) else 1e9
            if age > every:
                log.info("시간외 과거 자료 %s: %d개", symbol, fetch_history(symbol, path))
        except Exception as e:
            log.warning("시간외 과거 자료 받기 실패: %s", e)
            stop.wait(600)
            continue
        stop.wait(1800)


def yahoo_1m(symbol: str, timeout: float = 8) -> list:
    """야후 1분봉(시간외 포함, 최근 2일). 증권사 분봉에 시간외가 비어 있을 때만 쓴다."""
    from .models import Bar
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=2d&includePrePost=true"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return [Bar(datetime.fromtimestamp(t, ET), q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0)
            for i, t in enumerate(res.get("timestamp") or [])
            if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i])]


_cache: dict = {}


def _load(path: str):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None, None
    if _cache.get("hist", (None,))[0] != mt:
        with open(path, encoding="utf-8") as f:
            _cache["hist"] = (mt, json.load(f))
        _cache.pop("stats", None)
    return mt, _cache["hist"][1]


def samples(rows: list[list], x: float) -> list[dict]:
    """과거 5분봉에서 '시간외에 SOXL 이 박스의 새 위치에 들어온 순간'마다 +x%/-x% 중 먼저 닿은 쪽."""
    out, last_zone = [], {}
    n = len(rows)
    for i in range(n):
        t = rows[i][0]
        dt = datetime.fromtimestamp(t, ET)
        s = session(dt)
        if not s:
            continue
        name, _, close = s
        end = min(close.timestamp(), t + HORIZON_MIN * 60)
        win = [r for r in rows[max(0, i - BOX_MIN // 5 - 3):i] if t - BOX_MIN * 60 <= r[0] < t]
        if len(win) < BOX_MIN // 5 * 0.75:
            continue
        hi, lo, p = max(r[2] for r in win), min(r[3] for r in win), rows[i][4]
        z = zone(p, hi, lo)
        key = (name, dt.date())
        if last_zone.get(key) == z:
            continue                      # 같은 위치에 머무는 동안은 처음 들어온 순간만 센다
        last_zone[key] = z
        if t + 15 * 60 > end:
            continue
        res, move = "none", 0.0
        for j in range(i + 1, n):
            r = rows[j]
            if r[0] >= end:
                break
            up, dn = r[2] >= p * (1 + x / 100), r[3] <= p * (1 - x / 100)
            if up and dn:
                res = "tie"
                break
            if up or dn:
                res = "up" if up else "dn"
                break
            move = (r[4] / p - 1) * 100
        out.append({"s": name, "z": z, "d": dt.date().isoformat(), "r": res, "m": move})
    return out


def stats(path: str, x: float, fee_pct: float = 0.25) -> dict | None:
    """{세션: {위치: {up, dn, none, old:[up,dn], new:[up,dn], ev_up, ev_dn}}, days, since, until}"""
    mt, rows = _load(path)
    if not rows:
        return None
    ck = (mt, x, fee_pct)
    st = _cache.setdefault("stats", {})
    if ck in st:
        return st[ck]
    sm = samples(rows, x)
    days = sorted({s["d"] for s in sm})
    mid = days[len(days) // 2] if days else ""
    cost = 2 * fee_pct + 2 * SLIP_PCT
    out: dict = {"days": len(days), "since": days[0] if days else "", "until": days[-1] if days else "",
                 "split": mid, "x": x, "cost": cost, "by": {}}
    for s in sm:
        b = out["by"].setdefault(s["s"], {}).setdefault(s["z"], {"up": 0, "dn": 0, "none": 0, "tie": 0,
                                                                  "old": [0, 0], "new": [0, 0], "mv": 0.0})
        b[s["r"]] += 1
        if s["r"] in ("up", "dn"):
            b["old" if s["d"] < mid else "new"][0 if s["r"] == "up" else 1] += 1
        if s["r"] == "none":
            b["mv"] += s["m"]
    for sess in out["by"].values():
        for b in sess.values():
            n = b["up"] + b["dn"] + b["none"] + b["tie"]
            gross_up = (b["up"] * x - b["dn"] * x - b["tie"] * x + b["mv"]) / n   # SOXL 을 샀다면 (비용 전)
            gross_dn = (b["dn"] * x - b["up"] * x - b["tie"] * x - b["mv"]) / n   # SOXS 를 샀다면 (SOXL 반대로 근사)
            b["n"] = n
            b["ev_up"], b["ev_dn"] = gross_up - cost, gross_dn - cost
    st[ck] = out
    return out


def verdict(b: dict | None, x: float = 1.0) -> tuple[str, str]:
    """('up'|'dn'|'', 설명). 사례가 적거나 앞·뒤 기간이 엇갈리면 방향을 고르지 않는다."""
    if not b:
        return "", "과거 자료 없음"
    res = b["up"] + b["dn"]
    if res < 30:
        return "", f"과거에 ±{x:g}% 에 닿은 사례가 {res}번뿐이라 판단하기 어렵습니다"
    p = b["up"] / res * 100
    if abs(p - 50) < 5:
        return "", "위·아래로 먼저 간 경우가 비슷합니다"
    want = "up" if p > 50 else "dn"
    k = 0 if want == "up" else 1
    halves = [h for h in (b["old"], b["new"])]
    if min(sum(h) for h in halves) < 12:
        return "", "한쪽이 많았지만 앞·뒤 기간 중 한 곳의 사례가 적어 확인이 안 됩니다"
    if not all(h[k] / sum(h) > 0.5 for h in halves):
        return "", "한쪽이 많았지만 앞·뒤 기간의 방향이 엇갈립니다"
    return want, ("위로" if want == "up" else "아래로") + " 먼저 간 경우가 더 많았고, 앞·뒤 기간 모두 같은 방향이었습니다"


def advice(bull_bars: list[list], bear_last: float | None, now: datetime, path: str, x: float,
           fee_pct: float = 0.25) -> dict:
    """화면에 보여줄 판단. 박스·위치·확률·주문 참고 가격."""
    s = session(now)
    nxt = next_session(now)
    st = stats(path, x, fee_pct)
    out: dict = {"x": x, "session": s[0] if s else None, "close": s[2] if s else None,
                 "next": nxt, "stats": st}
    if not bull_bars:
        return out
    last = bull_bars[-1][4]
    out["last"] = last
    out["bear_last"] = bear_last
    out["age_min"] = (now.timestamp() - bull_bars[-1][0] / 1000) / 60
    bx = live_box(bull_bars)
    if not bx:
        return out
    hi, lo = bx
    z = zone(last, hi, lo)
    out.update(hi=hi, lo=lo, zone=z, width=(hi - lo) / last * 100)
    if not s or out["age_min"] > 5:
        return out
    b = ((st or {}).get("by") or {}).get(s[0], {}).get(z)
    side, why = verdict(b, x)
    out.update(b=b, side=side, why=why)
    k = x / 100
    out["plan"] = {"bull": (last, last * (1 + k), last * (1 - k))}
    if bear_last:
        out["plan"]["bear"] = (bear_last, bear_last * (1 + k), bear_last * (1 - k))
    return out
