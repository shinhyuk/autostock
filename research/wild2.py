"""장중 엉뚱한 아이디어 2년 1시간봉 (SOXL 기준 %, SOXS 는 반대로 어림, 비용 왕복 0.6%)."""
import json, datetime, zoneinfo, math, statistics as S
ET = zoneinfo.ZoneInfo("America/New_York")
B = {}
for t, o, h, l, c, v in json.load(open("fresh/SOXL_60m.json")):
    x = datetime.datetime.fromtimestamp(t, ET); B.setdefault(x.date(), {})[x.hour * 60 + x.minute] = (o, h, l, c)
days = sorted(d for d in B if 570 in B[d] and 930 in B[d]); mid = days[len(days) // 2]
R = {}
def add(k, d, r): R.setdefault(k, []).append((d, r - 0.6))
for d in days:
    b = B[d]; o = b[570][0]
    r1 = (b[570][3] / o - 1) * 100                         # 첫 1시간
    last = (b[930][3] / b[930][0] - 1) * 100               # 마지막 30분
    mid_ = (b[900][3] / b[630][0] - 1) * 100 if 900 in b and 630 in b else None   # 10:30~15:30
    for th in (0, 2, 4):
        if abs(r1) >= th and r1:
            s = 1 if r1 > 0 else -1
            add(f"첫 1시간 {th}%↑ 방향 → 마지막 30분 따라가기", d, s * last)
            if mid_ is not None: add(f"첫 1시간 {th}%↑ 방향 → 10:30~15:30 따라가기", d, s * mid_)
    if 690 in b and 750 in b:                               # 점심 반전: 11:30 시간 흐름 반대로 12:30~13:30
        r11 = (b[690][3] / b[690][0] - 1) * 100; r12 = (b[750][3] / b[750][0] - 1) * 100
        if abs(r11) >= 1: add("오전 11:30 시간 1%↑ 흐름 → 점심 시간 반대로", d, -(1 if r11 > 0 else -1) * r12)
    lo_d = min(x[2] for k, x in b.items() if 570 <= k < 900); hi_d = max(x[1] for k, x in b.items() if 570 <= k < 900)
    c15 = b[900][3] if 900 in b else None
    if c15 and hi_d > lo_d:
        pos = (c15 - lo_d) / (hi_d - lo_d)
        if pos >= .9: add("15:30 에 당일 고가 근처 → 마지막 30분 따라 SOXL", d, last)
        if pos <= .1: add("15:30 에 당일 저가 근처 → 마지막 30분 SOXS", d, -last)
        if pos <= .1: add("15:30 에 당일 저가 근처 → 마지막 30분 반등 SOXL", d, last)
    p = b[930][0]; rn = round(p)
    if abs(p - rn) / p < 0.003: add("15:30 정수 가격($xx.00) 근처 → 마지막 30분 SOXL", d, last)
print(f"{days[0]}~{days[-1]} {len(days)}일")
for k, v in sorted(R.items(), key=lambda kv: -S.mean(x for _, x in kv[1])):
    r = [x for _, x in v]; a = [x for d, x in v if d < mid]; bb = [x for d, x in v if d >= mid]
    t = S.mean(r) / (S.pstdev(r) / math.sqrt(len(r))) if len(r) > 1 and S.pstdev(r) else 0
    print(f"{k:44s} {len(r):4d}회 {S.mean(r):+.2f}% 승률 {sum(x>0 for x in r)/len(r)*100:3.0f}% t{t:+.1f} | 앞 {S.mean(a):+.2f} 뒤 {S.mean(bb):+.2f}")
