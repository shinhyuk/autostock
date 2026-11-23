"""박스권 매매를 프리마켓·애프터마켓에 적용 (1분봉 20일). 범위 = 각 시간대 시작 후 20분."""
import sys, statistics, itertools, datetime, zoneinfo
sys.argv = ["code/box.py", "data"]; sys.path.insert(0, "code")
import multi, box
ET = zoneinfo.ZoneInfo("America/New_York")
L, S, N, X = (multi.load(s) for s in ("SOXL", "SOXS", "NVDA", "SOXX"))


def build(h0, m0, h1, m1, minbars):
    days = {}
    for t in sorted(L):
        dt = datetime.datetime.fromtimestamp(t, ET)
        if (h0, m0) <= (dt.hour, dt.minute) < (h1, m1):
            days.setdefault(dt.date(), []).append(t)
    out = []
    for d, ts in days.items():
        if len(ts) < minbars:
            continue
        def fill(src):
            r, last = [], None
            for t in ts:
                last = src.get(t, last) or last
                r.append(last)
            return r
        day = {"date": d, "L": [L[t] for t in ts], "S": fill(S), "P": [fill(N), fill(X)]}
        if day["S"][0] is None or any(p[0] is None for p in day["P"]):
            continue
        out.append(day)
    return out


# 정규장 일봉 변동폭으로 변동성 필터 (전날까지 5일 평균)
reg = build(9, 30, 16, 0, 300)
rng = {d["date"]: (max(b[1] for b in d["L"]) - min(b[2] for b in d["L"])) / d["L"][0][0] * 100 for d in reg}
def vol5(day):
    prev = [v for k, v in sorted(rng.items()) if k < day][-5:]
    return statistics.mean(prev) if len(prev) >= 3 else None

sessions = {"프리마켓 04:00~ (한국 18:00~)": (4, 0, 9, 25, 250), "프리마켓 07:00~ (한국 21:00~)": (7, 0, 9, 25, 120),
            "애프터마켓 16:00~ (한국 06:00~)": (16, 0, 19, 55, 180)}
for slip in (0.0010, 0.0020):
    multi.SLIP = box.SLIP = slip
    print(f"\n===== 슬리피지 편도 {slip * 100:.1f}% =====")
    for name, win in sessions.items():
        days = build(*win)
        widths = [(max(b[1] for b in d["L"][:20]) - min(b[2] for b in d["L"][:20])) / d["L"][0][0] * 100 for d in days]
        rows = []
        for z, t, s_, wmin, m in itertools.product((0.2, 0.3), (0.5, 0.8), (0.1, 0.25), (0, 2, 3, 5), (1, 2)):
            bx = dict(n=20, z=z, t=t, s=s_, maxtr=m, tmax=0, wmin=wmin)
            r = box.run(days, {"orb": None, "box": bx})
            rf = box.run([d for d in days if (vol5(d["date"]) or 0) >= 8], {"orb": None, "box": bx})
            rows.append((bx, box.stats(r), box.stats(r[:len(r)//2])["ret"], box.stats(r[len(r)//2:])["ret"], box.stats(rf)))
        med = statistics.median(x[1]["ret"] for x in rows)
        medf = statistics.median(x[4]["ret"] for x in rows)
        both = sum(1 for x in rows if x[2] > 0 and x[3] > 0)
        print(f"[{name}] {len(days)}일, 시작 20분 범위 폭 중앙값 {statistics.median(widths):.1f}%")
        print(f"   조합 {len(rows)}개 중앙값 {med:+.1f}% (필터 적용 {medf:+.1f}%), 이익 조합 {sum(1 for x in rows if x[1]['ret'] > 0)}, 앞·뒤 모두 이익 {both}")
        same = [x for x in rows if x[0]["z"] == 0.2 and x[0]["t"] == 0.8 and x[0]["s"] == 0.1 and x[0]["wmin"] == 5 and x[0]["maxtr"] == 1][0]
        print(f"   정규장과 같은 설정(z0.2 t0.8 s0.1 폭5% 1회): {same[1]} | 필터 적용 {same[4]}")
        best = max(rows, key=lambda x: min(x[2], x[3]))
        print(f"   앞·뒤 중 나쁜 쪽이 가장 좋은 설정: {best[0]} → {best[1]} (앞 {best[2]:+.1f} 뒤 {best[3]:+.1f})")
