import runpy, io, contextlib, math, numpy as np
buf = io.StringIO()
with contextlib.redirect_stdout(buf): g = runpy.run_path("code/breakdir.py")
build, logit_walk, ci, load = g["build"], g["logit_walk"], g["ci"], g["load"]
COST = 0.6
for name, tf, rng_end, step, warm in (("A) 5분봉 60일", "5m", 590, 5, 25), ("B) 1시간봉 2년", "60m", 630, 60, 150)):
    rows = build(tf, rng_end, step); br = [r for r in rows if r[2] != 0]
    rw = np.mean([max(r[1]["범위 안 위치"] + .5, .5 - r[1]["범위 안 위치"]) for r in br])
    print(f"\n{name}: '범위 안 위치'가 무작위로도 맞힐 기대 정확도 {rw*100:.0f}%")
    other = [k for k in br[0][1] if k not in ("범위 안 위치", "개장후 흐름")]
    res = logit_walk(br, other, warm)
    acc = sum((p > .5) == (y == 1) for p, y in res)
    print(f"  SOXL 자기 위치·흐름 빼고(갭·전날·프리·NVDA·SOXX·QQQ) 회귀: {ci(acc, len(res))} · 기준(많은 쪽) {ci(max(sum(y for _,y in res), len(res)-sum(y for _,y in res)), len(res))}")
    # 매매로 확인: 범위 확정 시점에 회귀가 고른 방향으로 진입 → 장 마감 청산 (SOXL 기준 %, 비용 0.6%)
    B = load("SOXL", tf)
    full = logit_walk(br, list(br[0][1]), warm)
    days = br[warm:]
    for th in (0.5, 0.6, 0.7):
        rets, brk_agree, brk_dis = [], [], []
        for (d, f, lab), (p, y) in zip(days, full):
            L = B[d]; ks = sorted(k for k in L if 570 <= k < 960)
            ent = L[max(k for k in ks if k < rng_end)][3]; ex = L[ks[-1]][3]
            if p >= th or p <= 1 - th:
                sd = 1 if p > .5 else -1
                rets.append(sd * (ex / ent - 1) * 100 * 3 / 3 - COST)
        if rets:
            print(f"  확신 {th:.0%}↑ 방향으로 범위 확정 때 진입→마감: {len(rets)}회 평균 {np.mean(rets):+.2f}% 승률 {np.mean([r>0 for r in rets])*100:.0f}%")
    # 돌파 매매(첫 이탈 방향으로 진입 → 마감)를 회귀와 같은 쪽/다른 쪽으로 나눔
    ag, dis = [], []
    for (d, f, lab), (p, y) in zip(days, full):
        L = B[d]; ks = sorted(k for k in L if 570 <= k < 960)
        rk = [k for k in ks if k < rng_end]; hh, ll = max(L[k][1] for k in rk), min(L[k][2] for k in rk)
        for k in ks:
            if k >= rng_end and (L[k][3] > hh or L[k][3] < ll):
                sd = 1 if L[k][3] > hh else -1
                r = sd * (L[ks[-1]][3] / L[k][3] - 1) * 100 - COST
                ((ag if (p > .5) == (sd > 0) else dis)).append(r); break
    print(f"  돌파 매매(이탈 방향 진입→마감): 회귀와 같은 쪽 {len(ag)}회 평균 {np.mean(ag):+.2f}% · 반대쪽 {len(dis)}회 평균 {np.mean(dis):+.2f}%")
