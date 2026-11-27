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
    pad = (tol or 0) * 0.3                                # 선이 아니라 가격대(띠)로: 모인 고점·저점의 범위 + 약간 여유
    t = tol or 0
    return [{"v": mean(g), "n": len(g), "lo": max(min(g) - pad, mean(g) - t * 0.4),
             "hi": min(max(g) + pad, mean(g) + t * 0.4)} for g in groups]


def nearest(lv: list[dict], price: float, min_n: int = 2):
    """현재가 아래 가장 가까운 지지선, 위 가장 가까운 저항선 (2번 이상 닿은 선)."""
    strong = [x for x in lv if x["n"] >= min_n]
    below = [x for x in strong if x["v"] < price]
    above = [x for x in strong if x["v"] > price]
    return (max(below, key=lambda x: x["v"]) if below else None,
            min(above, key=lambda x: x["v"]) if above else None)


_bounce_cache: dict = {}


def bounce_stats_cached(key, b: list[list], ttl: float = 300) -> dict:
    """반등률은 천천히 변하므로 5분 동안 재사용 (페이지를 빨리 열기 위해)."""
    hit = _bounce_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = bounce_stats(b)
    _bounce_cache[key] = (time.time(), r)
    return r


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


def merge_recent(b: list[list], extra: list[list], tf: str) -> tuple[list[list], int]:
    """야후 봉 뒤에 증권사 1분봉(extra, 야후에 아직 없는 최근 것)을 그 시간 단위로 묶어 이어 붙인다."""
    if not extra or tf == "1d":
        return b, 0
    step = TF[tf][2] * 60_000
    last = b[-1][0] if b else 0
    agg: dict[int, list] = {}
    for t, o, h, l, c, v in sorted(extra):
        k = t - t % step
        if k <= last:
            continue
        if k not in agg:
            agg[k] = [k, o, h, l, c, v or 0]
        else:
            a = agg[k]
            a[2], a[3], a[4], a[5] = max(a[2], h), min(a[3], l), c, a[5] + (v or 0)
    return b + [agg[k] for k in sorted(agg)], len(agg)


def analyze(sym: str, tf: str, extra: list[list] | None = None) -> dict:
    b = bars(sym, tf)
    b, added = merge_recent(b, extra or [], tf)
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
    st = bounce_stats_cached((sym, tf), b)
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
            "zones": zones, "stats": st, "kis_bars": added,
            "fc": forecast(bars_daily(sym) if tf == "1d" else b, tf)}


def _ma(xs: list[float], n: int) -> float | None:
    return mean(xs[-n:]) if len(xs) >= n else None


