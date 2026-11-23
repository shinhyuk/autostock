"""정규장 밖(프리마켓 04:00~09:25 ET, 애프터마켓 16:00~19:55 ET)에서 같은 전략 계열을 백테스트."""
import sys, json, datetime, zoneinfo, itertools, statistics
sys.path.insert(0, sys.argv[1])
import bt
from bt import run, stats, STRATS
ET = zoneinfo.ZoneInfo("America/New_York")
D = sys.argv[2]
L, S, N, X = (bt.load(f"{D}/{s}_1m.json") for s in ("SOXL", "SOXS", "NVDA", "SOXX"))


def build(h0, m0, h1, m1, minbars):
    days = {}
    for t in sorted(L):
        dt = datetime.datetime.fromtimestamp(t, ET)
        if (h0, m0) <= (dt.hour, dt.minute) < (h1, m1):
            days.setdefault(dt.date(), []).append(t)
    out = []
    for d, ts in days.items():
        if len(ts) < minbars:
            continue
        cl = [L[t][3] for t in ts]
        def ema(xs, n):
            k, e, r = 2 / (n + 1), xs[0], []
            for x in xs:
                e = x * k + e * (1 - k); r.append(e)
            return r
        hi = [L[t][1] for t in ts]; lo = [L[t][2] for t in ts]
        tr = [hi[0] - lo[0]] + [max(hi[i] - lo[i], abs(hi[i] - cl[i-1]), abs(lo[i] - cl[i-1])) for i in range(1, len(cl))]
        def fill(src):
            r, last = [], None
            for t in ts:
                last = src.get(t, last) or last
                r.append(last)
            return r
        day = {"date": d, "t": ts, "L": [L[t] for t in ts], "S": fill(S), "N": fill(N), "X": fill(X),
               "e9": ema(cl, 9), "e20": ema(cl, 20), "atr": [a / c * 100 for a, c in zip(ema(tr, 14), cl)], "rsi": [50] * len(ts)}
        if any(v is None for v in day["S"]) or any(v is None for v in day["N"]):
            continue
        if any(v is None for v in day["X"]):
            day["X"] = day["N"]
        pv = vv = 0; vw = []
        for o, h, l, c, v in day["L"]:
            pv += (h + l + c) / 3 * (v or 1); vv += (v or 1); vw.append(pv / vv)
        day["vwap"] = vw
        out.append(day)
    return out


for name, win, slips in (("프리마켓", (4, 0, 9, 25, 250), (0.0010, 0.0020)), ("애프터마켓", (16, 0, 19, 55, 180), (0.0010, 0.0020))):
    days = build(*win)
    print(f"\n=== {name}: {len(days)}일 (봉 수 {min(len(d['t']) for d in days)}~{max(len(d['t']) for d in days)})")
    for slip in slips:
        bt.SLIP = slip
        rows = []
        for n, tp, sl, tr, w, mt, peer in itertools.product((15, 20, 30, 45, 60), (6, 10), (1.0, 1.5, 2.0), (0, 3.0), (60, 120, 999), (1, 2), (0, 1)):
            p = dict(n=n, peer=peer, tp=tp, sl=sl, trail=tr, window=w, maxtr=mt, hold=0)
            a, b = run(days[:len(days)//2], STRATS["orb2"], p), run(days[len(days)//2:], STRATS["orb2"], p)
            rows.append((p, stats(a), stats(b), stats(a + b)))
        allr = [r[3]["ret%"] for r in rows]
        both = sum(1 for r in rows if r[1]["ret%"] > 0 and r[2]["ret%"] > 0)
        print(f" 슬리피지 편도 {slip*100:.2f}%: 조합 {len(rows)}개 중앙값 {statistics.median(allr):+.1f}%, 앞·뒤 모두 플러스 {both}개")
        for key in ("n", "peer", "sl", "trail", "maxtr"):
            vals = sorted(set(p[key] for p, *_ in rows))
            print(f"   {key:6s}", {v: round(statistics.median(r[3]["ret%"] for r in rows if r[0][key] == v), 1) for v in vals})
        # 정규장에서 고른 설정을 그대로 썼을 때
        p = dict(n=20, peer=1, tp=10, sl=1.5, trail=3.0, window=120, maxtr=2, hold=0)
        print("   정규장 설정 그대로:", stats(run(days, STRATS["orb2"], p)))
    bt.SLIP = 0.0003
