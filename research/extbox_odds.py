"""시간외 박스 위치별로 '위로 먼저 / 아래로 먼저' 확률. 5분봉(시간외 포함) 59일."""
import json, datetime, zoneinfo, sys, statistics
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, SLIP = 0.25, 0.1
L = int(sys.argv[1]) if len(sys.argv) > 1 else 60       # 박스 기간(분)
ZF = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25  # 위·아래 구간 비율
H = int(sys.argv[3]) if len(sys.argv) > 3 else 60       # 최대 보유(분)
MODE = sys.argv[4] if len(sys.argv) > 4 else "half"     # 목표/손절 폭: half=박스폭/2, fix=1%

def load(s):
    return {t: (o, h, l, c) for t, o, h, l, c, v in json.load(open(f"data5x/{s}_5m.json"))}
A, B = load("SOXL"), load("SOXS")
ts = sorted(t for t in A if t in B)
def sess(t):
    d = datetime.datetime.fromtimestamp(t, ET); m = d.hour * 60 + d.minute
    if 240 <= m < 570: return "pre", d.date(), datetime.datetime.combine(d.date(), datetime.time(9, 30), ET).timestamp()
    if 960 <= m < 1200: return "post", d.date(), datetime.datetime.combine(d.date(), datetime.time(20, 0), ET).timestamp()
    return None, d.date(), None
def zone(p, hi, lo):
    w = hi - lo
    if p > hi: return "above"
    if p < lo: return "below"
    if p >= hi - ZF * w: return "top"
    if p <= lo + ZF * w: return "bottom"
    return "mid"
def run(D, i, tp, sp, end):
    """D 종목을 ts[i] 종가에 사서 +tp% / -sp% 중 먼저 닿는 쪽. 같은 봉이면 손절."""
    e = D[ts[i]][3] * (1 + SLIP / 100)
    for j in range(i + 1, len(ts)):
        t = ts[j]
        if t >= end or t - ts[i] > H * 60: break
        o, h, l, c = D[t]
        if l <= e * (1 - sp / 100): return -sp - SLIP - 2 * FEE, 0
        if h >= e * (1 + tp / 100): return tp - SLIP - 2 * FEE, 1
        last = c
    else:
        last = D[ts[min(j, len(ts) - 1)]][3]
    c = D[ts[j - 1]][3] if j > i + 1 else e
    return (c / e - 1) * 100 - SLIP - 2 * FEE, 0.5
res = {}
prevz = {}
for i, t in enumerate(ts):
    s, day, end = sess(t)
    if not s: continue
    win = [ts[k] for k in range(max(0, i - L // 5 - 2), i) if t - L * 60 <= ts[k] < t]
    if len(win) < L // 5 * 0.8: continue
    if max(b - a for a, b in zip(win + [t], (win + [t])[1:])) > 600: continue
    hi, lo = max(A[k][1] for k in win), min(A[k][2] for k in win)
    p = A[t][3]
    w = (hi - lo) / p * 100
    if w < 0.4: continue
    z = zone(p, hi, lo)
    key = (s, day)
    if prevz.get(key) == z: continue       # 같은 구간에 머무는 동안은 처음 한 번만
    prevz[key] = z
    tp = sp = min(max(w / 2, 0.6), 3.0) if MODE == "half" else 1.0
    if t + 600 > end: continue
    rl, wl = run(A, i, tp, sp, end)
    rs, ws = run(B, i, tp, sp, end)
    per = "train" if day.month in (9, 10) else "test"
    res.setdefault((s, z), []).append((per, rl, wl, rs, ws, w))
print(f"박스 {L}분, 구간 {ZF}, 보유 {H}분, 목표/손절 {MODE}")
print(f"{'':5s} {'위치':6s} {'n':>4s} {'폭':>5s} | {'SOXL 목표먼저':>12s} {'SOXL 평균':>9s} | {'SOXS 목표먼저':>12s} {'SOXS 평균':>9s} | 9~10월 L/S  · 11월 L/S")
for s in ("pre", "post"):
    for z in ("above", "top", "mid", "bottom", "below"):
        r = res.get((s, z), [])
        if not r: continue
        n = len(r)
        f = lambda rows, k: statistics.mean(x[k] for x in rows) if rows else float('nan')
        wr = lambda rows, k: sum(1 for x in rows if x[k] == 1) / len(rows) * 100 if rows else float('nan')
        tr = [x for x in r if x[0] == "train"]; te = [x for x in r if x[0] == "test"]
        print(f"{s:5s} {z:6s} {n:4d} {f(r,5):4.1f}% | {wr(r,2):11.0f}% {f(r,1):+8.2f}% | {wr(r,4):11.0f}% {f(r,3):+8.2f}% | "
              f"{wr(tr,2):3.0f}/{wr(tr,4):3.0f}% ({len(tr)}) · {wr(te,2):3.0f}/{wr(te,4):3.0f}% ({len(te)})")
