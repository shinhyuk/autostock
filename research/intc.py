"""인텔(INTC) 정규장, 매수만(공매도·인버스 없음) 백테스트."""
import sys, json, datetime, zoneinfo, itertools, statistics
sys.path.insert(0, sys.argv[1])
import bt
from bt import run, stats, STRATS
ET = zoneinfo.ZoneInfo("America/New_York")
D = sys.argv[2]
I, N, X, Q = (bt.load(f"{D}/{s}_1m.json") for s in ("INTC", "NVDA", "SOXX", "QQQ"))


def build(peer_a, peer_b):
    days = {}
    for t in sorted(I):
        dt = datetime.datetime.fromtimestamp(t, ET)
        days.setdefault(dt.date(), []).append(t)
    out = []
    for d, ts in days.items():
        reg = [t for t in ts if (9, 30) <= (datetime.datetime.fromtimestamp(t, ET).hour, datetime.datetime.fromtimestamp(t, ET).minute) < (16, 0)]
        if len(reg) < 300:
            continue
        pre = [t for t in ts if t < reg[0]][-120:]
        allt = pre + reg
        cl = [I[t][3] for t in allt]; hi = [I[t][1] for t in allt]; lo = [I[t][2] for t in allt]
        def ema(xs, n):
            k, e, r = 2 / (n + 1), xs[0], []
            for x in xs:
                e = x * k + e * (1 - k); r.append(e)
            return r
        tr = [hi[0] - lo[0]] + [max(hi[i] - lo[i], abs(hi[i] - cl[i-1]), abs(lo[i] - cl[i-1])) for i in range(1, len(cl))]
        off = len(pre)
        def fill(src):
            r, last = [], None
            for t in reg:
                last = src.get(t, last) or last
                r.append(last)
            return r
        g = l_ = 0.0; rsi = []
        for i in range(len(cl)):
            dl = cl[i] - cl[i-1] if i else 0
            g = (g * 13 + max(dl, 0)) / 14; l_ = (l_ * 13 + max(-dl, 0)) / 14
            rsi.append(100 - 100 / (1 + g / l_) if l_ else 50)
        day = {"date": d, "t": reg, "L": [I[t] for t in reg], "S": [I[t] for t in reg], "N": fill(peer_a), "X": fill(peer_b),
               "e9": ema(cl, 9)[off:], "e20": ema(cl, 20)[off:], "atr": [a / c * 100 for a, c in zip(ema(tr, 14)[off:], cl[off:])],
               "rsi": rsi[off:]}
        pv = vv = 0; vw = []
        for o, h, l, c, v in day["L"]:
            pv += (h + l + c) / 3 * (v or 1); vv += (v or 1); vw.append(pv / vv)
        day["vwap"] = vw
        out.append(day)
    return out


def longonly(f):
    def g(d, i, p, st, held):
        r = f(d, i, p, st, held)
        return None if r == "S" else r
    return g


for pname, pa, pb in (("SOXX+QQQ", X, Q), ("NVDA+SOXX", N, X)):
    days = build(pa, pb)
    A, B = days[:10], days[10:]
    print(f"\n=== 동조 종목 {pname}, {len(days)}일")
    fams = {
        "orb": (STRATS["orb2"], [dict(n=n, peer=pe, tp=tp, sl=sl, trail=tr, window=w, maxtr=mt, hold=0)
                                 for n, pe, tp, sl, tr, w, mt in itertools.product((15, 20, 30), (0, 1), (3, 6, 10), (0.7, 1.0, 1.5), (0, 1.5, 3.0), (60, 120), (1, 2))]),
        "pullback": (STRATS["pullback"], [dict(pb=b, sigexit=s, tp=tp, sl=sl, trail=tr, hold=0) for b in (0.3, 1.0) for s in (0, 1)
                                          for tp in (1.5, 3, 6) for sl in (0.7, 1.5) for tr in (0, 1.0)]),
        "breakout": (STRATS["breakout"], [dict(n=n, sigexit=s, tp=tp, sl=sl, trail=tr, hold=0) for n in (15, 30, 60) for s in (0, 1)
                                          for tp in (1.5, 3, 6) for sl in (0.7, 1.5) for tr in (0, 1.0)]),
        "scalp": (STRATS["scalp"], [dict(extk=e, tp=tp, sl=sl, trail=tr, hold=h) for e in (1, 2, 99) for tp in (0.8, 1.5, 3)
                                    for sl in (0.5, 1.0) for tr in (0, 0.5) for h in (0, 8)]),
    }
    for name, (f, grid) in fams.items():
        rs = []
        for p in grid:
            a, b = run(A, longonly(f), p), run(B, longonly(f), p)
            rs.append((p, stats(a), stats(b), stats(a + b)))
        both = sum(1 for r in rs if r[1]["ret%"] > 0 and r[2]["ret%"] > 0)
        med = statistics.median(r[3]["ret%"] for r in rs)
        medtr = statistics.median(r[3]["tr/day"] for r in rs)
        print(f" {name:9s} 조합 {len(rs):4d}  20일 중앙값 {med:+7.1f}%  하루 거래 중앙값 {medtr}  앞·뒤 모두 플러스 {both}")
        if name == "orb":
            for key in ("n", "peer", "tp", "sl", "trail", "window", "maxtr"):
                vals = sorted(set(r[0][key] for r in rs))
                print(f"     {key:6s}", {v: round(statistics.median(r[3]["ret%"] for r in rs if r[0][key] == v), 1) for v in vals})
    # 비교 기준: 매일 시가에 사서 종가에 팔기
    bh = [(d["L"][-1][3] * (1 - bt.SLIP) - d["L"][0][0] * (1 + bt.SLIP)) / d["L"][0][0] * 100 - 0.5 for d in days]
    print(f" 기준(매일 시가 매수→종가 매도) 20일 합 {sum(bh):+.1f}%, 오른 날 {sum(1 for x in bh if x > 0)}/{len(bh)}")
