"""요일별 장 마감 전 흐름. 2년 1시간봉(SOXL·SOXS 실제 가격) + 5년 일봉. 비용 빼기 전 / 뺀 후(왕복 0.6%)."""
import json, datetime, zoneinfo, statistics as S, math
ET = zoneinfo.ZoneInfo("America/New_York")
def load(path):
    d = {}
    rows = json.load(open(path)); rows = rows["rows"] if isinstance(rows, dict) else rows
    for r in rows:
        t = datetime.datetime.fromtimestamp(r[0], ET); d.setdefault(t.date(), {})[t.hour * 60 + t.minute] = r[1:5]
    return d
H = {s: load(f"data60/{s}.json") for s in ("SOXL", "SOXS")}
def at(D, d, m):                       # m분(동부) 시점 가격: 그 시각에 시작하는 봉의 시가, 없으면 직전 봉 종가
    b = D.get(d, {})
    if m in b: return b[m][0]
    ks = [k for k in b if k < m]
    return b[max(ks)][3] if ks else None
def close(D, d):
    b = D.get(d, {}); ks = [k for k in b if 570 <= k < 960]
    return b[max(ks)][3] if ks else None
days = sorted(d for d in H["SOXL"] if d in H["SOXS"] and close(H["SOXL"], d))
mid = days[len(days) // 2]
def tstat(v): return S.mean(v) / (S.pstdev(v) / math.sqrt(len(v))) if len(v) > 2 and S.pstdev(v) else 0
print(f"1시간봉 {days[0]}~{days[-1]} ({len(days)}일)")
for frm, lab in ((900, "15:00→마감(마지막 1시간)"), (780, "13:00→마감(마지막 3시간)"), (570, "시가→마감(하루)")):
    print(f"\n■ {lab}  (한국시간 {'05:00' if frm == 900 else '03:00' if frm == 780 else '23:30'}~06:00, 겨울 기준)")
    for wd in range(5):
        for s in ("SOXL", "SOXS"):
            D = H[s]; r = []; a = []; b = []
            for d in days:
                if d.weekday() != wd: continue
                p0, p1 = at(D, d, frm), close(D, d)
                if p0 and p1:
                    x = (p1 / p0 - 1) * 100; r.append(x); (a if d < mid else b).append(x)
            if r:
                print(f"  {'월화수목금'[wd]} {s}: {len(r):3d}일 평균 {S.mean(r):+.2f}% (비용 뒤 {S.mean(r)-0.6:+.2f}%) 오른 날 {sum(x>0 for x in r)/len(r)*100:3.0f}% t{tstat(r):+.1f} | 앞 1년 {S.mean(a):+.2f} 뒤 1년 {S.mean(b):+.2f}")
# 5년 일봉: 금요일 종가 → 월요일 시가 (주말), 금요일 장중
def daily(n):
    j = json.load(open(f"wild/{n}.json")); tz = zoneinfo.ZoneInfo(j["tz"])
    return {datetime.datetime.fromtimestamp(r[0], tz).date(): r[1:] for r in j["rows"]}
L5, X5 = daily("SOXL"), daily("SOXS"); dd = sorted(d for d in L5 if d in X5); m5 = dd[len(dd) // 2]
print(f"\n5년 일봉 {dd[0]}~{dd[-1]}")
for s, D in (("SOXL", L5), ("SOXS", X5)):
    for wd in range(5):
        r = [(D[d][3] / D[d][0] - 1) * 100 for d in dd if d.weekday() == wd]
        a = [(D[d][3] / D[d][0] - 1) * 100 for d in dd if d.weekday() == wd and d < m5]; b = [(D[d][3] / D[d][0] - 1) * 100 for d in dd if d.weekday() == wd and d >= m5]
        print(f"  {s} {'월화수목금'[wd]} 장중: 평균 {S.mean(r):+.2f}% 오른 날 {sum(x>0 for x in r)/len(r)*100:.0f}% t{tstat(r):+.1f} | 앞 {S.mean(a):+.2f} 뒤 {S.mean(b):+.2f}")
    w = [(D[dd[i + 1]][0] / D[d][3] - 1) * 100 for i, d in enumerate(dd[:-1]) if d.weekday() == 4 and dd[i + 1].weekday() == 0]
    print(f"  {s} 금요일 종가→월요일 시가(주말): 평균 {S.mean(w):+.2f}% 오른 비율 {sum(x>0 for x in w)/len(w)*100:.0f}% ({len(w)}주)")
