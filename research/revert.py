"""개장 직후 쏠림 뒤 되돌림 / 가짜 돌파 반대 매매. SOXL 가격 기준 %(SOXS 는 반대로 어림), 비용 왕복 0.6%."""
import json, datetime, zoneinfo, statistics as S, math, sys
ET = zoneinfo.ZoneInfo("America/New_York")
def days_of(path, step):
    d = {}
    for r in json.load(open(path)):
        t = datetime.datetime.fromtimestamp(r[0], ET); m = t.hour * 60 + t.minute
        if 570 <= m < 960: d.setdefault(t.date(), []).append((m, *r[1:5]))
    return {k: sorted(v) for k, v in d.items() if len(v) >= (390 // step) * 0.8}
def sim_fade(D, T, th, stop, target):
    """T분에 시가 대비 th% 넘게 움직였으면 반대로: 목표 = 시가까지 되돌림의 target 비율, 손절 = 그날 극단 너머 stop%."""
    out = []
    for d, b in D.items():
        o = b[0][1]; pre = [x for x in b if x[0] < 570 + T]; post = [x for x in b if x[0] >= 570 + T]
        if not pre or not post: continue
        p = pre[-1][4]; mv = (p / o - 1) * 100
        if abs(mv) < th: continue
        sd = 1 if mv < 0 else -1                      # 빠졌으면 SOXL, 올랐으면 SOXS
        ext = min(x[3] for x in pre) if sd > 0 else max(x[2] for x in pre)
        stp = ext * (1 - stop / 100) if sd > 0 else ext * (1 + stop / 100)
        tgt = p + (o - p) * target
        r = None
        for x in post:
            if (sd > 0 and x[3] <= stp) or (sd < 0 and x[2] >= stp): r = sd * (stp / p - 1) * 100; break
            if (sd > 0 and x[2] >= tgt) or (sd < 0 and x[3] <= tgt): r = sd * (tgt / p - 1) * 100; break
        if r is None: r = sd * (post[-1][4] / p - 1) * 100
        out.append((d, r - 0.6))
    return out
def sim_fail(D, step, rng_min=20, back=3):
    """20분 범위를 종가로 뚫었다가 back 봉 안에 다시 범위 안으로 들어오면 반대 방향: 목표 반대 경계, 손절 돌파 극단."""
    out = []
    n = rng_min // step
    for d, b in D.items():
        hh = max(x[2] for x in b[:n]); ll = min(x[3] for x in b[:n])
        for i in range(n, len(b)):
            c = b[i][4]
            if c > hh or c < ll:
                up = c > hh; ext = b[i][2] if up else b[i][3]
                for j in range(i + 1, min(i + 1 + back, len(b))):
                    ext = max(ext, b[j][2]) if up else min(ext, b[j][3])
                    if ll <= b[j][4] <= hh:
                        sd = -1 if up else 1; p = b[j][4]; tgt = ll if up else hh; stp = ext
                        r = None
                        for x in b[j + 1:]:
                            if (sd > 0 and x[3] <= stp) or (sd < 0 and x[2] >= stp): r = sd * (stp / p - 1) * 100; break
                            if (sd > 0 and x[2] >= tgt) or (sd < 0 and x[3] <= tgt): r = sd * (tgt / p - 1) * 100; break
                        if r is None: r = sd * (b[-1][4] / p - 1) * 100
                        out.append((d, r - 0.6)); break
                break
    return out
def show(name, rs, mid):
    if len(rs) < 5: print(f"  {name:42s} {len(rs)}회"); return
    r = [x for _, x in rs]; a = [x for d, x in rs if d < mid]; b = [x for d, x in rs if d >= mid]
    t = S.mean(r) / (S.pstdev(r) / math.sqrt(len(r))) if S.pstdev(r) else 0
    f = lambda v: f"{S.mean(v):+.2f}({len(v)})" if v else "-"
    print(f"  {name:42s} {len(r):3d}회 평균 {S.mean(r):+.2f}% 승률 {sum(x>0 for x in r)/len(r)*100:3.0f}% t{t:+.1f} 합 {sum(r):+.0f}% | 앞 {f(a)} 뒤 {f(b)}")
for label, path, step in (("1분봉 22일", "data_nov23/SOXL_1m.json", 1), ("5분봉 60일", "fresh/SOXL_5m.json", 5)):
    D = days_of(path, step); ks = sorted(D); mid = ks[len(ks) // 2]
    print(f"\n{label} ({ks[0]}~{ks[-1]}, {len(ks)}일)")
    for T in (15, 30, 60):
        for th in (3, 5, 8):
            for tg in (0.5, 1.0):
                show(f"개장 {T}분 {th}%↑ 쏠림 → 반대, 목표 되돌림 {int(tg*100)}%", sim_fade(D, T, th, 2, tg), mid)
    show("가짜 돌파(3봉 안 복귀) → 반대, 목표 반대 경계", sim_fail(D, step, 20, max(1, 3 // step) if step > 1 else 3), mid)
