"""억지 흐름·남의 시장 시험.
1) 장 마감 재조정: 15:30 까지 전일 종가 대비 크게 움직인 날, 마지막 30분에 같은 방향으로 더 가나 (약 3년 1시간봉 + 5분봉 60일).
2) 유럽 반도체(ASML·ASM·BESI, 암스테르담): 미국 개장 직전(9시 ET) 전일 대비 움직임 → SOXL 갭·개장 후 흐름.
3) FINRA 공매도 거래 비율(공매도 거래량/전체): 오늘 비율 → 내일 SOXL.
사용: python flows.py <5분봉·60분봉 폴더> <finra 폴더>"""
import json, sys, os, datetime, zoneinfo, math
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from daytype import yahoo, hourly_days, corr
ET = zoneinfo.ZoneInfo("America/New_York")
COST = 0.6

def close_rebal(folder):
    print("\n===== 1) 장 마감 30분 (15:30→16:00), 15:30 까지 전일 종가 대비 움직임 기준 =====")
    for sym in ("SOXL", "TQQQ"):
        D = hourly_days(folder, sym); ks = sorted(D); rows = []
        for a, b in zip(ks, ks[1:]):
            pc = D[a][-1][4]; last = D[b][-1]
            if (last[0].hour, last[0].minute) != (15, 30): continue
            mv = (last[1] / pc - 1) * 100; r = (last[4] / last[1] - 1) * 100
            rows.append((b, mv, r))
        mv, r = np.array([x[1] for x in rows]), np.array([x[2] for x in rows])
        c, t = corr(mv, r)
        print(f"  {sym} 1시간봉 {rows[0][0]}~{rows[-1][0]} {len(rows)}일: 상관 {c:+.2f} (t {t:+.1f})")
        h = len(rows) // 2
        for th in (3, 5, 8, 12):
            for nm, sl in (("전체", slice(None)), ("앞절반", slice(0, h)), ("뒤절반", slice(h, None))):
                m = np.abs(mv[sl]) >= th; g = np.sign(mv[sl][m]) * r[sl][m]
                if nm == "전체": line = f"    |움직임|≥{th:2d}%: {m.sum():3d}일 같은 방향 평균 {g.mean():+.2f}% 이어짐 {np.mean(g > 0) * 100:3.0f}% (비용 0.6% 뺀 평균 {g.mean() - COST:+.2f}%)"
                else: line += f" | {nm} {m.sum()}일 {g.mean() if m.any() else float('nan'):+.2f}%"
            print(line)
    # 5분봉으로 더 잘게: 15:30→15:55
    raw = json.load(open(f"{folder}/SOXL_5m.json")); D = {}
    for t, o, hh, l, c, *_ in raw:
        dt = datetime.datetime.fromtimestamp(t, ET)
        if (9, 30) <= (dt.hour, dt.minute) < (16, 0): D.setdefault(dt.date(), {})[(dt.hour, dt.minute)] = (o, c)
    ks = sorted(D); g = []
    for a, b in zip(ks, ks[1:]):
        pc = D[a].get((15, 55), (0, 0))[1]; x0 = D[b].get((15, 30)); x1 = D[b].get((15, 50))
        if pc and x0 and x1:
            mv = (x0[0] / pc - 1) * 100
            if abs(mv) >= 5: g.append(np.sign(mv) * (x1[1] / x0[0] - 1) * 100)
    print(f"  SOXL 5분봉 60일, |움직임|≥5%: {len(g)}일 같은 방향 평균 {np.mean(g):+.2f}% 이어짐 {np.mean(np.array(g) > 0) * 100:.0f}%")

def europe(folder):
    print("\n===== 2) 유럽 반도체 → SOXL (미국 9시 ET 기준 전일 대비) =====")
    L = hourly_days(folder, "SOXL"); Ld = sorted(L)
    for sym in ("ASML.AS", "ASM.AS", "BESI.AS"):
        bars = yahoo(f"{folder}/{sym}_60m.json"); byd = {}
        for t, o, h, l, c, v in bars: byd.setdefault(t.date(), []).append((t, c))
        ks = sorted(byd); prevc = {}
        for a, b in zip(ks, ks[1:]): prevc[b] = byd[a][-1][1]
        rows = []
        for i, d in enumerate(Ld[1:], 1):
            if d not in byd or d not in prevc: continue
            pre = [c for t, c in byd[d] if t.hour < 9]               # 9시 ET 전 마지막 봉
            if not pre: continue
            eu = (pre[-1] / prevc[d] - 1) * 100
            b = L[d]; pc = L[Ld[i - 1]][-1][4]
            gap = (b[0][1] / pc - 1) * 100; day = (b[-1][4] / b[0][1] - 1) * 100; h1 = (b[0][4] / b[0][1] - 1) * 100
            rows.append((eu, gap, day, h1))
        A = np.array(rows)
        c1, t1 = corr(A[:, 0], A[:, 1]); c2, t2 = corr(A[:, 0], A[:, 2]); c3, t3 = corr(A[:, 0], A[:, 3])
        print(f"  {sym:<8} {len(A)}일: → 미국 갭 상관 {c1:+.2f} (t {t1:+.1f}) · 개장→종가 {c2:+.2f} (t {t2:+.1f}) · 첫 1시간 {c3:+.2f} (t {t3:+.1f})")

def finra(folder, ffolder):
    print("\n===== 3) FINRA 공매도 거래 비율 → 다음 날 =====")
    rat = {}
    for f in sorted(os.listdir(ffolder)):
        for ln in open(os.path.join(ffolder, f)):
            p = ln.strip().split("|")
            if len(p) >= 5 and p[4] not in ("", "0"):
                rat.setdefault(p[1], {})[datetime.datetime.strptime(p[0], "%Y%m%d").date()] = float(p[2]) / float(p[4])
    L = hourly_days(folder, "SOXL"); ks = sorted(L)
    nxt = {a: b for a, b in zip(ks, ks[1:])}
    for sym in ("SOXL", "SOXS", "NVDA"):
        R = rat.get(sym, {}); rows = []
        ds = sorted(d for d in R if d in nxt)
        for i, d in enumerate(ds):
            past = [R[x] for x in ds[max(0, i - 20):i]]
            if len(past) < 10: continue
            z = (R[d] - np.mean(past)) / (np.std(past) + 1e-9)          # 최근 20일 대비 얼마나 높은가
            b = L[nxt[d]]; cc = (b[-1][4] / L[d][-1][4] - 1) * 100; oc = (b[-1][4] / b[0][1] - 1) * 100
            rows.append((z, R[d], cc, oc))
        A = np.array(rows)
        c1, t1 = corr(A[:, 0], A[:, 2]); c2, t2 = corr(A[:, 0], A[:, 3])
        hi = A[A[:, 0] > 1]; lo = A[A[:, 0] < -1]
        print(f"  {sym} {len(A)}일 (비율 평균 {A[:, 1].mean() * 100:.0f}%): 다음날 종가→종가 상관 {c1:+.2f} (t {t1:+.1f}) · 시가→종가 {c2:+.2f} (t {t2:+.1f})"
              f" | 평소보다 높음(z>1) {len(hi)}일 다음날 {hi[:, 2].mean():+.2f}% · 낮음(z<-1) {len(lo)}일 {lo[:, 2].mean():+.2f}%")

if __name__ == "__main__":
    close_rebal(sys.argv[1]); europe(sys.argv[1]); finra(sys.argv[1], sys.argv[2])
