"""개장 직후 급락·급등 → 회복 패턴: 얼마나 자주 나오나(정확도), 어떻게 타면 이기나(승률·손익).
SOXL 로 방향을 판단하고, 내려갔으면 SOXL 매수 / 올랐으면 SOXS 매수 (실제 SOXS 봉으로 체결 계산).
결정은 봉이 닫힌 뒤, 체결은 다음 봉 시가. 같은 봉에서 손절·익절이 다 닿으면 손절로 본다. 비용 왕복 0.6%.
사용: python openrev.py <1분봉 폴더> <5분봉 폴더>"""
import json, sys, datetime, zoneinfo, statistics as S
ET = zoneinfo.ZoneInfo("America/New_York")
COST = 0.6

def load(path):
    d = {}
    for r in json.load(open(path)):
        t = datetime.datetime.fromtimestamp(r[0], ET); m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            d.setdefault(t.date(), []).append((m, r[1], r[2], r[3], r[4]))
    return d

def days(folder, tf, step):
    a, b = load(f"{folder}/SOXL_{tf}.json"), load(f"{folder}/SOXS_{tf}.json")
    out = {}
    for k in sorted(a):
        if k in b and len(a[k]) >= 390 // step * 0.8:
            out[k] = (sorted(a[k]), {x[0]: x for x in b[k]})
    return out

# ── 1) 현상 측정: 개장 T분 안에 시가 대비 th% 이상 쏠렸을 때, 그 뒤 얼마나 되돌아오나 ──
def phenomenon(D, T, th):
    rows = []
    for d, (L, _) in D.items():
        o = L[0][1]
        pre = [x for x in L if x[0] < 570 + T]; post = [x for x in L if x[0] >= 570 + T]
        if not pre or not post: continue
        hi, lo = max(x[2] for x in pre), min(x[3] for x in pre)
        up, dn = (hi / o - 1) * 100, (1 - lo / o) * 100
        if max(up, dn) < th: continue
        sd = -1 if up > dn else 1                     # 위로 쏠렸으면 되돌림은 아래(-1)
        ext = hi if sd < 0 else lo
        # 쏠림 폭의 절반 이상 되돌아왔나 (그날 안에)
        half = ext + (o - ext) * 0.5
        back = any((x[3] <= half) if sd < 0 else (x[2] >= half) for x in post)
        full = any((x[3] <= o) if sd < 0 else (x[2] >= o) for x in post)
        # 극단을 더 넘어 추세가 이어졌나
        cont = any((x[2] > ext * 1.02) if sd < 0 else (x[3] < ext * 0.98) for x in post)
        close_back = (L[-1][4] - ext) * sd > 0 and abs(L[-1][4] - o) < abs(ext - o)
        rows.append(dict(d=d, mv=max(up, dn), half=back, full=full, cont=cont, cb=close_back))
    return rows

# ── 2) 매매 규칙 ──
def trade(D, rule, **p):
    out = []
    for d, (L, Sx) in D.items():
        r = rule(d, L, Sx, **p)
        if r is not None: out.append((d, r))
    return out

def fill(L, Sx, sd, i, stop_px, tgt_px, until):
    """L[i] 시가에 진입. sd=+1 SOXL 매수, -1 SOXS 매수. 손절·목표는 SOXL 가격 기준, 손익은 실제 산 종목 기준."""
    e = L[i]; m0 = e[0]
    if sd > 0: entry = e[1]
    else:
        s = Sx.get(m0)
        if not s: return None
        entry = s[1]
    for x in L[i:]:
        if x[0] >= until: break
        hit_stop = x[3] <= stop_px if sd > 0 else x[2] >= stop_px
        hit_tgt = x[2] >= tgt_px if sd > 0 else x[3] <= tgt_px
        if hit_stop or hit_tgt:
            px = stop_px if hit_stop else tgt_px
            ex = soxs_equiv(L, Sx, x, px) if sd < 0 else px
            return (ex / entry - 1) * 100 - COST
        last = x
    ex = last[4] if sd > 0 else (Sx.get(last[0]) or (0, 0, 0, 0, None))[4]
    if not ex: return None
    return (ex / entry - 1) * 100 - COST

def soxs_equiv(L, Sx, x, px):
    """SOXL 이 px 에 닿은 순간의 SOXS 가격 근사: 그 봉 SOXS 종가를 SOXL 변화 비율의 -1배로 보정."""
    s = Sx.get(x[0])
    if not s: return None
    return s[1] * (1 - (px / x[1] - 1))

def r_fade(d, L, Sx, T, th, tgt=0.5, stop=2.0, hold=120):
    """T분에 시가 대비 th% 이상 쏠려 있으면 바로 반대로. 목표 = 시가까지 되돌림의 tgt, 손절 = 쏠림 극단 너머 stop%."""
    o = L[0][1]
    pre = [x for x in L if x[0] < 570 + T]
    i = next((k for k, x in enumerate(L) if x[0] >= 570 + T), None)
    if not pre or i is None: return None
    p = pre[-1][4]; mv = (p / o - 1) * 100
    if abs(mv) < th: return None
    sd = 1 if mv < 0 else -1
    ext = min(x[3] for x in pre) if sd > 0 else max(x[2] for x in pre)
    stp = ext * (1 - stop / 100) if sd > 0 else ext * (1 + stop / 100)
    tg = p + (o - p) * tgt
    return fill(L, Sx, sd, i, stp, tg, 570 + T + hold)

