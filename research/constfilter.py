"""돌파·박스·되돌림 진입 때 구성 종목이 같은 방향인지(동조 비율)로 이기는 거래를 가를 수 있나.
동조 비율 = 진입 직전 봉에서, 산 방향(SOXL=오름, SOXS=내림)으로 시가 대비 움직인 구성 종목 비율.
주도주 = 엔비디아·브로드컴·AMD 시가 대비 평균 (산 방향 기준). 사용: python constfilter.py <1분봉> <5분봉>"""
import sys, numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import probsize as P, constit as K

def tag(trades, cdays, step):
    by = {d["date"]: d for d in cdays}
    for t in trades:
        d = by.get(t["date"])
        t["br"] = t["lead"] = None
        if not d: continue
        i = d["grid"].index(t["m"]) if t["m"] in d["grid"] else None
        if i is None: continue
        r = d["C"][:, i] / d["Co"] - 1
        t["br"] = float((t["sd"] * r > 0).mean())
        idx = [d["cons"].index(c) for c in ("NVDA", "AVGO", "AMD") if c in d["cons"]]
        t["lead"] = float(t["sd"] * r[idx].mean() * 100)

def show(trades, label):
    T = [t for t in trades if t["br"] is not None]
    print(f"\n== {label}: {len(T)}회, 기본 승률 {np.mean([t['win'] for t in T]) * 100:.0f}% 평균 {np.mean([t['base'] for t in T]):+.2f}% ==")
    for nm, key, cuts in (("동조 비율", "br", (0, .5, .8, 1.01)), ("주도주(산 방향 %)", "lead", (-99, 0, 1, 99))):
        for lo, hi in zip(cuts, cuts[1:]):
            g = [t for t in T if lo <= t[key] < hi]
            if g:
                kinds = " ".join(f"{k}{sum(x['kind'] == k for x in g)}" for k in ("fade", "orb", "box"))
                print(f"  {nm} {lo:>5}~{hi:<5}: {len(g):2d}회 승률 {np.mean([x['win'] for x in g]) * 100:3.0f}% 평균 {np.mean([x['base'] for x in g]):+5.2f}%  ({kinds})")
    for k in ("orb", "box", "fade"):
        g = [t for t in T if t["kind"] == k]
        if not g: continue
        hi_ = [t for t in g if t["br"] >= .8]; lo_ = [t for t in g if t["br"] < .8]
        f = lambda z: f"{len(z):2d}회 {np.mean([x['win'] for x in z]) * 100:3.0f}% {np.mean([x['base'] for x in z]):+5.2f}%" if z else " 0회"
        print(f"  {k:<4} 동조 80%↑ {f(hi_)} | 80% 미만 {f(lo_)}")

if __name__ == "__main__":
    for lab, folder, tf, step in (("5분봉 60일", sys.argv[2], "5m", 5), ("1분봉 한 달", sys.argv[1], "1m", 1)):
        tr = P.signals(P.build(folder, tf, step), step)
        tag(tr, K.build(folder, tf, step), step)
        show(tr, lab)
