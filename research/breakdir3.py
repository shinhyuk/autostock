"""2년 1시간봉: 첫 1시간 흐름이 강하고 엔비디아·SOXX도 같은 방향이면 10:30 에 따라 사서 마감까지 (단순 규칙). 반기별 확인."""
import runpy, io, contextlib, numpy as np
buf = io.StringIO()
with contextlib.redirect_stdout(buf): g = runpy.run_path("code/breakdir.py")
build, load, logit_walk = g["build"], g["load"], g["logit_walk"]
COST = 0.6
rows = build("60m", 630, 60); B = load("SOXL", "60m")
def half(d): return f"{d.year % 100}{'상' if d.month <= 6 else '하'}"
def trade(d, sd):
    L = B[d]; ks = sorted(k for k in L if 570 <= k < 960)
    return sd * (L[ks[-1]][3] / L[max(k for k in ks if k < 630)][3] - 1) * 100 - COST
print("규칙: SOXL 첫 1시간 |흐름| ≥ X% 이고 NVDA·SOXX 같은 방향 → 10:30 진입, 마감 청산 (SOXL 기준 %, 비용 0.6%)")
for X in (0, 2, 3, 5, 8):
    by = {}
    for d, f, lab in rows:
        r = f["개장후 흐름"]
        if abs(r) >= X and np.sign(r) == np.sign(f["NVDA 개장후"]) == np.sign(f["SOXX 개장후"]) and r != 0:
            by.setdefault(half(d), []).append(trade(d, np.sign(r)))
    allr = [x for v in by.values() for x in v]
    segs = " ".join(f"{k} {np.mean(v):+.2f}({len(v)})" for k, v in sorted(by.items()))
    print(f"  X={X}%: {len(allr)}회 평균 {np.mean(allr):+.2f}% 승률 {np.mean([x>0 for x in allr])*100:.0f}% | {segs}")
print("반대(되돌림) 기준 비교: 같은 조건에서 반대로 사면")
for X in (3,):
    rr = [trade(d, -np.sign(f["개장후 흐름"])) for d, f, lab in rows if abs(f["개장후 흐름"]) >= X and np.sign(f["개장후 흐름"]) == np.sign(f["NVDA 개장후"]) == np.sign(f["SOXX 개장후"])]
    print(f"  X={X}% 되돌림: {len(rr)}회 평균 {np.mean(rr):+.2f}%")
# 회귀 확신 70% 반기별
br = [r for r in rows if r[2] != 0]
res = logit_walk(br, list(br[0][1]), 150)
by = {}
for (d, f, lab), (p, y) in zip(br[150:], res):
    if p >= .7 or p <= .3: by.setdefault(half(d), []).append(trade(d, 1 if p > .5 else -1))
print("회귀 확신 70%↑ 반기별:", " ".join(f"{k} {np.mean(v):+.2f}({len(v)})" for k, v in sorted(by.items())))
