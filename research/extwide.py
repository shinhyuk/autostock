"""시간외 아이디어 넓게 탐색 (5분봉 59일, 시간외 포함). 실제 보유 종목(SOXL/SOXS) 가격으로 계산.
수수료 편도 0.25%, 슬리피지 시간외 0.1% / 정규장 0.05%. 9/1~10/15 로 고르고 10/16~ 로 확인."""
import json, itertools, statistics
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
FEE = 0.25
def load(s):
    d = {}
    for t, o, h, l, c, v in json.load(open(f"data5x/{s}_5m.json")):
        dt = datetime.fromtimestamp(t, ET); d.setdefault(dt.date(), {})[dt.hour * 60 + dt.minute] = (o, h, l, c)
    return d
L, S, N = load("SOXL"), load("SOXS"), load("NVDA")
days = sorted(d for d in L if d in S and 570 in L[d] and 955 in L[d])
SPLIT = date(2026, 10, 16)
def px(D, d, m, k=3):
    """d 날 m분(동부) 봉 값. 없으면 직전 30분 안의 가장 가까운 봉."""
    for mm in range(m, m - 30, -5):
        if mm in D.get(d, {}): return D[d][mm][k] if k is not None else D[d][mm]
    return None
def slip(m): return 0.05 if 570 <= m < 960 else 0.1
def trade(side, d1, m1, d2, m2):
    D = L if side > 0 else S
    a, b = px(D, d1, m1), px(D, d2, m2)
    if not a or not b: return None
    return (b / a - 1) * 100 - 2 * FEE - slip(m1) - slip(m2)
def nxt(d):
    i = days.index(d); return days[i + 1] if i + 1 < len(days) else None
def prv(d):
    i = days.index(d); return days[i - 1] if i else None
rules = {}
def add(name, fn):
    out = []
    for d in days:
        try: r = fn(d)
        except (TypeError, ZeroDivisionError, KeyError): r = None
        if r is not None: out.append((d, r))
    rules[name] = out
M = lambda h, m=0: h * 60 + m
# A. 프리 갭 추종/되돌림 → 프리 끝 / 정규 개장 직후 청산
for T, th, mode, ex in itertools.product((M(4, 30), M(6), M(7), M(8), M(9)), (1, 2, 3, 4), (1, -1), (M(9, 25), M(9, 35), M(10), M(10, 30))):
    if ex <= T: continue
    def f(d, T=T, th=th, mode=mode, ex=ex):
        p = prv(d); pc = px(L, p, M(15, 55)); g = (px(L, d, T) / pc - 1) * 100
        if abs(g) < th: return None
        return trade(mode * (1 if g > 0 else -1), d, T, d, ex)
    add(f"프리 {T//60:02d}:{T%60:02d} 갭{th}%↑ {'추종' if mode > 0 else '되돌림'} → {ex//60:02d}:{ex%60:02d}", f)
# B. 프리 흐름(04:00→T) 추종/되돌림
for T, th, mode, ex in itertools.product((M(6), M(7), M(8), M(8, 30), M(9)), (1, 2, 3), (1, -1), (M(9, 25), M(9, 45), M(10, 30))):
    def f(d, T=T, th=th, mode=mode, ex=ex):
        g = (px(L, d, T) / px(L, d, M(4)) - 1) * 100
        if abs(g) < th: return None
        return trade(mode * (1 if g > 0 else -1), d, T, d, ex)
    add(f"프리 04:00→{T//60:02d}:{T%60:02d} {th}%↑ {'추종' if mode > 0 else '되돌림'} → {ex//60:02d}:{ex%60:02d}", f)
# C. 정규장 하루 흐름 → 애프터 진입, 애프터/다음 날 청산
for th, mode, ex in itertools.product((2, 4, 6), (1, -1), ("17:00", "19:55", "next04:30", "next09:35", "next10:00")):
    def f(d, th=th, mode=mode, ex=ex):
        g = (px(L, d, M(15, 55)) / L[d][570][0] - 1) * 100
        if abs(g) < th: return None
        sd = mode * (1 if g > 0 else -1)
        if ex.startswith("next"):
            n = nxt(d); hh, mm = map(int, ex[4:].split(":")); return trade(sd, d, M(16, 5), n, M(hh, mm)) if n else None
        hh, mm = map(int, ex.split(":")); return trade(sd, d, M(16, 5), d, M(hh, mm))
    add(f"정규장 {th}%↑ 움직인 날 {'추종' if mode > 0 else '되돌림'} 16:05 → {ex}", f)
