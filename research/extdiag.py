"""시간외 진단: 거래량, 움직임 폭, 5분 수익률의 이어짐(자기상관), 급변 뒤 평균 움직임 (비용 전)."""
import json, datetime, zoneinfo, statistics, math, sys
ET = zoneinfo.ZoneInfo("America/New_York")
SESS = {"프리": (240, 570), "정규": (570, 960), "애프터": (960, 1200)}


def load(s):
    days = {}
    for t, o, h, l, c, v in json.load(open(f"data5x/{s}_5m.json")):
        dt = datetime.datetime.fromtimestamp(t, ET)
        days.setdefault(dt.date(), {})[dt.hour * 60 + dt.minute] = (o, h, l, c, v)
    return days


def series(days, a, b):
    """세션별 하루 5분봉 리스트 [(minute, o,h,l,c,v)]"""
    out = {}
    for d, m in days.items():
        rows = [(k, *m[k]) for k in sorted(m) if a <= k < b]
        if len(rows) >= (b - a) // 5 * 0.6:
            out[d] = rows
    return out


def corr(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0


for sym in sys.argv[1].split(","):
    days = load(sym)
    _r = series(days, 570, 960)
    regvol = statistics.mean(r[5] for rows in _r.values() for r in rows) or None
    print(f"\n■ {sym}")
    print(f"  {'시간대':5s} {'일수':>3s} {'5분 거래량':>10s} {'15분 평균폭':>9s} {'30분':>6s} {'60분':>6s} | {'5분→다음5분 상관':>14s} {'15분→다음15분':>12s} | 급변(2σ) 뒤 30분 (같은방향 +)")
    for name, (a, b) in SESS.items():
        ser = series(days, a, b)
        vol = statistics.mean(r[5] for rows in ser.values() for r in rows)
        if name == "정규":
            regvol = vol
        moves = {}
        for k in (3, 6, 12):
            mv = []
            for rows in ser.values():
                cl = [r[4] for r in rows]
                mv += [abs(cl[i + k] / cl[i] - 1) * 100 for i in range(0, len(cl) - k, k)]
            moves[k] = statistics.mean(mv)
        r5x, r5y, r15x, r15y, ev = [], [], [], [], []
        all5 = []
        for rows in ser.values():
            cl = [r[4] for r in rows]
            rets = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl))]
            all5 += rets
            r5x += rets[:-1]; r5y += rets[1:]
            c15 = cl[::3]
            q = [c15[i] / c15[i - 1] - 1 for i in range(1, len(c15))]
            r15x += q[:-1]; r15y += q[1:]
        sd = statistics.pstdev(all5)
        for rows in ser.values():
            cl = [r[4] for r in rows]
            for i in range(1, len(cl) - 6):
                r = cl[i] / cl[i - 1] - 1
                if abs(r) > 2 * sd:
                    ev.append(math.copysign(1, r) * (cl[i + 6] / cl[i] - 1) * 100)
        c5, c15 = corr(r5x, r5y), corr(r15x, r15y)
        evm = statistics.mean(ev) if ev else 0
        evt = evm / (statistics.pstdev(ev) / math.sqrt(len(ev))) if len(ev) > 2 and statistics.pstdev(ev) else 0
        print(f"  {name:5s} {len(ser):3d} {(f"{vol / regvol * 100:.0f}%" if regvol and vol else "정보없음"):>10s} {moves[3]:8.2f}% {moves[6]:5.2f}% {moves[12]:5.2f}% |"
              f" {c5:+.3f} (t {c5 * math.sqrt(len(r5x)):+.1f}) {c15:+.3f} (t {c15 * math.sqrt(len(r15x)):+.1f}) |"
              f" {len(ev):3d}번 평균 {evm:+.2f}% (t {evt:+.1f})")
