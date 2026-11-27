"""시간외(프리·애프터·주간거래) 직접 매매 도우미. 주문은 하지 않는다.

- 박스: 위·아래 경계에 각각 2번 이상 닿은 45~180분 구간 (꼬리 한 번은 무시). 종가가 2봉 연속 밖으로 나갈 때까지 고정.
- 위치: 박스 위로 돌파 / 상단 구간(위 20%) / 가운데 / 하단 구간(아래 20%) / 아래로 이탈.
- 박스 매매: SOXL 이 하단 구간이면 SOXL, 상단 구간이면 SOXS 매수. 목표는 반대쪽 80% 지점, 손절은 경계 밖 10%.
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
KST = ZoneInfo("Asia/Seoul")
ZONE = 0.2                           # 박스 위·아래 20% = 매수 구간 (정규장 박스권과 같음)
BOX_TARGET, BOX_STOP = 0.8, 0.1      # 목표: 반대쪽으로 폭의 80% 지점, 손절: 경계 밖 폭의 10%
HORIZON_MIN = 120
SLIP_PCT = 0.1                       # 시간외 호가 차이 (편도 가정)
X_CHOICES = (1.0, 1.5, 2.0)
SESS = {"pre": (dtime(4, 0), dtime(9, 30)), "post": (dtime(16, 0), dtime(20, 0))}
SLABEL = {"pre": "프리마켓", "post": "애프터마켓", "day": "주간거래"}
DAY_OPEN_KST, DAY_CLOSE_ET = dtime(10, 0), dtime(3, 15)   # 주간거래: 한국 10:00 ~ 미국 동부 03:15 (봇 설정과 같음)
STALE_MIN = {"pre": 5, "post": 5, "day": 15}               # 주간거래는 거래가 드물어 봉 간격이 길다
ZONES = ("above", "top", "mid", "bottom", "below")
ZLABEL = {"above": "박스 위로 돌파", "top": "박스 상단 구간", "mid": "박스 가운데",
          "bottom": "박스 하단 구간", "below": "박스 아래로 이탈"}
ZSHORT = {"above": "위로 돌파", "top": "상단 구간", "mid": "가운데", "bottom": "하단 구간", "below": "아래로 이탈"}


def _candidates(now: datetime):
    t = now.astimezone(ET)
    for off in range(-1, 7):
        d = t.date() + timedelta(days=off)
        if d.weekday() >= 5:
            continue
        for name, (a, b) in SESS.items():
            yield name, datetime.combine(d, a, ET), datetime.combine(d, b, ET)
        yield "day", datetime.combine(d, DAY_OPEN_KST, KST).astimezone(ET), datetime.combine(d, DAY_CLOSE_ET, ET)


def session(now: datetime):
    """지금이 프리·애프터·주간거래면 (이름, 시작, 끝), 아니면 None. 미국 휴장일은 모른다."""
    return next(((n, o, c) for n, o, c in _candidates(now) if o <= now < c), None)


def next_session(now: datetime):
    return min(((n, o) for n, o, c in _candidates(now) if o > now), key=lambda x: x[1], default=None)


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


BOX_MIN_MIN, BOX_MAX_MIN = 45, 180     # 박스로 볼 구간 길이
BOX_TOL = 0.2                           # 경계에서 폭의 20% 안이면 '닿음'
BOX_TOUCHES = 2                         # 위·아래 경계에 각각 이만큼 따로 닿아야 박스
BOX_WMIN, BOX_WMAX = 0.6, 5.0           # 박스 폭(%) 범위
BREAK_BARS, BREAK_M = 2, 0.1            # 종가가 경계 밖(폭의 10% 넘게)으로 2봉 연속이면 박스 끝
SPAN_GAP = 12 * 3600                    # 시간대 사이 빈 시간(밤사이 등)이 이보다 짧으면 이전 시간대 시세로 만든 박스를 이어 쓴다


def _groups(flags) -> int:
    g, prev = 0, False
    for f in flags:
        if f and not prev:
            g += 1
        prev = f
    return g


def find_boxes(rows: list[list], step: int, nmin: int | None = None, nmax: int | None = None,
               wmax: float | None = None, gap: float = 3600) -> tuple[list, dict]:
    """rows [[ts초,o,h,l,c], ...] 시간순. 고정 박스를 찾는다.
    - 박스: 45~180분 구간에서 위·아래 경계(꼬리 한 번은 무시)에 각각 2번 이상 따로 닿았고, 그동안 종가가 박스 밖으로 나간 적이 없는 가장 긴 구간.
    - 한 번 정해지면 고정. 종가가 경계 밖으로 폭의 10% 넘게 2봉 연속 나가면 돌파로 보고 끝낸 뒤, 그 뒤 봉들로 새 박스를 찾는다.
    돌려주는 값: (봉마다 그 봉 '직전'까지로 정해진 박스 dict 또는 None, 마지막 봉까지 반영한 상태)"""
    res, box, outside, frm, last_break = [], None, 0, 0, None
    nmin = nmin or max(3, BOX_MIN_MIN // step)
    nmax = nmax or BOX_MAX_MIN // step
    wmax = wmax or BOX_WMAX
    for i, r in enumerate(rows):
        res.append(box)
        if i and r[0] - rows[i - 1][0] > gap:           # 밤사이 같은 큰 공백이면 새로 시작
            box, outside, frm = None, 0, i
        if box:
            w = box["hi"] - box["lo"]
            out_up, out_dn = r[4] > box["hi"] + BREAK_M * w, r[4] < box["lo"] - BREAK_M * w
            outside = outside + 1 if (out_up or out_dn) else 0
            if outside >= BREAK_BARS:
                last_break = {"dir": "up" if out_up else "down", "ts": r[0], "hi": box["hi"], "lo": box["lo"]}
                box, outside, frm = None, 0, i - BREAK_BARS + 1
            continue
        for n in range(min(nmax, i + 1 - frm), nmin - 1, -1):
            win = rows[i - n + 1:i + 1]
            hs, ls = sorted(x[2] for x in win), sorted(x[3] for x in win)
            hi, lo = hs[-2], ls[1]
            w = hi - lo
            if not (BOX_WMIN <= w / ((hi + lo) / 2) * 100 <= wmax):
                continue
            if any(x[4] > hi + BREAK_M * w or x[4] < lo - BREAK_M * w for x in win):
                continue
            if (_groups([x[2] >= hi - BOX_TOL * w for x in win]) >= BOX_TOUCHES and
                    _groups([x[3] <= lo + BOX_TOL * w for x in win]) >= BOX_TOUCHES):
                box = {"hi": hi, "lo": lo, "start": win[0][0], "found": r[0]}
                break
    return res, {"box": box, "last_break": last_break}


def live_box(bars: list[list]):
    """1분봉 [[ms,o,h,l,c,v]] 에서 지금(마지막 봉) 쓸 박스 dict 와 직전 돌파. 마지막 봉은 박스 판단에 넣지 않는다."""
    if len(bars) < 2:
        return None, None
    rows = [[b[0] / 1000, *b[1:5]] for b in bars]
    res, st = find_boxes(rows[:-1], 1, gap=SPAN_GAP)    # 이전 시간대 시세도 이어서 → 시간대가 바뀌어도 바로 박스가 있다
    return st["box"], st["last_break"]


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


def _load(path: str, step: int = 5):
    """과거 봉과 그 봉들로 찾은 박스 (파일이 바뀔 때만 다시 계산)."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None, None
    c = _cache.get(path)
    if not c or c["mt"] != mt:
        with open(path, encoding="utf-8") as f:
            rows = [r[:5] for r in json.load(f)]
        c = _cache[path] = {"mt": mt, "rows": rows, "boxes": find_boxes(rows, step)[0], "stats": {}, "box": {}}
    return c, c["rows"]


