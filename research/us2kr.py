"""미국장 결과(한국 아침 6시에 확정) → 그날 한국장. 5년 일봉. 한국 주식 비용 왕복 0.25% (수수료+거래세).
갭(전일 종가→시가)은 매매로 먹을 수 없으니, 시가 진입→종가 청산(장중)을 본다."""
import json, math, datetime, zoneinfo, statistics as S
import numpy as np
def load(n):
    j = json.load(open(f"wild/{n}.json")); tz = zoneinfo.ZoneInfo(j["tz"])
    return {datetime.datetime.fromtimestamp(r[0], tz).date(): r[1:] for r in j["rows"]}
US = {k: load(k) for k in ("SOXL", "NVDA", "SOXX", "QQQ")}
KR = {"SK하이닉스": load("000660.KS"), "삼성전자": load("005930.KS"), "코스피": load("_KS11")}
usd = sorted(US["SOXX"]); C = 0.25
def us_prev(d):                      # 한국 날짜 d 직전에 끝난 미국 정규장 날짜
    ks = [x for x in usd if x < d]; return ks[-1] if len(ks) >= 2 else None
def chg(D, d):
    ks = sorted(x for x in D if x < d)
    return (D[d][3] / D[ks[-1]][3] - 1) * 100 if ks else None
for name, K in KR.items():
    kd = sorted(K); mid = kd[len(kd) // 2]
    rows = []
    for i, d in enumerate(kd[1:], 1):
        u = us_prev(d)
        if not u: continue
        p = kd[i - 1]; o, h, l, c = K[d]
        rows.append({"d": d, "soxx": chg(US["SOXX"], u), "nvda": chg(US["NVDA"], u), "soxl": chg(US["SOXL"], u),
                     "gap": (o / K[p][3] - 1) * 100, "o2c": (c / o - 1) * 100, "c2c": (c / K[p][3] - 1) * 100})
    x = np.array([r["soxx"] for r in rows]); g = np.array([r["gap"] for r in rows]); oc = np.array([r["o2c"] for r in rows])
    print(f"\n■ {name} ({rows[0]['d']}~{rows[-1]['d']}, {len(rows)}일)")
    print(f"  상관: SOXX 전날 등락 ↔ 한국 갭 {np.corrcoef(x, g)[0,1]:+.2f} · ↔ 한국 장중(시가→종가) {np.corrcoef(x, oc)[0,1]:+.2f}")
    acc = np.mean(np.sign(x) == np.sign([r["c2c"] for r in rows]))
    print(f"  방향 맞히기: SOXX 오르면 한국 종가(전일 대비)도 오름 {acc*100:.0f}% · 장중(시가→종가) 방향 {np.mean(np.sign(x)==np.sign(oc))*100:.0f}%")
    b = np.polyfit(x, g, 1)[0]
    print(f"  SOXX 1% 움직이면 한국 시가 갭 평균 {b:+.2f}%")
    for th in (1, 2, 3):
        for mode, lab in ((1, "따라가기"), (-1, "되돌림")):
            r = [mode * np.sign(rr["soxx"]) * rr["o2c"] - C for rr in rows if abs(rr["soxx"]) >= th]
            if mode == -1 and name == "코스피": pass
            a = [mode * np.sign(rr["soxx"]) * rr["o2c"] - C for rr in rows if abs(rr["soxx"]) >= th and rr["d"] < mid]
            bb = [mode * np.sign(rr["soxx"]) * rr["o2c"] - C for rr in rows if abs(rr["soxx"]) >= th and rr["d"] >= mid]
            t = S.mean(r) / (S.pstdev(r) / math.sqrt(len(r)))
            star = " ★" if S.mean(a) > 0 and S.mean(bb) > 0 and t > 2 else ""
            print(f"  SOXX {th}%↑ 움직인 다음 날 시가에 {lab}→종가: {len(r)}회 {S.mean(r):+.2f}% 승률 {np.mean([v>0 for v in r])*100:.0f}% t{t:+.1f} | 앞 {S.mean(a):+.2f} 뒤 {S.mean(bb):+.2f}{star}")
    # 갭이 미국 움직임보다 과하거나 모자랄 때
    res = g - b * x
    for mode, lab in ((-1, "갭이 과하면 되돌림"),):
        sd = np.std(res)
        r = [-np.sign(rr["gap"] - b * rr["soxx"]) * rr["o2c"] - C for rr in rows if abs(rr["gap"] - b * rr["soxx"]) > sd]
        print(f"  {lab} (미국 대비 갭 차이 1σ 넘을 때 반대로): {len(r)}회 {S.mean(r):+.2f}% 승률 {np.mean([v>0 for v in r])*100:.0f}%")
