"""여러 종목에 개장 범위 돌파를 같은 조건으로 돌려 비교한다. 수수료 편도 0.25%, 슬리피지 편도 0.03%, 1000만원 고정."""
import sys, json, os, datetime, zoneinfo, itertools, statistics
ET = zoneinfo.ZoneInfo("America/New_York")
D = sys.argv[1]
FEE, SLIP, CAP = 0.0025, 0.0003, 10_000_000 / 1400
TF, MINBARS = "1m", 300
_c = {}


def FEE_():
    return FEE


def load(s):
    if s not in _c:
        p = f"{D}/{s}_{TF}.json"
        _c[s] = {t: (o, h, l, c, v) for t, o, h, l, c, v in json.load(open(p))} if os.path.exists(p) else None
    return _c[s]


def build(bull, bear, peers):
    L, S = load(bull), load(bear) if bear else None
    P = [load(p) for p in peers]
    if L is None or (bear and S is None) or any(x is None for x in P):
        return None
    days = {}
    for t in sorted(L):
        dt = datetime.datetime.fromtimestamp(t, ET)
        if (9, 30) <= (dt.hour, dt.minute) < (16, 0):
            days.setdefault(dt.date(), []).append(t)
    out = []
    for d, ts in days.items():
        if len(ts) < MINBARS:
            continue
        def fill(src):
            r, last = [], None
            for t in ts:
                last = src.get(t, last) or last
                r.append(last)
            return r
        day = {"date": d, "L": [L[t] for t in ts], "S": fill(S) if S else None, "P": [fill(p) for p in P]}
        if (day["S"] and day["S"][0] is None) or any(p[0] is None for p in day["P"]):
            continue
        out.append(day)
    return out


def run(days, p):
    n = p["n"]
    res, widths = [], []
    for day in days:
        L, S = day["L"], day["S"]
        hh = max(b[1] for b in L[:n]); ll = min(b[2] for b in L[:n]); mid = (hh + ll) / 2
        width = (hh - ll) / mid * 100
        prev = widths[-5:]
        widths.append(width)
        skip = p.get("wmax") and len(prev) >= 3 and width > p["wmax"] * statistics.mean(prev)
        pnl, trades, pos, i, conf = 0.0, [], None, n, 0
        p0 = [pp[0][0] for pp in day["P"]]
        while i < len(L):
            if pos:
                side, qty, ent, peak, stop, take = pos
                o, h, l, c, v = (L if side == "L" else S)[i]
                ex = None
                if l <= stop:
                    ex = min(o, stop)
                elif h >= take:
                    ex = max(o, take)
                else:
                    tr = p["trail"]
                    if tr and (peak / ent - 1) * 100 >= tr + 2 * FEE * 100 and l <= peak * (1 - tr / 100):
                        ex = min(o, peak * (1 - tr / 100))
                    elif i >= len(L) - 5 or (p.get("tend") and i >= p["tend"]):
                        ex = c
                pos = (side, qty, ent, max(peak, h), stop, take)
                if ex is not None:
                    px = ex * (1 - SLIP)
                    net = (px - ent) * qty - FEE_() * (px + ent) * qty
                    pnl += net; trades.append(net); pos = None
                i += 1
                continue
            if skip or i > p["window"] or len(trades) >= p["maxtr"] or i >= len(L) - 20:
                i += 1
                continue
            c = L[i][3]
            sg = 1 if c > hh * (1 + p.get("buf", 0) / 100) else -1 if c < ll * (1 - p.get("buf", 0) / 100) else 0
            conf = conf + 1 if sg and (conf == 0 or (conf > 0) == (sg > 0)) else (1 if sg else 0)
            conf = conf if sg else 0
            if sg and abs(conf) >= p.get("confirm", 1) and (sg > 0 or S):
                if p["peer"] and any(sg * (pp[i][3] / q0 - 1) <= 0 for pp, q0 in zip(day["P"], p0)):
                    i += 1
                    continue
                side = "L" if sg > 0 else "S"
                bars = L if side == "L" else S
                if i + 1 >= len(L):
                    break
                ent = bars[i + 1][0] * (1 + SLIP)
                qty = int(CAP / (ent * (1 + FEE)))
                if p["stop"] == "mid":                                  # 범위 중간값(기초 종목 기준)을 손절로
                    slp = abs(L[i + 1][0] - mid) / L[i + 1][0] * 100
                    slp = min(max(slp, 0.5), 6) * (1 if side == "L" or not S else 1)
                else:
                    slp = p["sl"]
                pos = (side, qty, ent, ent, ent * (1 - slp / 100), ent * (1 + p["tp"] / 100))
                conf = 0
                i += 1
                continue
            i += 1
        res.append((day["date"], pnl, trades))
    return res


