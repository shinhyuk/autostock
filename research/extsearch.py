"""시간외 단타 계열 탐색: 9~10월로 고르고 11월로 검증. 5분봉(시간외 포함) 59일.
수수료 편도 0.25% + 슬리피지 편도 0.1%. '비용 전' 결과도 같이 본다."""
import json, datetime, zoneinfo, itertools, statistics, sys
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, SLIP = 0.0025, 0.001
BULL, BEAR, LEAD = (sys.argv[1:4] if len(sys.argv) > 3 else ("SOXL", "SOXS", "NVDA"))


def load(s):
    days = {}
    for t, o, h, l, c, v in json.load(open(f"data5x/{s}_5m.json")):
        dt = datetime.datetime.fromtimestamp(t, ET)
        days.setdefault(dt.date(), {})[dt.hour * 60 + dt.minute] = (o, h, l, c)
    return days


L, S, N = load(BULL), load(BEAR), load(LEAD)
dates = sorted(d for d in L if d in S and len(L[d]) > 150)


def px(src, d, m, kind="c"):
    mm = src.get(d, {})
    if kind == "c":
        ks = [k for k in mm if m - 15 <= k <= m]
        return mm[max(ks)][3] if ks else None
    ks = [k for k in mm if m <= k <= m + 10]
    return mm[min(ks)][0] if ks else None


def trade(d, side, m_in, m_out, stop=None, take=None):
    """m_in 봉 시가에 사서 m_out 봉 종가에 판다. stop/take(%)는 보유 종목 봉 고가·저가로 판정."""
    src = L if side > 0 else S
    b = px(src, d, m_in, "o")
    if not b:
        return None
    out = px(src, d, m_out)
    for m in range(m_in, m_out + 1, 5):
        bar = src.get(d, {}).get(m)
        if not bar:
            continue
        if stop and bar[2] <= b * (1 - stop / 100):
            out = min(bar[0], b * (1 - stop / 100)); break
        if take and bar[1] >= b * (1 + take / 100):
            out = max(bar[0], b * (1 + take / 100)); break
    if not out:
        return None
    gross = out / b - 1
    bb, ee = b * (1 + SLIP), out * (1 - SLIP)
    return gross, (ee / bb - 1) - FEE * (1 + ee / bb)


def run(rule):
    res = []
    for d in dates:
        for t in rule(d):
            r = trade(d, *t)
            if r:
                res.append((d, *r))
    return res


def sess(name):
    return (240, 565) if name == "프리" else (960, 1190)


