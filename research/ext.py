"""프리마켓·애프터마켓 전용 전략 탐색 (1분봉 20일, 시간외 포함). 수수료 편도 0.25%, 슬리피지 편도 SLIP."""
import sys, json, datetime, zoneinfo, itertools, statistics
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, CAP = 0.0025, 10_000_000 / 1400
SLIP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.001
D = sys.argv[1]
raw = {s: {t: v for t, *v in json.load(open(f"{D}/{s}_1m.json"))} for s in ("SOXL", "SOXS", "NVDA")}
days = {}
for s, m in raw.items():
    for t, v in m.items():
        dt = datetime.datetime.fromtimestamp(t, ET)
        days.setdefault(dt.date(), {}).setdefault(s, {})[dt.hour * 60 + dt.minute] = v   # 분 → (o,h,l,c,v)
dates = sorted(d for d in days if len(days[d].get("SOXL", {})) > 500)


def px(d, s, minute, kind="c"):
    """그 분까지 마지막 체결가(c) 또는 그 분 이후 첫 봉 시가(o)."""
    m = days[d].get(s, {})
    if kind == "c":
        ks = [k for k in m if k <= minute and k >= minute - 30]
        return m[max(ks)][3] if ks else None
    ks = [k for k in m if minute <= k <= minute + 10]
    return m[min(ks)][0] if ks else None


def rt(buy, sell):
    b, s = buy * (1 + SLIP), sell * (1 - SLIP)
    return (s / b - 1) - FEE * (1 + s / b)            # 수익률 (수수료 포함)


def M(h, m): return h * 60 + m


def report(name, trades):
    if len(trades) < 4:
        return None
    r = [x[1] for x in trades]
    half = len(trades) // 2
    a, b = sum(r[:half]), sum(r[half:])
    return (name, len(r), sum(1 for x in r if x > 0) / len(r) * 100, statistics.mean(r) * 100, sum(r) * 100, a * 100, b * 100)


rows = []
for i, d in enumerate(dates):
    pass
prev = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

# A. 프리마켓 갭 추종/되돌림: T 시점 전날 종가 대비 수익률이 ±th 넘으면 그 방향(또는 반대)으로 사서 09:25 청산
for T, th, mode in itertools.product((M(4, 30), M(6, 0), M(7, 0), M(8, 0), M(8, 30)), (1, 2, 4), ("추종", "되돌림")):
    tr = []
    for d in dates[1:]:
        pc = px(prev[d], "SOXL", M(15, 59))
        p = px(d, "SOXL", T)
        if not pc or not p:
            continue
        g = (p / pc - 1) * 100
        if abs(g) < th:
            continue
        up = (g > 0) == (mode == "추종")
        s = "SOXL" if up else "SOXS"
        b, e = px(d, s, T + 1, "o"), px(d, s, M(9, 25))
        if b and e:
            tr.append((d, rt(b, e)))
    rows.append(report(f"A 프리 {T//60:02d}:{T%60:02d} 갭{th}%↑ {mode}→09:25", tr))

# B. 애프터마켓: 정규장 마지막 30분(15:30→16:00) 방향 추종/되돌림, 16:01 진입 → X 청산
for X, th, mode in itertools.product((M(17, 0), M(18, 0), M(19, 50)), (0.5, 1, 2), ("추종", "되돌림")):
    tr = []
    for d in dates:
        a, c = px(d, "SOXL", M(15, 30)), px(d, "SOXL", M(15, 59))
        if not a or not c:
            continue
        g = (c / a - 1) * 100
        if abs(g) < th:
            continue
        up = (g > 0) == (mode == "추종")
        s = "SOXL" if up else "SOXS"
        b, e = px(d, s, M(16, 1), "o"), px(d, s, X)
        if b and e:
            tr.append((d, rt(b, e)))
    rows.append(report(f"B 애프터 마지막30분 {th}%↑ {mode}→{X//60}:{X%60:02d}", tr))

