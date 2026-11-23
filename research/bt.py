"""SOXL/SOXS 장중 전략 백테스트. 신호는 SOXL 1분봉으로 계산하고, 하락 쪽은 SOXS 를 매수한다.
체결: 신호가 난 봉의 다음 봉 시가 + 슬리피지. 청산: 손절/익절/추적손절은 봉의 고가·저가로 보수적으로 판정.
수수료 편도 0.25%, 슬리피지 편도 0.03%. 자본은 매일 1000만원(=$7,143)으로 고정(복리 없음)."""
import json, datetime, zoneinfo, math, sys, itertools, statistics
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, SLIP, CAP = 0.0025, 0.0003, 10_000_000 / 1400


def load(path):
    out = {}
    for t, o, h, l, c, v in json.load(open(path)):
        out[t] = (o, h, l, c, v)
    return out


def build(datadir):
    L, S = load(f"{datadir}/SOXL_1m.json"), load(f"{datadir}/SOXS_1m.json")
    N, X = load(f"{datadir}/NVDA_1m.json"), load(f"{datadir}/SOXX_1m.json")
    days = {}
    for t in sorted(L):
        dt = datetime.datetime.fromtimestamp(t, ET)
        days.setdefault(dt.date(), []).append(t)
    out = []
    for d, ts in days.items():
        reg = [t for t in ts if (9, 30) <= (datetime.datetime.fromtimestamp(t, ET).hour, datetime.datetime.fromtimestamp(t, ET).minute) < (16, 0)]
        if len(reg) < 300:
            continue
        pre = [t for t in ts if t < reg[0]]
        day = {"date": d, "t": reg}
        # SOXL: 지표는 프리마켓 포함 연속 계산, VWAP 은 09:30 부터
        allt = pre[-120:] + reg
        cl = [L[t][3] for t in allt]
        hi = [L[t][1] for t in allt]
        lo = [L[t][2] for t in allt]
        def ema(xs, n):
            k, e, r = 2 / (n + 1), xs[0], []
            for x in xs:
                e = x * k + e * (1 - k); r.append(e)
            return r
        e9, e20 = ema(cl, 9), ema(cl, 20)
        tr = [hi[0] - lo[0]] + [max(hi[i] - lo[i], abs(hi[i] - cl[i-1]), abs(lo[i] - cl[i-1])) for i in range(1, len(cl))]
        atr = ema(tr, 14)
        # RSI
        g = l_ = 0.0; rsi = []
        for i in range(len(cl)):
            dlt = cl[i] - cl[i-1] if i else 0
            g = (g * 13 + max(dlt, 0)) / 14; l_ = (l_ * 13 + max(-dlt, 0)) / 14
            rsi.append(100 - 100 / (1 + g / l_) if l_ else 50)
        off = len(allt) - len(reg)
        day["L"] = [L[t] for t in reg]
        def fill(src):
            r, last = [], None
            for t in reg:
                last = src.get(t, last) or last
                r.append(last)
            return r
        day["S"] = fill(S)
        day["N"] = fill(N); day["X"] = fill(X)
        day["e9"], day["e20"] = e9[off:], e20[off:]
        day["atr"] = [a / c * 100 for a, c in zip(atr[off:], cl[off:])]
        day["rsi"] = rsi[off:]
        pv = vv = 0; vw = []
        for o, h, l, c, v in day["L"]:
            pv += (h + l + c) / 3 * (v or 1); vv += (v or 1); vw.append(pv / vv)
        day["vwap"] = vw
        out.append(day)
    return out