def st(res):
    tot = sum(r[1] for r in res); tr = [t for r in res for t in r[2]]
    daily = [r[1] / CAP * 100 for r in res]
    sd = statistics.pstdev(daily) or 1
    return {"ret": round(tot / CAP * 100, 1), "n": len(tr), "win": round(sum(1 for t in tr if t > 0) / max(len(tr), 1) * 100),
            "pdays": sum(1 for r in res if r[1] > 0), "days": len(res), "sharpe": round(statistics.mean(daily) / sd * 15.87, 1) if res else 0,
            "mdd": round(min([0] + [sum(daily[:k + 1]) - max([0] + [sum(daily[:j + 1]) for j in range(k + 1)]) for k in range(len(daily))]), 1)}


PAIRS = [("SOXL", "SOXS", ("NVDA", "SOXX"), "lev"), ("TQQQ", "SQQQ", ("QQQ", "SPY"), "lev"), ("TECL", "TECS", ("XLK", "QQQ"), "lev"),
         ("SPXL", "SPXS", ("SPY", "QQQ"), "lev"), ("TNA", "TZA", ("IWM", "SPY"), "lev"), ("LABU", "LABD", ("XBI", "SPY"), "lev"),
         ("TSLL", "TSLQ", ("TSLA", "QQQ"), "lev"), ("NVDL", "NVDD", ("NVDA", "SOXX"), "lev")]
SINGLES = [(s, None, pe, "one") for s, pe in [("NVDA", ("SOXX", "QQQ")), ("AMD", ("SOXX", "QQQ")), ("MU", ("SOXX", "QQQ")),
           ("AVGO", ("SOXX", "QQQ")), ("INTC", ("SOXX", "QQQ")), ("TSLA", ("QQQ", "SPY")), ("AAPL", ("XLK", "QQQ")),
           ("META", ("XLK", "QQQ")), ("MSFT", ("XLK", "QQQ")), ("AMZN", ("QQQ", "SPY")), ("GOOGL", ("XLK", "QQQ")),
           ("PLTR", ("QQQ", "SPY")), ("COIN", ("QQQ", "SPY")), ("MSTR", ("QQQ", "SPY")), ("QQQ", ("SPY", "XLK")), ("SPY", ("QQQ", "IWM"))]]
EXITS = {"lev": dict(sl=1.5, tp=10, trail=3.0), "one": dict(sl=1.0, tp=6, trail=1.5)}

if __name__ == "__main__":
    rows = []
    for bull, bear, peers, kind in PAIRS + SINGLES:
        days = build(bull, bear, peers)
        if not days:
            print("데이터 없음", bull); continue
        base = dict(n=20, peer=1, stop="pct", window=120, maxtr=2, **EXITS[kind])
        grid = [dict(base, n=n, maxtr=m, stop=s, sl=sl * (1 if kind == "lev" else 0.67), trail=tr * (1 if kind == "lev" else 0.5))
                for n in (15, 20, 30) for m in (1, 2) for s in ("pct", "mid") for sl in (1.0, 1.5, 2.0) for tr in (0, 3.0)]
        allr = [st(run(days, g)) for g in grid]
        half = [(st(run(days[:len(days)//2], g))["ret"] > 0 and st(run(days[len(days)//2:], g))["ret"] > 0) for g in grid]
        b = st(run(days, base))
        rows.append((bull + ("/" + bear if bear else ""), kind, b, statistics.median(x["ret"] for x in allr), sum(half) / len(half) * 100))
    rows.sort(key=lambda r: -r[3])
    print(f"{'종목':11s} {'종류':4s} {'기본설정 수익':>9s} {'거래':>4s} {'승률':>4s} {'+일':>5s} {'샤프':>5s} {'낙폭':>6s} | {'설정72개 중앙값':>12s} {'앞뒤모두+':>8s}")
    for name, kind, b, med, both in rows:
        print(f"{name:11s} {kind:4s} {b['ret']:+8.1f}% {b['n']:4d} {b['win']:3d}% {b['pdays']:2d}/{b['days']:2d} {b['sharpe']:5.1f} {b['mdd']:5.1f}% | {med:+11.1f}% {both:7.0f}%")