def r_spike(sname, k, hold, mode):
    a, b = sess(sname)
    sd = {}
    def rule(d):
        out, last = [], -999
        cl = [(m, L[d][m][3]) for m in sorted(L.get(d, {})) if a <= m < b]
        rets = [cl[i][1] / cl[i - 1][1] - 1 for i in range(1, len(cl))]
        if len(rets) < 20:
            return out
        s = statistics.pstdev(rets) or 1
        for i in range(1, len(cl) - hold // 5 - 1):
            r = cl[i][1] / cl[i - 1][1] - 1
            if abs(r) > k * s and cl[i][0] - last > hold:
                side = (1 if r > 0 else -1) * (1 if mode == "추종" else -1)
                m_in = cl[i][0] + 5
                out.append((side, m_in, min(m_in + hold - 5, b)))
                last = m_in + hold
        return out
    return rule


def r_prebreak(t0, x, mode, stop):
    def rule(d):
        mm = L.get(d, {})
        pre = [mm[m] for m in sorted(mm) if 240 <= m < t0]
        if len(pre) < 10:
            return []
        hi, lo = max(p[1] for p in pre), min(p[2] for p in pre)
        for m in sorted(mm):
            if t0 <= m < 555:
                c = mm[m][3]
                sg = 1 if c > hi * (1 + x / 100) else -1 if c < lo * (1 - x / 100) else 0
                if sg:
                    return [((sg if mode == "추종" else -sg), m + 5, 560, stop, None)]
        return []
    return rule


def r_window(t0, t1, th, mode, x_out):
    """t0~t1 구간 움직임이 th% 넘으면 그 방향(추종) 또는 반대(되돌림)로 t1+5 진입, x_out 청산."""
    def rule(d):
        a, b = px(L, d, t0), px(L, d, t1)
        if not a or not b or abs(b / a - 1) * 100 < th:
            return []
        sg = (1 if b > a else -1) * (1 if mode == "추종" else -1)
        return [(sg, t1 + 5, x_out)]
    return rule


def r_lead(sname, x, hold):
    a, b = sess(sname)
    def rule(d):
        out, last = [], -999
        for m in range(a + 5, b - hold, 5):
            n0, n1, l0, l1 = px(N, d, m - 5), px(N, d, m), px(L, d, m - 5), px(L, d, m)
            if not all((n0, n1, l0, l1)) or m - last < hold:
                continue
            rn, rl = (n1 / n0 - 1) * 100, (l1 / l0 - 1) * 100
            if abs(rn) >= x and abs(rl) < abs(rn):                 # 선행 종목이 움직였는데 아직 덜 따라옴
                out.append((1 if rn > 0 else -1, m + 5, m + hold))
                last = m + hold
        return out
    return rule


def r_ema(sname, f, s_, hold):
    a, b = sess(sname)
    def rule(d):
        cl = [(m, L[d][m][3]) for m in sorted(L.get(d, {})) if a <= m < b]
        if len(cl) < s_ + 2:
            return []
        def ema(xs, n):
            k, e, r = 2 / (n + 1), xs[0], []
            for v in xs:
                e = v * k + e * (1 - k); r.append(e)
            return r
        p = [c for _, c in cl]
        ef, es = ema(p, f), ema(p, s_)
        out, last = [], -999
        for i in range(s_, len(cl) - 1):
            cross = (ef[i] - es[i]) * (ef[i - 1] - es[i - 1]) < 0
            if cross and cl[i][0] - last > hold:
                out.append((1 if ef[i] > es[i] else -1, cl[i][0] + 5, min(cl[i][0] + hold, b)))
                last = cl[i][0] + hold
        return out
    return rule


cands = []
for sname, k, hold, mode in itertools.product(("프리", "애프터"), (2, 3), (15, 30, 60), ("추종", "되돌림")):
    cands.append((f"급변 {k}σ {mode} {hold}분 ({sname})", r_spike(sname, k, hold, mode)))
for t0, x, mode, stop in itertools.product((420, 480, 510), (0, 0.5), ("추종", "되돌림"), (None, 2)):
    cands.append((f"프리 {t0//60:02d}:{t0%60:02d}부터 프리 고저 돌파{x}% {mode} 손절{stop}", r_prebreak(t0, x, mode, stop)))
for (t0, t1, xo, lab), th, mode in itertools.product(
        ((510, 515, 560, "08:30 발표 5분"), (510, 540, 560, "08:30~09:00"), (240, 300, 560, "04:00~05:00"),
         (960, 975, 1020, "애프터 첫 15분→17:00"), (960, 990, 1185, "애프터 첫 30분→19:45"), (930, 955, 1020, "정규 마지막 25분→17:00")),
        (0.5, 1, 2), ("추종", "되돌림")):
    cands.append((f"{lab} {th}%↑ {mode}", r_window(t0, t1, th, mode, xo)))
for sname, x, hold in itertools.product(("프리", "애프터"), (0.3, 0.5, 1.0), (15, 30)):
    cands.append((f"{LEAD} 선행 {x}% → {hold}분 ({sname})", r_lead(sname, x, hold)))
for sname, (f, s_), hold in itertools.product(("프리", "애프터"), ((3, 8), (5, 15)), (30, 60)):
    cands.append((f"EMA{f}/{s_} 교차 {hold}분 ({sname})", r_ema(sname, f, s_, hold)))

rows = []
for name, rule in cands:
    res = run(rule)
    if len(res) < 6:
        continue
    tr = [x for x in res if x[0].month in (8, 9, 10)]; te = [x for x in res if x[0].month == 11]
    f = lambda xs, i: sum(x[i] for x in xs) * 100                # noqa: E731
    rows.append((name, len(tr), f(tr, 2), f(tr, 1), len(te), f(te, 2), f(te, 1),
                 sum(1 for x in res if x[2] > 0) / len(res) * 100))
print(f"{BULL}/{BEAR} (선행 {LEAD}) — 후보 {len(rows)}개")
print(f"  9~10월 이익: {sum(1 for r in rows if r[2] > 0)}개 / 11월 이익: {sum(1 for r in rows if r[5] > 0)}개 / 둘 다: {sum(1 for r in rows if r[2] > 0 and r[5] > 0)}개")
print(f"  비용 전 기준 9~10월 이익: {sum(1 for r in rows if r[3] > 0)}개 / 둘 다: {sum(1 for r in rows if r[3] > 0 and r[6] > 0)}개")
print(f"\n  9~10월 성적 상위 8개를 11월에 적용 (비용 후, 괄호는 비용 전):")
print(f"  {'후보':42s} {'9~10월':>14s} {'11월':>15s} {'승률':>5s}")
for r in sorted(rows, key=lambda r: -r[2])[:8]:
    print(f"  {r[0]:42s} {r[2]:+6.1f}% ({r[3]:+5.1f}) {r[1]:2d}회 | {r[5]:+6.1f}% ({r[6]:+5.1f}) {r[4]:2d}회 {r[7]:4.0f}%")
