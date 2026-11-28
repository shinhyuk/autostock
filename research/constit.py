"""SOXL 을 구성 종목(반도체 지수 편입 종목)으로 예측할 수 있나.
SOXL 하루 수익률 ≈ 3 × 지수 하루 수익률. 구성 종목으로 '있어야 할 SOXL 가격'(이론가)을 만들고,
① 구성 종목이 SOXL 보다 먼저 움직이나(선행), ② SOXL 이 이론가에서 벗어나면 되돌아오나(괴리), ③ 개장 쏠림이 SOXL 만의 과잉인가,
④ 이 특징들로 그 전 날까지만 학습한 모델이 몇 분 뒤 방향을 맞히나, ⑤ 그걸로 매매하면 비용(왕복 0.6%) 빼고 남나.
사용: python constit.py <1분봉 폴더> <5분봉 폴더>"""
import json, sys, os, datetime, zoneinfo, math
import numpy as np
ET = zoneinfo.ZoneInfo("America/New_York")
CONS = ["NVDA", "AVGO", "AMD", "TSM", "QCOM", "TXN", "MU", "INTC", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "ASML", "NXPI",
        "MCHP", "ON", "MPWR", "TER"]
COST = 0.006

def load(folder, sym, tf):
    p = f"{folder}/{sym}_{tf}.json"
    if not os.path.exists(p): return None
    d = {}
    for t, o, h, l, c, *_ in json.load(open(p)):
        if c is None: continue
        dt = datetime.datetime.fromtimestamp(t, ET); m = dt.hour * 60 + dt.minute
        d.setdefault(dt.date(), {})[m] = (o, h, l, c)
    return d

def build(folder, tf, step):
    S = {s: load(folder, s, tf) for s in ["SOXL", "SOXS", "SOXX", "NQ=F"] + CONS}
    S = {k: v for k, v in S.items() if v}
    cons = [c for c in CONS if c in S]
    days, prevc = [], {}
    grid = list(range(570, 960, step))
    for d in sorted(S["SOXL"]):
        reg = {s: {m: x for m, x in S[s].get(d, {}).items() if 570 <= m < 960} for s in S}
        ok = len(reg["SOXL"]) >= len(grid) * 0.85 and all(len(reg[s]) >= len(grid) * 0.5 for s in ["SOXS", "SOXX"] + cons)
        if ok and all(s in prevc for s in ["SOXL", "SOXX"] + cons):
            def ff(s, k=3):
                out, last = [], None
                for m in grid:
                    x = reg[s].get(m)
                    last = x[k] if x else last
                    out.append(last)
                first = next((v for v in out if v is not None), None)
                return np.array([v if v is not None else first for v in out], float)
            day = {"date": d, "grid": grid, "L": ff("SOXL"), "Co": np.array([reg[c][min(reg[c])][0] for c in cons], float), "Lo": np.array([(reg["SOXL"].get(m) or (None,))[0] or np.nan for m in grid]),
                   "S": ff("SOXS"), "X": ff("SOXX"), "C": np.array([ff(c) for c in cons]),
                   "pc": {s: prevc[s] for s in prevc}, "cons": cons}
            nq = S.get("NQ=F", {}).get(d, {})
            last = None; arr = []
            for m in grid:
                x = nq.get(m); last = x[3] if x else last; arr.append(last)
            day["NQ"] = np.array([v if v is not None else np.nan for v in arr], float)
            day["open"] = {"L": reg["SOXL"][min(reg["SOXL"])][0]}
            days.append(day)
        for s in S:
            if reg[s]: prevc[s] = reg[s][max(reg[s])][3]
    return days

def weights(train_days):
    """SOXX 수익률을 구성 종목 수익률로 회귀 → 음수는 0, 합 1 (그 전 날들만 사용)."""
    if not train_days: return None
    X, y = [], []
    for d in train_days:
        X.append(np.diff(np.log(d["C"]), axis=1).T); y.append(np.diff(np.log(d["X"])))
    X, y = np.vstack(X), np.concatenate(y)
    lam = 1e-6 * len(y)
    k = X.shape[1]
    w = np.linalg.solve(X.T @ X + lam * np.eye(k), X.T @ y + lam * np.ones(k) / k)
    w = np.clip(w, 0, None)
    return w / w.sum() if w.sum() > 0 else np.ones(k) / k