def samples(rows: list[list], x: float, boxes: list | None = None) -> list[dict]:
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
        bx = boxes[i] if boxes else None
        if not bx:
            continue
        hi, lo, p = bx["hi"], bx["lo"], rows[i][4]
        z = zone(p, hi, lo)
        key = (name, dt.date())
        if last_zone.get(key) == (z, bx["start"]):
            continue                      # 같은 박스의 같은 위치에 머무는 동안은 처음 들어온 순간만 센다
        last_zone[key] = (z, bx["start"])
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


def box_levels(hi: float, lo: float) -> dict:
    """박스 하나의 매수 구간·목표·손절 (그 종목을 박스 아래쪽에서 산다고 볼 때)."""
    w = hi - lo
    return {"buy_max": lo + ZONE * w, "target": lo + BOX_TARGET * w, "stop": lo - BOX_STOP * w}


def box_samples(rows: list[list], boxes: list | None = None) -> list[dict]:
    """과거 5분봉: 시간외에 SOXL 이 하단 구간에 새로 들어오면 SOXL 매수, 상단 구간이면 SOXS 매수(SOXL 반대로 어림).
    목표·손절은 SOXL 박스 기준. 같은 봉에 둘 다 닿으면 손절로 본다. 2시간·시간대 끝까지 안 닿으면 그때 가격으로 정리."""
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
        bx = boxes[i] if boxes else None
        if not bx:
            continue
        hi, lo, p = bx["hi"], bx["lo"], rows[i][4]
        z = zone(p, hi, lo)
        key = (name, dt.date())
        prev, last_zone[key] = last_zone.get(key), (z, bx["start"])
        if z not in ("top", "bottom") or prev == (z, bx["start"]) or t + 15 * 60 > end:
            continue
        w = hi - lo
        long = z == "bottom"
        tgt = lo + BOX_TARGET * w if long else hi - BOX_TARGET * w
        stp = lo - BOX_STOP * w if long else hi + BOX_STOP * w
        res, last = "none", p
        for j in range(i + 1, n):
            r = rows[j]
            if r[0] >= end:
                break
            hit_s = r[3] <= stp if long else r[2] >= stp
            hit_t = r[2] >= tgt if long else r[3] <= tgt
            if hit_s:
                res, last = "loss", stp
                break
            if hit_t:
                res, last = "win", tgt
                break
            last = r[4]
        move = (last / p - 1) * 100 * (1 if long else -1)
        out.append({"s": name, "z": z, "d": dt.date().isoformat(), "r": res, "m": move})
    return out