def run(days, sig, p, verbose=False):
    """sig(day, i, p, state) -> 'L' | 'S' | None (진입), 보유 중엔 'X' 면 청산."""
    res = []
    for day in days:
        n = len(day["t"]); pos = None; pnl = 0.0; trades = []; st = {}
        i = 0
        while i < n:
            if pos:
                side, qty, ent, i0, peak, stop, take = pos
                o, h, l, c, v = day["L"][i] if side == "L" else day["S"][i]
                ex = None
                if l <= stop:
                    ex = (min(o, stop), "SL")
                elif h >= take:
                    ex = (max(o, take), "TP")
                else:
                    tr = p.get("trail")
                    if tr and (peak / ent - 1) * 100 >= tr + 2 * FEE * 100:
                        lvl = peak * (1 - tr / 100)
                        if l <= lvl:
                            ex = (min(o, lvl), "TR")
                    if not ex and p.get("hold") and i - i0 >= p["hold"] and (c / ent - 1) * 100 < 2 * FEE * 100 + 0.1:
                        ex = (c, "TIME")
                    if not ex and i >= n - 5:
                        ex = (c, "EOD")
                    if not ex and sig(day, i, p, st, side) == "X":
                        ex = (c, "SIG")
                pos = (side, qty, ent, i0, max(peak, h), stop, take)
                if ex:
                    px = ex[0] * (1 - SLIP)
                    net = (px - ent) * qty - FEE * (px + ent) * qty
                    pnl += net; trades.append((side, ex[1], net, i - i0))
                    pos = None
                    if p.get("daylim") and (pnl <= -p["daylim"] * CAP or pnl >= p["daylim"] * CAP):
                        break
                i += 1
                continue
            if 2 <= i < n - 20 and len(trades) < p.get("maxtr", 999):
                s = sig(day, i, p, st, None)
                if s in ("L", "S") and i + 1 < n:
                    bars = day["L"] if s == "L" else day["S"]
                    ent = bars[i + 1][0] * (1 + SLIP)
                    qty = int(CAP / (ent * (1 + FEE)))
                    a = day["atr"][i]
                    sl = p.get("slk") * a if p.get("slk") else p["sl"]
                    tp = p.get("tpk") * a if p.get("tpk") else p["tp"]
                    sl = min(max(sl, 0.3), p.get("slmax", 3.0)); tp = min(max(tp, 0.8), p.get("tpmax", 20))
                    pos = (s, qty, ent, i + 1, ent, ent * (1 - sl / 100), ent * (1 + tp / 100))
                    i += 1
                    continue
            i += 1
        res.append((day["date"], pnl, trades))
    return res


def stats(res):
    tot = sum(r[1] for r in res); tr = [t for r in res for t in r[2]]
    wins = [t[2] for t in tr if t[2] > 0]; loss = [t[2] for t in tr if t[2] <= 0]
    eq = mdd = peak = 0
    for r in res:
        eq += r[1]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {"ret%": round(tot / CAP * 100, 1), "krw": round(tot * 1400), "trades": len(tr),
            "tr/day": round(len(tr) / max(len(res), 1), 1), "win%": round(len(wins) / max(len(tr), 1) * 100),
            "avgW%": round(statistics.mean(wins) / CAP * 100, 2) if wins else 0,
            "avgL%": round(statistics.mean(loss) / CAP * 100, 2) if loss else 0,
            "+days": sum(1 for r in res if r[1] > 0), "days": len(res), "mdd%": round(mdd / CAP * 100, 1)}


# ── 전략들 ─────────────────────────────────────────────────────
def trend_dir(d, i):
    c = d["L"][i][3]
    if d["e9"][i] > d["e20"][i] and c > d["vwap"][i]:
        return "L"
    if d["e9"][i] < d["e20"][i] and c < d["vwap"][i]:
        return "S"
    return None


def s_scalp(d, i, p, st, held):       # 지금 가상매매와 비슷: 추세+1·3분 모멘텀, 추격 제한
    if held:
        return None
    t = trend_dir(d, i)
    if not t or i < 3:
        return None
    c, c1, c3 = d["L"][i][3], d["L"][i-1][3], d["L"][i-3][3]
    r1, r3 = (c / c1 - 1) * 100, (c / c3 - 1) * 100
    ext = (c / d["e9"][i] - 1) * 100
    sgn = 1 if t == "L" else -1
    if sgn * r3 > 0 and abs(ext) < p.get("extk", 99) * d["atr"][i]:
        return t
    return None


