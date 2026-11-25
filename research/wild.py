"""기상천외 포함 일봉 아이디어 5년 검증. 실제 SOXL / SOXS 일봉으로 계산, 비용 왕복 0.6% (오버나이트 보유도 같음).
신호는 진입 전에 알 수 있는 값만 쓴다. 앞 2.5년 / 뒤 2.5년으로 나눠 둘 다 플러스이고 t>2 인지 본다."""
import json, math, datetime, zoneinfo, statistics as S
def load(n):
    j = json.load(open(f"wild/{n}.json")); tz = zoneinfo.ZoneInfo(j["tz"])
    return {datetime.datetime.fromtimestamp(r[0], tz).date(): r[1:] for r in j["rows"]}
L, X = load("SOXL"), load("SOXS")
O = {k: load(k) for k in ("_VIX", "BTC-USD", "005930.KS", "000660.KS", "_KS11", "8035.T", "NVDA", "SOXX", "QQQ", "_TNX", "DX-Y.NYB", "GC_F")}
days = sorted(d for d in L if d in X)
mid = days[len(days) // 2]
C = 0.6
def o2c(D, d): o, h, l, c = D[d]; return (c / o - 1) * 100
def c2c(D, d, p): return (D[d][3] / D[p][3] - 1) * 100
rules = {}
def add(name, d, side, kind="o2c"):
    i = days.index(d)
    if kind == "o2c":
        r = o2c(L, d) if side > 0 else o2c(X, d)
    else:                                 # 오버나이트: d 종가 → 다음 날 시가
        if i + 1 >= len(days): return
        n = days[i + 1]; D = L if side > 0 else X
        r = (D[n][0] / D[d][3] - 1) * 100
    rules.setdefault(name, []).append((d, r - C))
def moon(d):
    ref = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)
    t = datetime.datetime.combine(d, datetime.time(14, 30), datetime.timezone.utc)
    return ((t - ref).total_seconds() / 86400) % 29.530588
def prior(D, d, k=1):
    ks = [x for x in D if x < d]; return sorted(ks)[-k:] if len(ks) >= k else None