def r_turn(d, L, Sx, T, th, conf=1.5, tgt=1.0, stop=1.0, hold=120, last_entry=90):
    """개장 T분 안에 th% 이상 쏠린 뒤, 극단에서 conf% 되돌아오는 걸 '확인'하고 따라 탄다.
    목표 = 시가(tgt=1) 까지, 손절 = 그때까지 극단 너머 stop%."""
    o = L[0][1]; ext = None; sd = 0
    for k, x in enumerate(L):
        if x[0] >= 570 + last_entry: return None
        if x[0] < 570 + T:
            up, dn = (x[2] / o - 1) * 100, (1 - x[3] / o) * 100
            if not sd and max(up, dn) >= th: sd = 1 if dn > up else -1
        if not sd: continue
        ext = (min(ext, x[3]) if ext else x[3]) if sd > 0 else (max(ext, x[2]) if ext else x[2])
        moved = (x[4] / ext - 1) * 100 * sd
        if moved >= conf and k + 1 < len(L):
            stp = ext * (1 - stop / 100) if sd > 0 else ext * (1 + stop / 100)
            nx = L[k + 1][1]
            tg = nx + (o - nx) * tgt
            if (tg - nx) * sd <= 0: return None       # 이미 시가 넘음 → 남은 몫 없음
            return fill(L, Sx, sd, k + 1, stp, tg, L[k + 1][0] + hold)
    return None

def r_follow(d, L, Sx, T, th, stop=2.0, hold=120, tgt=6.0):
    """비교용: 쏠린 방향으로 따라감 (되돌림 가설의 반대)."""
    o = L[0][1]
    pre = [x for x in L if x[0] < 570 + T]
    i = next((k for k, x in enumerate(L) if x[0] >= 570 + T), None)
    if not pre or i is None: return None
    p = pre[-1][4]; mv = (p / o - 1) * 100
    if abs(mv) < th: return None
    sd = 1 if mv > 0 else -1
    stp = p * (1 - stop / 100) if sd > 0 else p * (1 + stop / 100)
    tg = p * (1 + tgt / 100) if sd > 0 else p * (1 - tgt / 100)
    return fill(L, Sx, sd, i, stp, tg, 570 + T + hold)

def stat(rs):
    v = [r for _, r in rs if r is not None]
    if not v: return "  0회"
    w = sum(r > 0 for r in v); eq = 1.0
    for r in v: eq *= 1 + r / 100
    return f"{len(v):3d}회 승률 {w / len(v) * 100:3.0f}% 평균 {S.mean(v):+5.2f}% 누적 {(eq - 1) * 100:+6.1f}%"

def halves(rs, D):
    ks = sorted(D); mid = ks[len(ks) // 2]
    a = [x for x in rs if x[0] < mid]; b = [x for x in rs if x[0] >= mid]
    return stat(a), stat(b)

if __name__ == "__main__":
    sets = [("1분봉", days(sys.argv[1], "1m", 1)), ("5분봉", days(sys.argv[2], "5m", 5))]
    for name, D in sets:
        ks = sorted(D)
        print(f"\n=== {name} {ks[0]} ~ {ks[-1]} ({len(ks)}일) ===")
        print("[현상] 개장 T분 안 시가 대비 쏠림 → 그날 안 되돌림")
        for T in (5, 15, 30):
            for th in (2, 3, 5):
                r = phenomenon(D, T, th)
                if not r: continue
                n = len(r)
                print(f"  {T:2d}분 {th}%↑: {n:2d}일/{len(ks)} · 절반 복귀 {sum(x['half'] for x in r) / n * 100:3.0f}% · 시가 복귀 {sum(x['full'] for x in r) / n * 100:3.0f}%"
                      f" · 극단 2% 더 감 {sum(x['cont'] for x in r) / n * 100:3.0f}%")
        print("[매매] 결과 (앞 절반 / 뒤 절반)")
        tests = []
        for T in (5, 10, 15):
            for th in (2, 3, 4):
                tests.append((f"즉시 반대  {T:2d}분 {th}%  목표 절반복귀", r_fade, dict(T=T, th=th, tgt=0.5)))
                tests.append((f"즉시 반대  {T:2d}분 {th}%  목표 시가    ", r_fade, dict(T=T, th=th, tgt=1.0)))
                for conf in (1.0, 2.0):
                    tests.append((f"반등확인 {conf:.0f}% {T:2d}분 {th}% 목표 시가   ", r_turn, dict(T=T, th=th, conf=conf)))
                tests.append((f"따라가기  {T:2d}분 {th}%  (비교)       ", r_follow, dict(T=T, th=th)))
        step = 1 if name == "1분봉" else 5
        for lab, fn, p in tests:
            if step == 5 and p["T"] % 5: continue
            rs = trade(D, fn, **p)
            a, b = halves(rs, D)
            print(f"  {lab}: {stat(rs)} | {a} | {b}")
