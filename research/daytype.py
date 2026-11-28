"""오늘 장 성격(추세장 vs 되돌림장)을 아침에 알 수 있나.
A) 2년 1시간봉(약 500일): 10:30(첫 1시간) 시점 특징 → 나머지 장이 첫 1시간 방향으로 이어지나(추세) 되돌아오나.
B) 5분봉 60일·1분봉 한 달: 9:40(첫 10분) 특징 → 그날 각 전략(되돌림·돌파·박스) 손익.
특징: 갭, 첫 구간 움직임·변동폭(최근 5일 하루 변동폭 대비), 거래량 배수(최근 10일 같은 구간 대비), VIX 수준·변화,
연속 폭락/폭등 개장 일수, 옵션 만기일(셋째 금요일), 나스닥 3배(TQQQ) 대비 SOXL 의 쏠림.
사용: python daytype.py <1분봉 폴더> <5분봉·60분봉 폴더>"""
import json, sys, datetime, zoneinfo, math, statistics as S
import numpy as np
ET = zoneinfo.ZoneInfo("America/New_York")

def yahoo(path):
    j = json.load(open(path))["chart"]["result"][0]; q = j["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(j.get("timestamp") or []):
        if q["close"][i] is None: continue
        out.append((datetime.datetime.fromtimestamp(t, ET), q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0))
    return out

def hourly_days(folder, sym):
    d = {}
    for t, o, h, l, c, v in yahoo(f"{folder}/{sym}_60m.json"):
        if (9, 30) <= (t.hour, t.minute) < (16, 0): d.setdefault(t.date(), []).append((t, o, h, l, c, v))
    return {k: sorted(v) for k, v in d.items() if len(v) >= 6}

def third_friday(d):
    return d.weekday() == 4 and 15 <= d.day <= 21

def corr(x, y):
    x, y = np.array(x, float), np.array(y, float); m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 8 or x[m].std() == 0: return float("nan"), 0
    r = np.corrcoef(x[m], y[m])[0, 1]; n = m.sum()
    return r, r * math.sqrt((n - 2) / max(1e-9, 1 - r * r))

def part_a(folder):
    L, T, V = hourly_days(folder, "SOXL"), hourly_days(folder, "TQQQ"), hourly_days(folder, "^VIX")
    days = sorted(L); rows = []
    prev_close, ranges, vols, streak = None, [], [], 0
    for d in days:
        b = L[d]; o = b[0][1]; c1 = b[0][4]; hi1, lo1 = b[0][2], b[0][3]; close = b[-1][4]
        mv1 = (c1 / o - 1) * 100; rng1 = (hi1 / lo1 - 1) * 100
        rest = (close / c1 - 1) * 100
        sd = 1 if mv1 > 0 else -1
        f = {"date": d, "mv1": mv1, "absmv1": abs(mv1), "cont": sd * rest,
             "gap": (o / prev_close - 1) * 100 if prev_close else np.nan,
             "rng_rel": rng1 / S.mean(ranges[-5:]) if len(ranges) >= 5 else np.nan,
             "rvol": b[0][5] / S.mean(vols[-10:]) if len(vols) >= 10 and S.mean(vols[-10:]) > 0 else np.nan,
             "streak": streak, "opex": third_friday(d), "dow": d.weekday()}
        f["gap_same"] = np.sign(f["gap"]) * sd if np.isfinite(f["gap"]) else np.nan    # 갭과 첫 1시간이 같은 방향(+1)인가
        if d in T and T[d]:
            tm = (T[d][0][4] / T[d][0][1] - 1) * 100; f["rel_tqqq"] = sd * (mv1 - tm)
        else: f["rel_tqqq"] = np.nan
        if d in V and V[d]:
            f["vix"] = V[d][0][4]; vp = [V[k][-1][4] for k in V if k < d]
            f["vix_chg"] = (V[d][0][4] / vp[-1] - 1) * 100 if vp else np.nan
        else: f["vix"] = f["vix_chg"] = np.nan
        rows.append(f)
        prev_close = close; ranges.append((max(x[2] for x in b) / min(x[3] for x in b) - 1) * 100); vols.append(b[0][5])
        streak = streak + 1 if abs(mv1) >= 3 else 0
    print(f"\n===== A) 2년 1시간봉: {days[0]} ~ {days[-1]} ({len(rows)}일) =====")
    print("목표 = 첫 1시간 방향으로 나머지 장이 더 갔나(+) 되돌아왔나(-), 첫 1시간 |움직임|≥2% 인 날만")
    R = [r for r in rows if r["absmv1"] >= 2]
    print(f"  해당 {len(R)}일, 평균 {np.mean([r['cont'] for r in R]):+.2f}% (추세 이어짐 {np.mean([r['cont'] > 0 for r in R]) * 100:.0f}%)")
    for k in ("absmv1", "gap", "gap_same", "rng_rel", "rvol", "vix", "vix_chg", "streak", "rel_tqqq"):
        r, t = corr([x[k] for x in R], [x["cont"] for x in R])
        print(f"  {k:<9} 상관 {r:+.2f} (t {t:+.1f})")
    print("  구간별 (평균 이어짐 %, 추세일 비율):")
    def grp(name, key, cuts):
        for lo, hi in zip(cuts, cuts[1:]):
            g = [x for x in R if np.isfinite(x[key]) and lo <= x[key] < hi]
            if len(g) >= 5:
                h = len(R) // 2
                a = [x for x in g if x in R[:h]]; b2 = [x for x in g if x in R[h:]]
                fm = lambda z: f"{np.mean([x['cont'] for x in z]):+5.2f}%" if z else "  -  "
                print(f"    {name} {lo:>6}~{hi:<6}: {len(g):3d}일 평균 {np.mean([x['cont'] for x in g]):+5.2f}% 추세 {np.mean([x['cont'] > 0 for x in g]) * 100:3.0f}%  (앞 1년 {fm(a)} / 뒤 1년 {fm(b2)})")
    grp("첫1시간|%|", "absmv1", (2, 3, 5, 8, 99))
    grp("갭같은방향", "gap_same", (-1.5, 0, 1.5))
    grp("거래량배수", "rvol", (0, 0.8, 1.2, 1.8, 99))
    grp("변동폭배수", "rng_rel", (0, 0.5, 0.8, 1.2, 99))
    grp("VIX", "vix", (0, 15, 20, 25, 99))
    grp("연속쏠림일", "streak", (0, 1, 2, 4, 99))
    grp("TQQQ대비", "rel_tqqq", (-99, 0, 2, 99))
    grp("옵션만기", "opex", (0, 0.5, 1.5))
    return rows

if __name__ == "__main__":
    part_a(sys.argv[2])

def part_b(f1, f5):
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    import probsize as P, constit as K, constfilter as F
    vix5 = {}
    for t, o, h, l, c, v in yahoo(f"{f5}/^VIX_5m.json") if False else []:
        pass
    raw = json.load(open(f"{f5}/^VIX_5m.json"))
    for t, o, h, l, c, *_ in raw:
        dt = datetime.datetime.fromtimestamp(t, ET)
        if (dt.hour, dt.minute) == (9, 35): vix5[dt.date()] = c          # 9:35~9:40 봉 종가 = 9:40 VIX
    for lab, folder, tf, step in (("5분봉 60일", f5, "5m", 5), ("1분봉 한 달", f1, "1m", 1)):
        days = P.build(folder, tf, step)
        tr = P.signals(days, step); F.tag(tr, K.build(folder, tf, step), step)
        tr = [t for t in tr if t["kind"] != "orb" or (t["lead"] is not None and t["lead"] >= 1)]   # 지금 실계좌 규칙(주도주 1%)
        feat, vols, streak = {}, [], 0
        for d in days:
            L = d["L"]; k10 = 10 // step
            v10 = None
            mv10 = (L[k10 - 1][3] / L[0][0] - 1) * 100
            feat[d["date"]] = {"vix": vix5.get(d["date"], np.nan), "streak": streak, "mv10": mv10}
            streak = streak + 1 if abs(mv10) >= 4 else 0
        print(f"\n===== B) {lab}: 전략별 손익을 아침 특징으로 나눔 (돌파는 주도주 1% 필터 적용) =====")
        for name, key, cuts in (("VIX", "vix", (0, 20, 25, 99)), ("연속 폭락/폭등 개장(4%↑) 일수", "streak", (0, 1, 3, 99))):
            for lo, hi in zip(cuts, cuts[1:]):
                ds = {d for d, f in feat.items() if np.isfinite(f[key]) and lo <= f[key] < hi}
                line = f"  {name} {lo}~{hi}: {len(ds):2d}일"
                for k in ("fade", "orb", "box"):
                    g = [t["base"] for t in tr if t["date"] in ds and t["kind"] == k]
                    line += f" | {k} {len(g):2d}회 " + (f"평균 {np.mean(g):+5.2f}% 승률 {np.mean([x > 0 for x in g]) * 100:3.0f}%" if g else "-")
                print(line)
        vs = [f["vix"] for f in feat.values() if np.isfinite(f["vix"])]
        print(f"  (이 기간 VIX {min(vs):.1f} ~ {max(vs):.1f}, 중앙 {np.median(vs):.1f})")

if __name__ == "__main__" and len(sys.argv) > 2:
    part_b(sys.argv[1], sys.argv[2])