# D. 애프터 첫 30·60분 흐름 → 추종/되돌림
for T, th, mode, ex in itertools.product((M(16, 30), M(17)), (1, 2, 3), (1, -1), ("19:55", "next09:35")):
    def f(d, T=T, th=th, mode=mode, ex=ex):
        g = (px(L, d, T) / px(L, d, M(15, 55)) - 1) * 100
        if abs(g) < th: return None
        sd = mode * (1 if g > 0 else -1)
        if ex == "next09:35":
            n = nxt(d); return trade(sd, d, T, n, M(9, 35)) if n else None
        return trade(sd, d, T, d, M(19, 55))
    add(f"애프터 16:00→{T//60:02d}:{T%60:02d} {th}%↑ {'추종' if mode > 0 else '되돌림'} → {ex}", f)
# E. 엔비디아 애프터 움직임 선행
for th, mode, ex in itertools.product((1, 2, 4), (1, -1), ("19:55", "next09:35")):
    def f(d, th=th, mode=mode, ex=ex):
        g = (px(N, d, M(16, 30)) / px(N, d, M(15, 55)) - 1) * 100
        if abs(g) < th: return None
        sd = mode * (1 if g > 0 else -1)
        if ex == "next09:35":
            n = nxt(d); return trade(sd, d, M(16, 30), n, M(9, 35)) if n else None
        return trade(sd, d, M(16, 30), d, M(19, 55))
    add(f"엔비디아 애프터 30분 {th}%↑ {'추종' if mode > 0 else '되돌림'} → {ex}", f)
# F. 요일·시간대 흐름 (방향 고정)
for sd, (a, b) in itertools.product((1, -1), ((M(4), M(9, 25)), (M(8), M(9, 25)), (M(16, 5), M(19, 55)), (M(16, 5), M(9, 35) + 10000))):
    def f(d, sd=sd, a=a, b=b):
        if b > 10000:
            n = nxt(d); return trade(sd, d, a, n, b - 10000) if n else None
        return trade(sd, d, a, d, b)
    add(f"항상 {'SOXL' if sd > 0 else 'SOXS'} {a//60:02d}:{a%60:02d} → {'다음 날 ' if b > 10000 else ''}{(b%10000)//60:02d}:{(b%10000)%60:02d}", f)
rows = []
for name, rs in rules.items():
    a = [r for d, r in rs if d < SPLIT]; b = [r for d, r in rs if d >= SPLIT]
    if len(a) < 6 or len(b) < 6: continue
    rows.append((name, len(rs), statistics.mean(a), statistics.mean(b), sum(r > 0 for _, r in rs) / len(rs) * 100, sum(r for _, r in rs), len(a), len(b)))
print(f"{days[0]}~{days[-1]} {len(days)}일 · 규칙 {len(rules)}개 · 앞·뒤 6회 이상 {len(rows)}개")
both = [r for r in rows if r[2] > 0 and r[3] > 0]
print(f"앞(9/1~10/15) 1회 평균 플러스 {sum(r[2] > 0 for r in rows)} · 뒤(10/16~) 플러스 {sum(r[3] > 0 for r in rows)} · 둘 다 {len(both)}"
      f"  (무작위라면 약 {sum(r[2] > 0 for r in rows) * sum(r[3] > 0 for r in rows) / len(rows):.0f}개)")
for r in sorted(both, key=lambda r: -min(r[2], r[3]))[:15]:
    print(f"  {r[0]:48s} {r[1]:3d}회 (앞 {r[6]} 뒤 {r[7]}) 앞 {r[2]:+.2f}% 뒤 {r[3]:+.2f}% 승률 {r[4]:.0f}% 합 {r[5]:+.1f}%")
json.dump({r[0]: [(str(d), x) for d, x in rules[r[0]]] for r in both}, open("extwide.json", "w"))
