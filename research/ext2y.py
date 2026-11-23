"""후보 규칙을 2년 1시간봉(시간외 포함)으로 다시 확인. 반기별 1회 평균(수수료·슬리피지 뺀 값)."""
import json, datetime, zoneinfo, statistics, itertools
ET = zoneinfo.ZoneInfo("America/New_York")
def load(s):
    d = {}
    for t, o, h, l, c in json.load(open(f"data60/{s}.json")):
        x = datetime.datetime.fromtimestamp(t, ET); d.setdefault(x.date(), {})[(x.hour, x.minute)] = (o, h, l, c)
    return d
L, S = load("SOXL"), load("SOXS")
days = sorted(d for d in L if d in S and (9, 30) in L[d] and (15, 30) in L[d])
FEE = 0.25
def tr(sd, d1, k1, i1, d2, k2, i2, sl):
    D = L if sd > 0 else S
    try: a, b = D[d1][k1][i1], D[d2][k2][i2]
    except KeyError: return None
    return (b / a - 1) * 100 - 2 * FEE - sl
def half(d): return f"{d.year}{'상' if d.month <= 6 else '하'}"
def show(name, fn):
    rs = []
    for i, d in enumerate(days[1:], 1):
        r = fn(days[i - 1], d, days[i + 1] if i + 1 < len(days) else None)
        if r is not None: rs.append((d, r))
    by = {}
    for d, r in rs: by.setdefault(half(d), []).append(r)
    segs = " ".join(f"{k} {statistics.mean(v):+.2f}({len(v)})" for k, v in sorted(by.items()))
    allr = [r for _, r in rs]
    print(f"{name:42s} {len(allr):3d}회 평균 {statistics.mean(allr):+.2f}% 승률 {sum(r > 0 for r in allr) / len(allr) * 100:.0f}% | {segs}")
print(f"{days[0]}~{days[-1]} {len(days)}일")
for th in (1, 2, 3):
    def f(p, d, n, th=th):
        try: g = (L[d][(6, 0)][0] / L[p][(15, 30)][3] - 1) * 100
        except KeyError: return None
        if abs(g) < th: return None
        return tr(1 if g > 0 else -1, d, (6, 0), 0, d, (9, 0), 3, 0.15)
    show(f"프리 06:00 갭 {th}%↑ 추종 → 09:30", f)
for T in (6, 7, 8):
    for th in (1, 2):
        def f(p, d, n, T=T, th=th):
            try: g = (L[d][(T, 0)][0] / L[d][(4, 0)][0] - 1) * 100
            except KeyError: return None
            if abs(g) < th: return None
            return tr(1 if g > 0 else -1, d, (T, 0), 0, d, (9, 0), 3, 0.15)
        show(f"프리 04:00→{T:02d}:00 {th}%↑ 추종 → 09:30", f)
for th in (2, 4, 6):
    for ex in ("open", "10:30"):
        def f(p, d, n, th=th, ex=ex):
            if not n: return None
            g = (L[d][(15, 30)][3] / L[d][(9, 30)][0] - 1) * 100
            if abs(g) < th: return None
            return tr(1 if g > 0 else -1, d, (16, 0), 0, n, (9, 30), 0 if ex == "open" else 3, 0.15)
        show(f"정규장 {th}%↑ 날 추종 16:00 → 다음 {ex}", f)
for sd in (1, -1):
    show(f"항상 {'SOXL' if sd > 0 else 'SOXS'} 06:00 → 09:30", lambda p, d, n, sd=sd: tr(sd, d, (6, 0), 0, d, (9, 0), 3, 0.2))