def box_stats(path: str, fee_pct: float = 0.25, step: int = 5) -> dict | None:
    """{세션: {'bottom'|'top': {n, win, loss, none, avg, old, new}}} — avg 는 수수료·호가 차이 뺀 1회 평균 %."""
    c, rows = _load(path, step)
    if not rows:
        return None
    st = c["box"]
    if fee_pct in st:
        return st[fee_pct]
    sm = box_samples(rows, c["boxes"])
    days = sorted({x["d"] for x in sm})
    mid = days[len(days) // 2] if days else ""
    cost = 2 * fee_pct + 2 * SLIP_PCT
    out: dict = {"days": len(days), "split": mid, "cost": cost, "by": {}}
    for x in sm:
        b = out["by"].setdefault(x["s"], {}).setdefault(x["z"], {"n": 0, "win": 0, "loss": 0, "none": 0,
                                                                  "sum": 0.0, "old": [0, 0.0], "new": [0, 0.0]})
        net = x["m"] - cost
        b["n"] += 1
        b[x["r"]] += 1
        b["sum"] += net
        h = b["old" if x["d"] < mid else "new"]
        h[0] += 1
        h[1] += net
    for sess in out["by"].values():
        for b in sess.values():
            b["avg"] = b["sum"] / b["n"]
            for k in ("old", "new"):
                b[k] = b[k][1] / b[k][0] if b[k][0] else None
    st[fee_pct] = out
    return out


def stats(path: str, x: float, fee_pct: float = 0.25, step: int = 5) -> dict | None:
    """{세션: {위치: {up, dn, none, old:[up,dn], new:[up,dn], ev_up, ev_dn}}, days, since, until}"""
    c, rows = _load(path, step)
    if not rows:
        return None
    ck = (x, fee_pct)
    st = c["stats"]
    if ck in st:
        return st[ck]
    sm = samples(rows, x, c["boxes"])
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


def advice(bull_bars: list[list], bear_bars: list[list], now: datetime, path: str, x: float,
           fee_pct: float = 0.25, day_path: str | None = None) -> dict:
    """화면에 보여줄 판단: 두 종목의 박스, SOXL 위치에 따른 박스 매매 권장(매수·목표·손절가), 참고 확률.
    과거 통계: 프리·애프터는 야후 5분봉(path), 주간거래는 서버가 모은 1분봉(day_path)."""
    s = session(now)
    nxt = next_session(now)
    hp, step = (day_path, 1) if s and s[0] == "day" and day_path else (path, 5)
    st = stats(hp, x, fee_pct, step)
    bst = box_stats(hp, fee_pct, step)
    out: dict = {"x": x, "session": s[0] if s else None, "close": s[2] if s else None,
                 "next": nxt, "stats": st, "bstats": bst}
    if not bull_bars:
        return out
    last = bull_bars[-1][4]
    bear_last = bear_bars[-1][4] if bear_bars else None
    out["last"] = last
    out["bear_last"] = bear_last
    out["age_min"] = (now.timestamp() - bull_bars[-1][0] / 1000) / 60
    bx, brk = live_box(bull_bars)
    out["last_break"] = brk
    if not bx:
        return out
    hi, lo = bx["hi"], bx["lo"]
    z = zone(last, hi, lo)
    out.update(hi=hi, lo=lo, box_start=bx["start"], zone=z, width=(hi - lo) / last * 100, bull_lv=box_levels(hi, lo))
    sx = live_box(bear_bars)[0] if bear_bars else None
    if sx:
        out.update(bear_hi=sx["hi"], bear_lo=sx["lo"], bear_start=sx["start"], bear_lv=box_levels(sx["hi"], sx["lo"]))
    elif bear_last:                                   # SOXS 박스가 아직 없으면 SOXL 박스를 뒤집어 어림
        w = (hi - lo) / last
        out["bear_lv"] = {"buy_max": bear_last * (1 + (last - (hi - ZONE * (hi - lo))) / last),
                          "target": bear_last * (1 + BOX_TARGET * w - (hi - last) / last),
                          "stop": bear_last * (1 - BOX_STOP * w - (hi - last) / last)}
    out["stale"] = bool(s) and out["age_min"] > STALE_MIN[s[0]]
    if not s or out["stale"]:
        return out
    b = ((st or {}).get("by") or {}).get(s[0], {}).get(z)
    side, why = verdict(b, x)
    out.update(b=b, side=side, why=why)
    k = x / 100
    out["plan"] = {"bull": (last, last * (1 + k), last * (1 - k))}
    if bear_last:
        out["plan"]["bear"] = (bear_last, bear_last * (1 + k), bear_last * (1 - k))
    # 박스 매매 권장
    rec = "bull" if z == "bottom" else "bear" if z == "top" else None
    if rec == "bear" and not bear_last:
        rec = None
    out["rec"] = rec
    out["bbox"] = ((bst or {}).get("by") or {}).get(s[0], {})
    if rec:
        lv = out["bull_lv" if rec == "bull" else "bear_lv"]
        px = last if rec == "bull" else bear_last
        gain = (lv["target"] / px - 1) * 100
        cost = 2 * fee_pct + 2 * SLIP_PCT
        out["rec_gain"], out["rec_loss"] = gain, (lv["stop"] / px - 1) * 100
        if gain < cost * 1.5:
            out["rec_thin"] = True                    # 목표까지 남은 폭이 수수료에 비해 작음
    return out


def save_day_bars(path: str, bars, keep_days: int = 60) -> int:
    """주간거래 1분봉을 모아 둔다 (야후에는 주간거래 시세가 없어 과거 통계를 직접 쌓는다). 저장된 날 수를 돌려준다."""
    try:
        with open(path, encoding="utf-8") as f:
            d = {int(r[0]): r for r in json.load(f)}
    except (FileNotFoundError, ValueError):
        d = {}
    for b in bars:
        if session(b.ts) and session(b.ts)[0] == "day":
            t = int(b.ts.timestamp())
            d[t] = [t, b.open, b.high, b.low, b.close]
    cut = time.time() - keep_days * 86400
    rows = [d[t] for t in sorted(d) if t >= cut]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    os.replace(tmp, path)
    return len({datetime.fromtimestamp(r[0], KST).date() for r in rows})
