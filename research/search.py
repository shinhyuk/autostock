import sys, itertools, json
sys.path.insert(0, sys.argv[1])
from bt import build, run, stats, STRATS
days = build(sys.argv[2])
train, test = days[:10], days[10:]
exits = [dict(tp=tp, sl=sl, trail=tr, hold=h) for tp in (1.2, 3, 6) for sl in (1.0, 2.0) for tr in (0, 0.8, 2.0) for h in (0, 8)]
exits_k = [dict(tpk=tk, slk=sk, tp=0, sl=0, trail=tr, hold=0, slmax=4) for tk in (3, 6) for sk in (1.5, 3) for tr in (0, 1.5)]
grids = {
    "scalp": [dict(extk=e) for e in (1, 2, 99)],
    "pullback": [dict(pb=b, sigexit=s) for b in (0.3, 1.0) for s in (0, 1)],
    "breakout": [dict(n=n, sigexit=s) for n in (5, 15, 30) for s in (0, 1)],
    "orb": [dict(n=n, maxtr=m, window=w) for n in (5, 10, 15) for m in (1, 2) for w in (60, 400)],
    "vwap": [dict(band=b, tp=99, sl=s, trail=0, hold=0) for b in (0.1, 0.3, 0.6, 1.0) for s in (2.0, 4.0)],
    "revert": [dict(lo=l, dev=dv) for l in (15, 25) for dv in (1, 2)],
}
rows = []
for name, g in grids.items():
    for sp in g:
        exs = [{}] if name == "vwap" else exits + exits_k
        for ex in exs:
            p = {**ex, **sp}
            tr, te = stats(run(train, STRATS[name], p)), stats(run(test, STRATS[name], p))
            rows.append((name, p, tr, te))
json.dump([(n, p, a, b) for n, p, a, b in rows], open(sys.argv[3], "w"), default=str)
print(len(rows), "combos")
# 전략별: 앞 10일 기준 최고 조합을 뒤 10일에 적용
for name in grids:
    rs = [r for r in rows if r[0] == name and r[2]["trades"] >= 10]
    if not rs:
        continue
    best = max(rs, key=lambda r: r[2]["ret%"])
    med_te = sorted(r[3]["ret%"] for r in rs)[len(rs)//2]
    print(f"\n[{name}] 조합 {len(rs)}개, 뒤10일 중앙값 {med_te}%")
    print("  고른 파라미터:", best[1])
    print("  앞10일:", best[2])
    print("  뒤10일:", best[3])
