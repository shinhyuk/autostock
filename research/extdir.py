"""시간외: 박스 위치(+직전 15분 방향)별로 SOXL 이 +X% 에 먼저 닿을 확률 (−X% 보다). 5분봉 59일, 비용 전."""
import json, datetime, zoneinfo, sys
ET = zoneinfo.ZoneInfo("America/New_York")
L, X, H = int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
A = {t: (o, h, l, c) for t, o, h, l, c, v in json.load(open("data5x/SOXL_5m.json"))}
ts = sorted(A)
def sess(t):
    d = datetime.datetime.fromtimestamp(t, ET); m = d.hour * 60 + d.minute
    if 240 <= m < 570: return "pre", d.date(), datetime.datetime.combine(d.date(), datetime.time(9, 30), ET).timestamp()
    if 960 <= m < 1200: return "post", d.date(), datetime.datetime.combine(d.date(), datetime.time(20, 0), ET).timestamp()
    return None, None, None
def zone(p, hi, lo):
    w = hi - lo
    return "above" if p > hi else "below" if p < lo else "top" if p >= hi - .25 * w else "bottom" if p <= lo + .25 * w else "mid"
R = {}
prev = {}
for i, t in enumerate(ts):
    s, day, end = sess(t)
    if not s: continue
    win = [k for k in ts[max(0, i - L // 5 - 2):i] if t - L * 60 <= k < t]
    if len(win) < L // 5 * .8 or i < 3 or t - ts[i - 3] > 900: continue
    hi, lo = max(A[k][1] for k in win), min(A[k][2] for k in win); p = A[t][3]
    z = zone(p, hi, lo)
    mom = "↑" if p > A[ts[i - 3]][3] else "↓"
    if prev.get((s, day)) == z: continue
    prev[(s, day)] = z
    up = dn = None
    for k in ts[i + 1:]:
        if k >= end or k - t > H * 60: break
        if A[k][2] <= p * (1 - X / 100): dn = 1; break
        if A[k][1] >= p * (1 + X / 100): up = 1; break
    if up is None and dn is None: continue
    per = 0 if day.month in (9, 10) else 1
    for key in ((s, z), (s, z + mom)):
        R.setdefault(key, [[0, 0], [0, 0]])[per][0 if up else 1] += 1
print(f"박스 {L}분 · ±{X}% · {H}분 안에 먼저 닿은 쪽 (같은 봉 두 쪽이면 아래로 셈)")
for s in ("pre", "post"):
    for z in ("above", "top", "mid", "bottom", "below"):
        for k in (z, z + "↑", z + "↓"):
            r = R.get((s, k))
            if not r: continue
            a = r[0][0] + r[1][0]; b = r[0][1] + r[1][1]
            pp = lambda x: f"{x[0] / (x[0] + x[1]) * 100:3.0f}% ({x[0] + x[1]:3d})" if sum(x) else "  -"
            print(f"{s:5s} {k:8s} 위로먼저 {a / (a + b) * 100:3.0f}% (n={a + b:3d}) | 9~10월 {pp(r[0])} · 11월 {pp(r[1])}")