# C. 하루 전체(시가→종가) 방향으로 애프터 16:01 진입 → X 청산
for X, th, mode in itertools.product((M(17, 0), M(19, 50)), (2, 5, 10), ("추종", "되돌림")):
    tr = []
    for d in dates:
        o, c = px(d, "SOXL", M(9, 30), "o"), px(d, "SOXL", M(15, 59))
        if not o or not c:
            continue
        g = (c / o - 1) * 100
        if abs(g) < th:
            continue
        up = (g > 0) == (mode == "추종")
        s = "SOXL" if up else "SOXS"
        b, e = px(d, s, M(16, 1), "o"), px(d, s, X)
        if b and e:
            tr.append((d, rt(b, e)))
    rows.append(report(f"C 애프터 당일 {th}%↑ {mode}→{X//60}:{X%60:02d}", tr))

# D. 밤새 보유: 애프터 19:45 에 당일 방향(추종/되돌림)으로 사서 다음 날 프리 04:30 / 08:00 / 09:25 청산
nxt = {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}
for Y, th, mode in itertools.product((M(4, 30), M(8, 0), M(9, 25)), (0, 3, 6), ("추종", "되돌림")):
    tr = []
    for d in dates[:-1]:
        o, c = px(d, "SOXL", M(9, 30), "o"), px(d, "SOXL", M(19, 45))
        if not o or not c:
            continue
        g = (c / o - 1) * 100
        if abs(g) < th:
            continue
        up = (g > 0) == (mode == "추종")
        s = "SOXL" if up else "SOXS"
        b, e = px(d, s, M(19, 46), "o"), px(nxt[d], s, Y)
        if b and e:
            tr.append((d, rt(b, e)))
    rows.append(report(f"D 밤새 19:45 당일{th}%↑ {mode}→다음날 {Y//60:02d}:{Y%60:02d}", tr))

# E. 엔비디아 선행: 시간외에서 NVDA 3분 수익률이 x% 넘는데 SOXL 은 아직 덜 움직였으면 따라 사고 k분 뒤 청산
for x, k, sess in itertools.product((0.3, 0.6), (5, 15), ("pre", "post")):
    tr = []
    lo_, hi_ = (M(4, 0), M(9, 20)) if sess == "pre" else (M(16, 0), M(19, 40))
    for d in dates:
        last = -999
        for m0 in range(lo_ + 3, hi_ - k):
            if m0 - last < k + 1:
                continue
            n0, n1 = px(d, "NVDA", m0 - 3), px(d, "NVDA", m0)
            l0, l1 = px(d, "SOXL", m0 - 3), px(d, "SOXL", m0)
            if not all((n0, n1, l0, l1)):
                continue
            rn, rl = (n1 / n0 - 1) * 100, (l1 / l0 - 1) * 100
            if abs(rn) >= x and abs(rl) < abs(rn) * 1.5 and (rl * rn >= 0 or abs(rl) < 0.2):
                s = "SOXL" if rn > 0 else "SOXS"
                b, e = px(d, s, m0 + 1, "o"), px(d, s, m0 + k)
                if b and e:
                    tr.append((d, rt(b, e))); last = m0
    rows.append(report(f"E 엔비디아 선행 {'프리' if sess == 'pre' else '애프터'} {x}% → {k}분", tr))

rows = [r for r in rows if r]
rows.sort(key=lambda r: -r[4])
print(f"슬리피지 편도 {SLIP*100:.1f}%  (전략 {len(rows)}개, 거래 4회 이상만)")
print(f"{'전략':46s} {'거래':>4s} {'승률':>5s} {'1회 평균':>8s} {'합계':>7s} {'앞절반':>7s} {'뒤절반':>7s}")
for name, n, w, avg, tot, a, b in rows[:14]:
    print(f"{name:46s} {n:4d} {w:4.0f}% {avg:+7.2f}% {tot:+6.1f}% {a:+6.1f}% {b:+6.1f}%")
print("...")
print(f"합계 이익인 전략 {sum(1 for r in rows if r[4] > 0)}/{len(rows)}, 앞·뒤 절반 모두 이익 {sum(1 for r in rows if r[5] > 0 and r[6] > 0)}, 승률 60% 이상 {sum(1 for r in rows if r[2] >= 60)}")