def features(day, w, step):
    L, X, C, cons = day["L"], day["X"], day["C"], day["cons"]
    pcC = np.array([day["pc"][c] for c in cons])
    rC = C / pcC[:, None] - 1                                   # 구성 종목 전일 종가 대비
    B = (w[:, None] * rC).sum(0)                                # 바스켓(지수 추정) 전일 대비
    rL = L / day["pc"]["SOXL"] - 1
    rX = X / day["pc"]["SOXX"] - 1
    dev = rL - 3 * B                                            # SOXL 이 이론가보다 얼마나 더/덜 갔나
    devx = rL - 3 * rX
    oC = day["Co"][:, None]
    breadth = (C > oC).mean(0) - 0.5                            # 시가보다 위인 종목 비율 - 0.5
    lb = lambda a, k: np.r_[np.full(k, np.nan), np.log(a[k:] / a[:-k])]
    n = len(L); F = {}
    for km in (1, 5, 15, 30):
        k = max(1, km // step)
        if km < step: continue
        F[f"L{km}"] = lb(L, k)
        Bl = np.log1p(B); F[f"B{km}"] = 3 * np.r_[np.full(k, np.nan), Bl[k:] - Bl[:-k]]
        F[f"NQ{km}"] = lb(day["NQ"], k)
    F["dev"] = dev; F["devx"] = devx
    F["dev_chg15"] = dev - np.r_[np.full(max(1, 15 // step), np.nan), dev[:-max(1, 15 // step)]]
    F["breadth"] = breadth
    F["disp"] = np.log(C / oC).std(0)
    F["tod"] = np.array(day["grid"]) - 570
    return F

def targets(day, step, hs):
    L = day["L"]; T = {}
    for h in hs:
        k = max(1, h // step)
        T[h] = np.r_[np.log(L[k:] / L[:-k]), np.full(k, np.nan)]
    return T

def ic_table(days, step, hs):
    rows = {}
    for i, d in enumerate(days):
        w = weights(days[max(0, i - 10):i]) if i >= 3 else np.ones(len(d["cons"])) / len(d["cons"])
        d["F"] = features(d, w, step); d["T"] = targets(d, step, hs)
    names = list(days[0]["F"])
    print(f"  {'특징':<10}" + "".join(f"{f'{h}분 뒤':>16}" for h in hs))
    for nm in names:
        if nm == "tod": continue
        line = f"  {nm:<10}"
        for h in hs:
            xs = np.concatenate([d["F"][nm] for d in days]); ys = np.concatenate([d["T"][h] for d in days])
            m = np.isfinite(xs) & np.isfinite(ys)
            sx, sy = xs[m].std(), ys[m].std()
            contrib = []
            for d in days:
                x, y = d["F"][nm], d["T"][h]; mm = np.isfinite(x) & np.isfinite(y)
                contrib.append(((x[mm] - xs[m].mean()) * y[mm]).sum() / (sx * sy * m.sum()) if mm.any() else 0.0)
            c = np.array(contrib); ic = c.sum()
            t = c.mean() / (c.std(ddof=1) / math.sqrt(len(c))) if len(c) > 2 and c.std() > 0 else 0
            line += f"{ic:+7.3f} (t{t:+5.1f})"
        print(line)

FEATS = ["L5", "L15", "B5", "B15", "NQ5", "NQ15", "dev", "dev_chg15", "breadth", "disp"]
NQ_OK = True

def walk_forward(days, step, h, thr_list, warm=5, lam=50.0):
    """그 전 날들로만 릿지 회귀 학습 → 오늘 매 봉 예측. 방향 적중률과, 예측이 thr 넘을 때 h분 보유 매매 결과."""
    k = max(1, h // step)
    preds = []
    for i in range(warm, len(days)):
        tr = days[:i]
        X = np.vstack([np.c_[[d["F"][f] for f in FEATS]].T for d in tr]); y = np.concatenate([d["T"][h] for d in tr])
        m = np.isfinite(X).all(1) & np.isfinite(y)
        X, y = X[m], y[m]
        if len(y) < 200: continue
        mu, sd = X.mean(0), X.std(0) + 1e-12
        Z = (X - mu) / sd
        wv = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
        d = days[i]
        Xt = np.c_[[d["F"][f] for f in FEATS]].T
        p = ((Xt - mu) / sd) @ wv + y.mean()
        preds.append((d, p))
    # 방향 적중
    hit, n, ics = 0, 0, []
    for d, p in preds:
        y = d["T"][h]; m = np.isfinite(p) & np.isfinite(y)
        hit += (np.sign(p[m]) == np.sign(y[m])).sum(); n += m.sum()
        if m.sum() > 10: ics.append(np.corrcoef(p[m], y[m])[0, 1])
    out = {"hit": hit / max(n, 1), "ic": float(np.mean(ics)), "days": len(preds)}
    # 매매: 예측 > thr 이면 SOXL, < -thr 이면 SOXS, h분 보유 (봉 종가에 판단, 다음 봉 시가 근사=종가 체결)
    for thr in thr_list:
        rets = []
        for d, p in preds:
            i = 0; L, S = d["L"], d["S"]
            while i < len(L) - k - 1:
                if np.isfinite(p[i]) and abs(p[i]) > thr and d["grid"][i] - 570 >= 5:
                    H = L if p[i] > 0 else S
                    rets.append(H[i + k] / H[i] - 1 - COST); i += k
                else: i += 1
        r = np.array(rets)
        out[thr] = (len(r), (r > 0).mean() if len(r) else 0, (np.prod(1 + r) - 1) if len(r) else 0)
    return out

def opening(days, step):
    """개장 10분 쏠림: SOXL 이 구성 종목(×3)보다 더 쏠렸나(과잉) → 그 뒤 30·60분."""
    k10 = 10 // step
    rows = []
    for d in days:
        o = d["open"]["L"]; L = d["L"]
        if not np.isfinite(o) or len(L) < k10 + 60 // step: continue
        mvL = L[k10 - 1] / o - 1
        Cn = d["C"]; w = np.ones(len(d["cons"])) / len(d["cons"])
        mvB = 3 * float((w * (Cn[:, k10 - 1] / d["Co"] - 1)).sum())           # 구성 종목 실제 시가 기준
        over = mvL - mvB
        f30 = L[k10 - 1 + 30 // step] / L[k10 - 1] - 1; f60 = L[k10 - 1 + 60 // step] / L[k10 - 1] - 1
        br = float((Cn[:, k10 - 1] > d["Co"]).mean())
        rows.append((d["date"], mvL, mvB, over, br, f30, f60))
    return rows

if __name__ == "__main__":
    hs = [5, 15, 30, 60]
    for name, folder, tf, step in (("1분봉 최근 한 달", sys.argv[1], "1m", 1), ("5분봉 60일", sys.argv[2], "5m", 5)):
        days = build(folder, tf, step)
        print(f"\n===== {name}: {days[0]['date']} ~ {days[-1]['date']} ({len(days)}일, 구성 종목 {len(days[0]['cons'])}개) =====")
        print("[특징별 예측력] 전체 상관계수(IC), t = 날짜별 기여의 일관성 (|t|>2 면 우연 아닐 가능성)")
        ic_table(days, step, hs)
        print("[모델] 그 전 날들로만 학습 → 오늘 예측")
        for h in (15, 30, 60):
            thr = [0.003, 0.006, 0.01]
            r = walk_forward(days, step, h, thr)
            s = " | ".join(f"예측>{t * 100:.1f}%: {r[t][0]}회 승률 {r[t][1] * 100:.0f}% 누적 {r[t][2] * 100:+.1f}%" for t in thr)
            print(f"  {h:2d}분 뒤: 방향 적중 {r['hit'] * 100:.1f}% · IC {r['ic']:+.3f} ({r['days']}일) || {s}")
        print("[개장 10분] SOXL 쏠림 vs 구성 종목×3 쏠림 (과잉 = 차이), 그 뒤 30·60분 SOXL")
        rows = opening(days, step)
        for r in rows:
            if abs(r[1]) >= 0.03:
                print(f"  {r[0]} SOXL {r[1] * 100:+5.1f}% 구성×3 {r[2] * 100:+5.1f}% 과잉 {r[3] * 100:+5.1f}% 오른종목 {r[4] * 100:3.0f}% → 30분 {r[5] * 100:+5.1f}% 60분 {r[6] * 100:+5.1f}%")
        A = np.array([r[1:] for r in rows])
        for j, nm in ((2, "과잉"), (0, "SOXL 쏠림"), (1, "구성×3 쏠림"), (3, "오른 종목 비율")):
            c30 = np.corrcoef(A[:, j], A[:, 4])[0, 1]; c60 = np.corrcoef(A[:, j], A[:, 5])[0, 1]
            print(f"  상관 {nm:<10} → 30분 {c30:+.2f} · 60분 {c60:+.2f}  (n={len(A)})")