for i, d in enumerate(days[5:], 5):
    p, p2, p3 = days[i - 1], days[i - 2], days[i - 3]
    wd = "월화수목금"[d.weekday()]
    add(f"요일: {wd}요일 SOXL", d, 1); add(f"요일: {wd}요일 SOXS", d, -1)
    nxt = days[i + 1] if i + 1 < len(days) else None
    if nxt and nxt.month != d.month or (p.month != d.month) or (days[i - 2].month != d.month):
        add("월말·월초 SOXL", d, 1)
    m = moon(d)
    if 13.8 <= m <= 15.8: add("보름달 SOXL", d, 1); add("보름달 SOXS", d, -1)
    if m <= 1 or m >= 28.5: add("그믐(신월) SOXL", d, 1); add("그믐(신월) SOXS", d, -1)
    pr = c2c(L, p, p2)
    for th in (5, 8, 12):
        if pr <= -th: add(f"전날 -{th}%↓ 다음날 반등 SOXL", d, 1); add(f"전날 -{th}%↓ 다음날 SOXS 추종", d, -1)
        if pr >= th: add(f"전날 +{th}%↑ 다음날 SOXL 추종", d, 1); add(f"전날 +{th}%↑ 다음날 되돌림 SOXS", d, -1)
    if all(c2c(L, days[i - k], days[i - k - 1]) < 0 for k in (1, 2, 3)): add("3일 연속 하락 후 SOXL", d, 1)
    if all(c2c(L, days[i - k], days[i - k - 1]) > 0 for k in (1, 2, 3)): add("3일 연속 상승 후 SOXS", d, -1)
    add("항상 SOXL 장중(시가→종가)", d, 1); add("항상 SOXS 장중", d, -1)
    add("항상 SOXL 밤사이(종가→다음 시가)", d, 1, "on"); add("항상 SOXS 밤사이", d, -1, "on")
    if wd == "금": add("금요일 종가 → 월요일 시가 SOXL", d, 1, "on")
    o, h, l, c = L[p]
    if h > l and (c - l) / (h - l) >= 0.9: add("전날 고가 근처 마감 → SOXL 추종", d, 1); add("전날 고가 근처 마감 → SOXS 되돌림", d, -1)
    if h > l and (c - l) / (h - l) <= 0.1: add("전날 저가 근처 마감 → SOXL 반등", d, 1); add("전날 저가 근처 마감 → SOXS 추종", d, -1)
    gap = (L[d][0] / L[p][3] - 1) * 100
    for th in (3, 6):
        if gap >= th: add(f"갭 +{th}%↑ 되돌림 SOXS", d, -1); add(f"갭 +{th}%↑ 추종 SOXL", d, 1)
        if gap <= -th: add(f"갭 -{th}%↓ 반등 SOXL", d, 1); add(f"갭 -{th}%↓ 추종 SOXS", d, -1)
    V = O["_VIX"]
    if p in V and p2 in V:
        vc = c2c(V, p, p2)
        if vc >= 10: add("공포지수 전날 +10%↑ → SOXL 반등", d, 1); add("공포지수 전날 +10%↑ → SOXS", d, -1)
        if vc <= -8: add("공포지수 전날 -8%↓ → SOXL", d, 1)
        if V[p][3] >= 30: add("공포지수 30 이상 → SOXL", d, 1)
    if wd == "월":
        B = O["BTC-USD"]; fri = d - datetime.timedelta(days=3); sun = d - datetime.timedelta(days=1)
        if fri in B and sun in B:
            br = (B[sun][3] / B[fri][3] - 1) * 100
            if br >= 3: add("비트코인 주말 +3%↑ → 월요일 SOXL", d, 1)
            if br <= -3: add("비트코인 주말 -3%↓ → 월요일 SOXS", d, -1)
    for k, nm in (("000660.KS", "SK하이닉스"), ("005930.KS", "삼성전자"), ("8035.T", "도쿄일렉트론"), ("_KS11", "코스피")):
        K = O[k]
        if d in K:                            # 한국·일본 장은 미국 같은 날짜 장보다 먼저 끝난다
            kp = prior(K, d)
            if not kp: continue
            kr = c2c(K, d, kp[-1])
            if kr >= 2: add(f"{nm} 당일 +2%↑ → 그날 밤 SOXL 장중", d, 1); add(f"{nm} 당일 +2%↑ → SOXS 되돌림", d, -1)
            if kr <= -2: add(f"{nm} 당일 -2%↓ → 그날 밤 SOXS 장중", d, -1); add(f"{nm} 당일 -2%↓ → SOXL 반등", d, 1)
    for k, nm in (("_TNX", "미 10년 금리"), ("DX-Y.NYB", "달러지수"), ("GC_F", "금값")):
        K = O[k]
        if p in K and p2 in K:
            kc = c2c(K, p, p2)
            th = 3 if k == "_TNX" else 0.7 if k == "DX-Y.NYB" else 1.5
            if kc >= th: add(f"{nm} 전날 급등 → SOXS", d, -1); add(f"{nm} 전날 급등 → SOXL", d, 1)
            if kc <= -th: add(f"{nm} 전날 급락 → SOXL", d, 1)
    if d.month in (11, 12, 1, 2, 3, 4): add("11~4월만 SOXL 장중", d, 1)
    else: add("5~10월만 SOXL 장중", d, 1)
    if d.day == 13 and wd == "금": add("13일의 금요일 SOXS", d, -1)
out = []
for k, v in rules.items():
    r = [x for _, x in v]
    if len(r) < 15: continue
    a = [x for d, x in v if d < mid]; b = [x for d, x in v if d >= mid]
    sd = S.pstdev(r) or 1
    t = S.mean(r) / (sd / math.sqrt(len(r)))
    out.append((k, len(r), S.mean(r), sum(x > 0 for x in r) / len(r) * 100, t, S.mean(a) if a else float('nan'), S.mean(b) if b else float('nan')))
print(f"{days[0]} ~ {days[-1]} ({len(days)}일), 나눔 {mid}, 비용 왕복 {C}%, 규칙 {len(out)}개")
print(f"{'규칙':34s} {'횟수':>4s} {'1회평균':>7s} {'승률':>4s} {'t':>5s} | {'앞 2.5년':>7s} {'뒤 2.5년':>7s}")
for k, n, m_, w, t, a, b in sorted(out, key=lambda x: -x[4]):
    flag = " ★" if a > 0 and b > 0 and t > 2 else ""
    print(f"{k:34s} {n:4d} {m_:+6.2f}% {w:3.0f}% {t:+5.1f} | {a:+6.2f}% {b:+6.2f}%{flag}")