def longterm(sym: str) -> dict:
    """장기 관점(5년 일봉): 추세(50·200일 평균), 1년 고점 대비 하락률, 주봉 지지·저항대,
    지금과 비슷한 상태(고점 대비 하락률 구간·200일선 위/아래)였던 날들의 1·3·6개월 뒤 수익률, 레버리지 감가."""
    d = bars_daily(sym)
    if len(d) < 300:
        return {"error": "일봉이 부족합니다"}
    cl = [x[4] for x in d]
    last = cl[-1]
    ma50, ma200 = _ma(cl, 50), _ma(cl, 200)
    hi252 = max(x[2] for x in d[-252:])
    lo252 = min(x[3] for x in d[-252:])
    dd = (last / hi252 - 1) * 100

    def state(i):
        h = max(x[2] for x in d[max(0, i - 251):i + 1])
        ddi = (cl[i] / h - 1) * 100
        m = mean(cl[i - 199:i + 1]) if i >= 199 else None
        return ddi, (cl[i] > m) if m else None
    bucket = lambda v: 0 if v > -20 else 1 if v > -40 else 2 if v > -60 else 3 if v > -80 else 4   # noqa: E731
    now_b, now_above = bucket(dd), last > ma200 if ma200 else None
    fwd = {21: [], 63: [], 126: []}
    hits = []
    for i in range(252, len(d)):
        ddi, ab = state(i)
        if bucket(ddi) != now_b or ab != now_above:
            continue
        hits.append(i)
        for h in fwd:
            if i + h < len(d):
                fwd[h].append((cl[i + h] / cl[i] - 1) * 100)
    stats = {h: {"n": len(v), "med": sorted(v)[len(v) // 2] if v else None,
                 "up": sum(x > 0 for x in v) / len(v) * 100 if v else None,
                 "p10": sorted(v)[len(v) // 10] if len(v) >= 10 else None,
                 "p90": sorted(v)[len(v) * 9 // 10] if len(v) >= 10 else None} for h, v in fwd.items()}
    eps = []                                             # 연속된 날은 한 번의 '사례'로 묶는다 (20거래일 넘게 끊기면 새 사례)
    for i in hits:
        if eps and i - eps[-1][1] <= 20:
            eps[-1][1] = i
        else:
            eps.append([i, i])
    wk = _weekly(d)
    lv = levels(wk, k=2, look=104, tol=atr(wk[-26:]) * 0.5)
    sup, res = nearest(lv, last)
    out = {"sym": sym, "last": last, "ma50": ma50, "ma200": ma200, "hi252": hi252, "lo252": lo252, "dd": dd,
           "bucket": ["고점 근처(-20% 이내)", "-20~-40%", "-40~-60%", "-60~-80%", "-80% 넘게"][now_b],
           "above200": now_above, "fwd": stats, "episodes": [[d[a][0], d[b][0]] for a, b in eps], "wsup": sup, "wres": res, "from": d[0][0], "days": len(d)}
    if sym in ("SOXL", "SOXS"):                         # 레버리지 감가: 1년 동안 SOXL 실제 vs SOXX 의 3배(또는 -3배)
        sx = bars_daily("SOXX")
        if len(sx) >= 253 and len(d) >= 253:
            r_l = (cl[-1] / cl[-253] - 1) * 100
            r_x = (sx[-1][4] / sx[-253][4] - 1) * 100
            out["decay"] = {"etf": r_l, "soxx": r_x, "mult": 3 if sym == "SOXL" else -3}
    return out


def bars_daily(sym: str) -> list[list]:
    iv = TF["1d"]
    TF["1d5y"] = ("1d", "5y", 1440)
    try:
        return bars(sym, "1d5y", ttl=3600)
    finally:
        TF["1d"] = iv


def _weekly(d: list[list]) -> list[list]:
    from datetime import datetime, timezone
    out: dict = {}
    for x in d:
        k = datetime.fromtimestamp(x[0] / 1000, timezone.utc).isocalendar()[:2]
        if k not in out:
            out[k] = list(x)
        else:
            w = out[k]
            w[2], w[3], w[4], w[5] = max(w[2], x[2]), min(w[3], x[3]), x[4], w[5] + (x[5] or 0)
    return [out[k] for k in sorted(out)]


# ── 미래 추정: 가능성 범위(80%·50%)와 가운데 예상선. 세 가지 방식을 과거에 걸어 보며 검증해 가장 정확한 것을 쓴다.
import math
import numpy as np

QS = (0.1, 0.25, 0.5, 0.75, 0.9)
FAR = 10                                # 예상선을 기본 h 봉의 몇 배까지 그릴지 (끌어서 볼 수 있는 최대)
_fc_cache: dict = {}
MODELS = {"flat": "방향 없음(범위만)", "mom": "최근 흐름이 이어짐", "rev": "20봉 평균으로 되돌림"}


def _drift(lc, i: int, model: str) -> float:
    """i 봉까지 정보로 본 봉당 기대 로그수익 (모델별)."""
    if model == "mom" and i >= 20:
        return (lc[i] - lc[i - 20]) / 20
    if model == "rev" and i >= 20:
        return (float(np.mean(lc[i - 19:i + 1])) - lc[i]) / 10    # 10봉에 걸쳐 평균까지 돌아간다고 봄
    return 0.0


def _quant(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q
    f = math.floor(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


def _cone(lc, i: int, h: int, model: str, win: int = 400, widen: float = 1.0, vol: bool = False) -> list[float]:
    """i 봉에서 h 봉 뒤 로그가격의 분위수: 과거 h봉 수익률 분포(평균 뺌) × 폭 보정 + 모델 기대치 × h."""
    a = _np(lc)
    lo = max(0, i - win)
    if i - h + 1 - lo < 30:
        return []
    rs = a[lo + h:i + 1] - a[lo:i - h + 1]
    k = 1.0
    if vol:
        one = a[lo + 1:i + 1] - a[lo:i]
        rec = one[-30:]
        if len(rec) >= 10 and one.std() > 0:
            k = min(max(rec.std() / one.std(), 0.5), 3.0)
    d = _drift(lc, i, model) * min(h, 10 if model == "rev" else h)
    q = np.quantile(rs, QS)
    return list(a[i] + (q - rs.mean()) * k * widen + d)


def _np(lc):
    return lc if isinstance(lc, np.ndarray) else np.asarray(lc, dtype=float)


def validate(b: list[list], h: int, tests: int = 200, widen: float = 1.0, vol: bool = False,
             models=None, upto: int | None = None) -> dict:
    """upto 봉 전까지의 tests 번 시점마다 그때까지 정보로 h 봉 뒤를 추정하고 실제와 비교 (미래 정보 없음)."""
    lc = np.log([x[4] for x in b])
    end = (upto if upto is not None else len(b)) - h
    out = {}
    for mdl in models or MODELS:
        cov80 = cov50 = hit = n_dir = n = 0
        pin = 0.0
        for i in range(max(h + 60, end - tests), end):
            q = _cone(lc, i, h, mdl, widen=widen, vol=vol)
            if not q:
                continue
            y = lc[i + h]
            n += 1
            cov80 += q[0] <= y <= q[4]
            cov50 += q[1] <= y <= q[3]
            pin += sum(max(t * (y - v), (t - 1) * (y - v)) for t, v in zip(QS, q)) / len(QS)
            if mdl != "flat" and abs(q[2] - lc[i]) > 1e-9:
                n_dir += 1
                hit += (q[2] > lc[i]) == (y > lc[i])
        if n:
            out[mdl] = {"n": n, "cov80": cov80 / n * 100, "cov50": cov50 / n * 100, "pin": pin / n * 1e4,
                        "dir": hit / n_dir * 100 if n_dir else None, "ndir": n_dir}
    return out


def forecast(b: list[list], tf: str) -> dict | None:
    """다음 H 봉의 가능성 범위.
    1) 방식(방향 없음/흐름/되돌림)과 폭 보정(1~2배, 최근 변동성 반영 여부)을 앞쪽 200번 시점으로 고르고
    2) 그 선택을 바로 뒤 200번 시점(고를 때 안 본 구간)에서 다시 채점해 화면에 보여준다."""
    h = {"1m": 30, "5m": 24, "15m": 16, "1h": 12, "1d": 10}.get(tf, 20)
    T = min(200, (len(b) - h - 120) // 2)
    if T < 60:
        return None
    lc = np.log([x[4] for x in b])
    key = (tf, len(b) // 50, round(b[0][4], 4))
    hit = _fc_cache.get(key)
    if hit and time.time() - hit[0] < 600:                   # 방식 고르기는 무거우니 10분 동안 재사용
        return _fc_out(lc, h, *hit[1])
    cut = len(b) - T                                        # 여기까지로 고르고, 이후 T 번으로 확인
    best, score = None, None
    for mdl in MODELS:
        for w in (1.0, 1.5, 2.0):
            for vol in (False, True):
                v = validate(b, h, T, w, vol, (mdl,), upto=cut).get(mdl)
                if not v:
                    continue
                sc = v["pin"] + abs(v["cov80"] - 80) * 2           # 정확하면서 80% 띠가 실제로 80% 맞게
                if score is None or sc < score:
                    best, score = (mdl, w, vol), sc
    if not best:
        return None
    mdl, w, vol = best
    chk = validate(b, h, T, w, vol, (mdl,)).get(mdl)          # 고를 때 안 본 마지막 T 번
    # 예상선(방향): '흐름 이어짐'과 '되돌림' 중 고를 때 안 본 구간에서 방향을 더 잘 맞힌 쪽, 둘 다 55% 미만이면 평평하게
    dirs = {m: validate(b, h, T, 1.0, False, (m,), upto=cut).get(m, {}).get("dir") or 0 for m in ("mom", "rev")}
    lm = max(dirs, key=dirs.get)
    lm = lm if dirs[lm] >= 55 else "flat"
    lchk = validate(b, h, T, 1.0, False, (lm,)).get(lm) if lm != "flat" else None
    args = (mdl, w, vol, chk, lm, dirs.get(lm), lchk and lchk["dir"])
    _fc_cache[key] = (time.time(), args)
    return _fc_out(lc, h, *args)


def _fc_out(lc, h, mdl, w, vol, chk, lm, dir_pick, dir_check) -> dict:
    """예상선(lm 방식의 가운데 값)과 좁은 50% 범위를 기본 h 봉의 FAR 배까지. 끌어서 더 먼 미래를 볼 수 있게."""
    i = len(lc) - 1
    line, band = [], []
    d = _drift(lc, i, lm) if lm != "flat" else 0.0
    cap = 10 if lm == "rev" else h                          # 검증한 거리(h 봉)까지만 기울이고 그 뒤는 평평하게
    for k in range(1, FAR * h + 1):
        q = _cone(lc, i, k, mdl, widen=w, vol=vol, win=max(400, 3 * k))   # 먼 미래는 더 긴 과거로 범위를 잡는다
        if not q:
            continue
        mid = lc[i] + d * min(k, cap)                       # 매끈한 예상선 (분위수 잡음 없이)
        line.append(math.exp(mid))
        band.append([math.exp(mid + q[1] - q[2]), math.exp(mid + q[3] - q[2])])
    out = {"h": h, "line": line, "band": band, "model": lm, "label": MODELS[lm],
           "check": chk, "dir_check": dir_check, "dir_pick": dir_pick}
    out["strength"] = strength(out)
    return out


def strength(fc: dict | None) -> float:
    """예측 세기 0~1: 고를 때 안 본 구간에서의 방향 적중률로 정한다 (50% → 0, 70% 이상 → 1). 평평하면 0."""
    if not fc or fc.get("model") == "flat" or fc.get("dir_check") is None:
        return 0.0
    return max(0.0, min(1.0, (fc["dir_check"] - 50) / 20))


def quick_forecast(sym: str, recent: list[list], tf: str = "1m") -> dict | None:
    """다른 탭 차트용: 야후 봉 + 증권사 최근 봉으로 다음 h 봉 예상선 (방식 선택은 10분 캐시)."""
    try:
        b, _ = merge_recent(bars(sym, tf), recent, tf)
        f = forecast(b, tf)
    except Exception as e:
        log.info("예상선 계산 실패 %s: %s", sym, e)
        return None
    if not f:
        return None
    h = f["h"]
    return {"h": h, "line": f["line"][:h], "band": f["band"][:h], "model": f["model"], "label": f["label"],
            "dir_check": f["dir_check"], "strength": strength(f)}


# ── 계획: 차트 정보(지지·저항, 박스, 예상선, 장기 추세, 과거 반등률)를 모아 Claude 가 매매 계획 하나를 낸다
from typing import Literal
from pydantic import BaseModel, Field

_plan_cache: dict = {}


class Plan(BaseModel):
    action: Literal["BUY", "AVOID", "WAIT"] = Field(description="BUY=이 종목 매수, AVOID=이 종목은 사지 말 것(하락 쪽, 반대 종목 고려), WAIT=관망")
    entry_lo: float = Field(description="진입 가격대 아래 (이 종목 가격). WAIT/AVOID 면 기다릴 가격대")
    entry_hi: float = Field(description="진입 가격대 위")
    target: float = Field(description="목표가")
    stop: float = Field(description="손절가")
    horizon: str = Field(description="보유 기간 (예: '오늘 장중', '2~3일', '몇 주')")
    confidence: float = Field(description="확신도 0~1")
    reasons: list[str] = Field(description="근거 2~4개, 각 한 문장 (한국어)")
    long_view: str = Field(description="장기 관점 한 문장 (한국어)")


PLAN_SYSTEM = """\
당신은 미국 반도체 레버리지 ETF 차트를 보고 개인 투자자에게 매매 계획 하나를 제시합니다.
입력 JSON: 종목, 봉 단위, 현재가, 한 봉 평균 움직임(atr), 가까운 지지대·저항대(가격 범위와 닿은 횟수), 박스,
과거에 지지대·저항대 근처에서 실제로 반등/이탈한 비율, 예상선(방향과 과거 방향 적중률), 장기 추세(50·200일 평균, 1년 고점 대비 하락률,
레버리지 감가). SOXL 은 반도체 3배, SOXS 는 반대 3배입니다.
- 근거가 약하면(반등률·적중률이 50% 근처, 신호가 엇갈림) WAIT 를 고르고 기다릴 가격대를 주세요. 억지로 매수하지 마세요.
- 가격은 반드시 이 종목 가격으로, 손절은 진입가대 바깥, 목표는 손절보다 멀게(손익비 1.5 이상) 잡으세요.
- 3배 레버리지는 오래 들수록 감가가 크다는 점을 보유 기간에 반영하세요.
- confidence 는 실제로 맞을 가능성이고, 과거 적중률보다 높게 쓰지 마세요."""


def _plan_input(sym: str, tf: str, d: dict) -> dict:
    lt = None
    try:
        lt = longterm(sym)
    except Exception:
        pass
    fc = d.get("fc") or {}
    st = d.get("stats") or {}
    rate = lambda a: round(a[0] / (a[0] + a[1]) * 100) if a and a[0] + a[1] else None   # noqa: E731
    band = lambda x: x and {"범위": [round(x["lo"], 2), round(x["hi"], 2)], "닿은 횟수": x["n"]}   # noqa: E731
    return {"종목": sym, "봉": TFLABEL.get(tf, tf), "현재가": round(d["last"], 2), "atr": round(d["atr"], 3),
            "지지대": band(d.get("sup")), "저항대": band(d.get("res")),
            "박스": d.get("box") and [round(d["box"]["lo"], 2), round(d["box"]["hi"], 2)],
            "지지대 근처 반등률%": rate(st.get("sup")), "저항대 근처 되밀림률%": rate(st.get("res")),
            "예상선": fc and {"방식": fc.get("label"), f"{fc.get('h')}봉 뒤": fc.get("line") and round(fc["line"][fc["h"] - 1], 2),
                            "방향 적중%": fc.get("dir_check") and round(fc["dir_check"])},
            "장기": lt and not lt.get("error") and {"50일평균": round(lt["ma50"], 2), "200일평균": round(lt["ma200"], 2),
                                                 "1년고점대비%": round(lt["dd"], 1), "감가": lt.get("decay")}}


def _rule_plan(d: dict) -> dict:
    """Claude 를 못 쓸 때: 손익비 1.5 이상일 때만 지지대 위 매수 / 저항대 아래 회피, 아니면 관망."""
    p = _rule_plan0(d)
    mid = (p["entry_lo"] + p["entry_hi"]) / 2
    if p["action"] != "WAIT" and abs(p["target"] - mid) < 1.5 * abs(mid - p["stop"]):
        p.update(action="WAIT", confidence=0.3, reasons=p["reasons"] + ["목표까지 거리가 손절 거리의 1.5배가 안 돼 기다림"])
    return p


def _rule_plan0(d: dict) -> dict:
    last, a = d["last"], d["atr"]
    sup, res = d.get("sup"), d.get("res")
    if sup and last - sup["hi"] <= 0.5 * a:
        return {"action": "BUY", "entry_lo": sup["lo"], "entry_hi": sup["hi"] + 0.3 * a, "target": res["lo"] if res else last + 2 * a,
                "stop": sup["lo"] - 0.5 * a, "horizon": "오늘 장중", "confidence": 0.5,
                "reasons": ["지지대 바로 위", "목표는 위 저항대"], "long_view": "", "src": "규칙"}
    if res and res["lo"] - last <= 0.5 * a:
        return {"action": "AVOID", "entry_lo": res["lo"] - 0.3 * a, "entry_hi": res["hi"], "target": sup["hi"] if sup else last - 2 * a,
                "stop": res["hi"] + 0.5 * a, "horizon": "오늘 장중", "confidence": 0.5,
                "reasons": ["저항대 바로 아래", "되밀리면 아래 지지대까지"], "long_view": "", "src": "규칙"}
    lo = sup["hi"] if sup else last - a
    return {"action": "WAIT", "entry_lo": lo, "entry_hi": lo + 0.3 * a, "target": res["lo"] if res else last + 2 * a,
            "stop": lo - 0.8 * a, "horizon": "-", "confidence": 0.3,
            "reasons": ["지지대·저항대 어느 쪽에도 가깝지 않음"], "long_view": "", "src": "규칙"}


def cached_plan(sym: str, tf: str) -> dict | None:
    """이미 받은 계획 (Claude 를 부르지 않음)."""
    hit = _plan_cache.get((sym, tf))
    return hit[1] if hit else None


def plan(sym: str, tf: str, d: dict, model: str = "claude-haiku-5-5", ttl: float = 60) -> dict:
    """사용자가 버튼을 눌렀을 때만 부른다. 같은 종목·봉 단위를 1분 안에 다시 누르면 앞 결과를 돌려준다."""
    key = (sym, tf)
    hit = _plan_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    if d.get("error") or not d.get("last"):
        return {"error": "차트 정보 부족"}
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=60.0, max_retries=1)
        resp = client.messages.parse(model=model, max_tokens=4000, system=PLAN_SYSTEM, output_format=Plan,
                                     messages=[{"role": "user", "content": json.dumps(_plan_input(sym, tf, d), ensure_ascii=False)}])
        if resp.parsed_output is None:
            raise ValueError(f"stop_reason={resp.stop_reason}")
        out = {**resp.parsed_output.model_dump(), "src": "Claude"}
    except Exception as e:
        log.info("계획 생성 실패, 규칙으로 대신: %s", e)
        out = {**_rule_plan(d), "note": f"AI 판단을 받지 못해 규칙으로 계산 ({type(e).__name__})"}
    out["at"] = time.time()
    _plan_cache[key] = (time.time(), out)
    return out


def warmer(stop: threading.Event, recent_fn=None, every: float = 240) -> None:
    """서버 시작 직후와 이후 몇 분마다 자주 보는 차트를 미리 계산해 둔다 (첫 화면이 느리지 않게)."""
    keys = [("SOXL", "5m"), ("SOXL", "1m"), ("SOXS", "1m"), ("SOXS", "5m")]
    while not stop.is_set():
        for sym, tf in keys:
            try:
                extra = recent_fn(sym) if recent_fn else []
                analyze(sym, tf, extra)
                if tf == "1m":
                    quick_forecast(sym, extra)
            except Exception as e:
                log.info("미리 계산 실패 %s %s: %s", sym, tf, e)
        stop.wait(every)
