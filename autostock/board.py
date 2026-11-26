"""차트 탭 데이터: 봉(1분~일봉), 지지·저항선, 고정 박스, 추천 구간, 지지·저항 근처에서의 과거 반등 확률, 호가창.

봉은 야후(시간외 포함)에서 받아 잠깐 캐시한다. 계산은 모두 그 차트의 봉만으로 한다(미래 정보 없음).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from statistics import mean

from . import extbox

log = logging.getLogger("board")
TF = {"1m": ("1m", "5d", 1), "5m": ("5m", "1mo", 5), "15m": ("15m", "1mo", 15), "1h": ("60m", "6mo", 60),
      "1d": ("1d", "2y", 1440)}
TFLABEL = {"1m": "1분", "5m": "5분", "15m": "15분", "1h": "1시간", "1d": "일봉"}
SYMBOLS = ("SOXL", "SOXS", "NVDA", "SOXX")
_cache: dict = {}
_lock = threading.Lock()


def bars(sym: str, tf: str, ttl: float = 20) -> list[list]:
    """[[ms, o, h, l, c, v], ...] 시간순. 같은 요청은 ttl 초 동안 재사용."""
    iv, rng, _ = TF[tf]
    key = (sym, tf)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    pp = "false" if tf == "1d" else "true"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={iv}&range={rng}&includePrePost={pp}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = [[t * 1000, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0]
           for i, t in enumerate(res.get("timestamp") or [])
           if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i])]
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def atr(b: list[list], n: int = 14) -> float:
    tr = [max(x[2] - x[3], abs(x[2] - p[4]), abs(x[3] - p[4])) for p, x in zip(b[-n - 1:], b[-n:])]
    return mean(tr) if tr else 0.0


def pivots(b: list[list], k: int = 3) -> list[tuple[int, str, float]]:
    """좌우 k 봉보다 높은 고점(res)·낮은 저점(sup). (확정되는 봉 번호, 종류, 가격) — 확정은 k 봉 뒤."""
    out = []
    for i in range(k, len(b) - k):
        hi, lo = b[i][2], b[i][3]
        if all(hi >= b[j][2] for j in range(i - k, i + k + 1)):
            out.append((i + k, "res", hi))
        if all(lo <= b[j][3] for j in range(i - k, i + k + 1)):
            out.append((i + k, "sup", lo))
    return out


def levels(b: list[list], upto: int | None = None, k: int = 3, tol: float | None = None, look: int = 400) -> list[dict]:
    """upto 봉까지(최근 look 봉 안에서) 확정된 고점·저점을 가까운 것끼리 묶어 선으로. 많이 닿을수록 강함."""
    upto = len(b) if upto is None else upto
    lo = max(0, upto - look)
    seg = b[lo:upto]
    tol = tol if tol is not None else atr(seg) * 0.5
    pts = sorted(p for _, _, p in pivots(seg, k))
    groups: list[list[float]] = []
    for p in pts:
        if groups and p - groups[-1][0] <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [{"v": mean(g), "n": len(g)} for g in groups]


def nearest(lv: list[dict], price: float, min_n: int = 2):
    """현재가 아래 가장 가까운 지지선, 위 가장 가까운 저항선 (2번 이상 닿은 선)."""
    strong = [x for x in lv if x["n"] >= min_n]
    below = [x for x in strong if x["v"] < price]
    above = [x for x in strong if x["v"] > price]
    return (max(below, key=lambda x: x["v"]) if below else None,
            min(above, key=lambda x: x["v"]) if above else None)


def bounce_stats(b: list[list], k: int = 3, step: int = 20) -> dict:
    """과거에 그때까지 알려진 지지선(저항선) 근처(0.3 ATR 안)에 왔을 때, 위로(아래로) 1 ATR 먼저 갔는지.
    계산을 가볍게 하려고 step 봉마다 선을 다시 계산한다."""
    res = {"sup": [0, 0], "res": [0, 0]}
    if len(b) < 80:
        return res
    lv, last_i, a = [], -1, 0.0
    seen = set()
    for i in range(60, len(b) - 1):
        if i - last_i >= step:
            lv, last_i, a = levels(b, i, k), i, atr(b[:i])
        if not a:
            continue
        p = b[i][4]
        s, r = nearest(lv, p)
        for kind, x in (("sup", s), ("res", r)):
            if not x or abs(p - x["v"]) > 0.3 * a or (kind, round(x["v"], 2)) in seen:
                continue
            seen.add((kind, round(x["v"], 2)))
            up, dn = p + a, p - a
            for y in b[i + 1:i + 200]:
                if y[2] >= up and y[3] <= dn:
                    break
                if y[2] >= up:
                    res[kind][0 if kind == "sup" else 1] += 1
                    break
                if y[3] <= dn:
                    res[kind][1 if kind == "sup" else 0] += 1
                    break
    return res   # sup: [반등, 이탈], res: [되밀림, 돌파]


def _near(lv: list[dict], price: float, k: int = 3) -> list[dict]:
    """차트가 어지럽지 않게 현재가 위·아래로 가까운 선 k 개씩만 (2번 이상 닿은 선)."""
    strong = [x for x in lv if x["n"] >= 2]
    below = sorted((x for x in strong if x["v"] < price), key=lambda x: -x["v"])[:k]
    above = sorted((x for x in strong if x["v"] >= price), key=lambda x: x["v"])[:k]
    return below + above


def analyze(sym: str, tf: str) -> dict:
    b = bars(sym, tf)
    if len(b) < 30:
        return {"sym": sym, "tf": tf, "bars": b, "error": "봉이 부족합니다"}
    step = TF[tf][2]
    last = b[-1][4]
    a = atr(b)
    lv = levels(b)
    sup, res = nearest(lv, last)
    rows = [[x[0] / 1000, *x[1:5]] for x in b[-400:]]
    bx = extbox.find_boxes(rows, step, nmin=9, nmax=36, wmax=40, gap=max(3600, step * 60 * 3))[1]["box"] \
        if step < 1440 else extbox.find_boxes(rows, 1, nmin=9, nmax=36, wmax=60, gap=10 ** 9)[1]["box"]
    st = bounce_stats(b)
    zones = []
    if sup:
        tgt = res["v"] if res else last + 2 * a
        stop = sup["v"] - 0.5 * a
        zones.append({"k": "buy", "lo": sup["v"], "hi": sup["v"] + 0.3 * a, "stop": stop, "target": tgt,
                      "rr": (tgt - sup["v"]) / max(sup["v"] - stop, 1e-9)})
    if res:
        tgt = sup["v"] if sup else last - 2 * a
        stop = res["v"] + 0.5 * a
        zones.append({"k": "sell", "lo": res["v"] - 0.3 * a, "hi": res["v"], "stop": stop, "target": tgt,
                      "rr": (res["v"] - tgt) / max(stop - res["v"], 1e-9)})
    return {"sym": sym, "tf": tf, "bars": b, "last": last, "atr": a,
            "levels": _near(lv, last), "sup": sup, "res": res,
            "box": {"hi": bx["hi"], "lo": bx["lo"], "start": bx["start"] * 1000} if bx else None,
            "zones": zones, "stats": st}