def s_pullback(d, i, p, st, held):    # 추세 방향 + EMA9 근처 되돌림 후 반등 봉
    t = trend_dir(d, i)
    if held:
        return "X" if p.get("sigexit") and t and t != held else None
    if not t:
        return None
    o, h, l, c, v = d["L"][i]
    e9, a = d["e9"][i], d["atr"][i] / 100 * c
    if t == "L" and l <= e9 + p["pb"] * a and c > o and c > e9:
        return "L"
    if t == "S" and h >= e9 - p["pb"] * a and c < o and c < e9:
        return "S"
    return None


def s_breakout(d, i, p, st, held):    # n분 고점/저점 돌파 + 추세
    t = trend_dir(d, i)
    if held:
        return "X" if p.get("sigexit") and t and t != held else None
    n = p["n"]
    if i < n or not t:
        return None
    c = d["L"][i][3]
    hh = max(b[1] for b in d["L"][i-n:i]); ll = min(b[2] for b in d["L"][i-n:i])
    if t == "L" and c > hh:
        return "L"
    if t == "S" and c < ll:
        return "S"
    return None


def s_orb(d, i, p, st, held):         # 개장 n분 범위 돌파 (운용자 가설: 개장 추세 ~10분 지속)
    n = p["n"]
    if held:
        return None
    if i < n:
        return None
    if "hh" not in st:
        st["hh"] = max(b[1] for b in d["L"][:n]); st["ll"] = min(b[2] for b in d["L"][:n])
    c = d["L"][i][3]
    if i > p.get("window", 400):
        return None
    if c > st["hh"]:
        return "L"
    if c < st["ll"]:
        return "S"
    return None


def s_vwap(d, i, p, st, held):        # VWAP 추세 추종(히스테리시스) - 신호 반전 때만 청산
    c, vw = d["L"][i][3], d["vwap"][i]
    up = c > vw * (1 + p["band"] / 100) and d["e9"][i] > d["e20"][i]
    dn = c < vw * (1 - p["band"] / 100) and d["e9"][i] < d["e20"][i]
    if held:
        return "X" if (held == "L" and dn) or (held == "S" and up) else None
    return "L" if up else "S" if dn else None


def s_revert(d, i, p, st, held):      # 과매도/과매수 역추세
    if held:
        return None
    r, c, vw, a = d["rsi"][i], d["L"][i][3], d["vwap"][i], d["atr"][i]
    if r < p["lo"] and (c / vw - 1) * 100 < -p["dev"] * a:
        return "L"
    if r > 100 - p["lo"] and (c / vw - 1) * 100 > p["dev"] * a:
        return "S"
    return None


STRATS = {"scalp": s_scalp, "pullback": s_pullback, "breakout": s_breakout, "orb": s_orb, "vwap": s_vwap, "revert": s_revert}


def s_orb2(d, i, p, st, held):
    """개장 n분 범위 돌파 + (선택) 엔비디아·SOXX 동조 + (선택) VWAP 쪽 확인."""
    n = p["n"]
    if held or i < n or i > p.get("window", 400):
        return None
    if "hh" not in st:
        st["hh"] = max(b[1] for b in d["L"][:n]); st["ll"] = min(b[2] for b in d["L"][:n])
        st["n0"], st["x0"] = d["N"][0][0], d["X"][0][0]
    c = d["L"][i][3]
    side = "L" if c > st["hh"] * (1 + p.get("buf", 0) / 100) else "S" if c < st["ll"] * (1 - p.get("buf", 0) / 100) else None
    if not side:
        return None
    sg = 1 if side == "L" else -1
    if p.get("peer"):
        nv = d["N"][i][3] / st["n0"] - 1; sx = d["X"][i][3] / st["x0"] - 1
        if sg * nv <= 0 or sg * sx <= 0:
            return None
    if p.get("vw") and sg * (c - d["vwap"][i]) <= 0:
        return None
    return side


STRATS["orb2"] = s_orb2
