"""개장 범위를 어느 쪽으로 먼저 뚫을지 미리 맞힐 수 있나. 신호별 정확도 + 걸어가며 학습한 로지스틱 회귀.
A) 5분봉 60일: 개장 20분 범위, 09:50 에 예측, 첫 5분 종가 이탈 방향(장 마감까지).
B) 1시간봉 2년: 개장 60분 범위(첫 1시간 봉), 10:30 에 예측, 이후 1시간 종가 이탈 방향 (거친 근사, 표본이 많음)."""
import json, math, statistics, datetime, zoneinfo
import numpy as np
ET = zoneinfo.ZoneInfo("America/New_York")
def load(s, tf):
    d = {}
    for t, o, h, l, c, v in json.load(open(f"fresh/{s}_{tf}.json")):
        x = datetime.datetime.fromtimestamp(t, ET)
        d.setdefault(x.date(), {})[x.hour * 60 + x.minute] = (o, h, l, c, v)
    return d
def daily(s):
    return {datetime.datetime.fromtimestamp(t, ET).date(): (o, h, l, c) for t, o, h, l, c, v in json.load(open(f"fresh/{s}_1d.json"))}
D = {s: daily(s) for s in ("SOXL", "NVDA", "SOXX", "QQQ")}
ddays = sorted(D["SOXL"])
def prev_day(d):
    i = ddays.index(d) if d in D["SOXL"] else None
    return ddays[i - 1] if i else None

def build(tf, rng_end, step):
    B = {s: load(s, tf) for s in ("SOXL", "NVDA", "SOXX", "QQQ")}
    rows = []
    for d in sorted(B["SOXL"]):
        L = B["SOXL"][d]
        if 570 not in L or d not in D["SOXL"]: continue
        reg = sorted(k for k in L if 570 <= k < 960)
        rk = [k for k in reg if k < rng_end]; after = [k for k in reg if k >= rng_end]
        if len(rk) < (rng_end - 570) // step * 0.8 or len(after) < 5: continue
        hh, ll = max(L[k][1] for k in rk), min(L[k][2] for k in rk); o = L[570][0]; c0 = L[rk[-1]][3]
        lab = 0
        for k in after:
            if L[k][3] > hh: lab = 1; break
            if L[k][3] < ll: lab = -1; break
        p = prev_day(d)
        if not p: continue
        pc = D["SOXL"][p][3]
        pre = [k for k in L if 240 <= k < 570]
        f = {"갭": (o / pc - 1) * 100,
             "개장후 흐름": (c0 / o - 1) * 100,
             "범위 안 위치": (c0 - ll) / (hh - ll) - 0.5 if hh > ll else 0,
             "전날 흐름": (D["SOXL"][p][3] / D["SOXL"][p][0] - 1) * 100,
             "프리 흐름": (L[pre[-1]][3] / L[pre[0]][0] - 1) * 100 if len(pre) > 3 else 0}
        ok = True
        for s in ("NVDA", "SOXX", "QQQ"):
            X = B[s].get(d, {})
            ks = [k for k in X if 570 <= k < rng_end]
            if not ks or 570 not in X: ok = False; break
            f[f"{s} 개장후"] = (X[max(ks)][3] / X[570][0] - 1) * 100
            pp = D[s].get(p); dd = D[s].get(d)
            f[f"{s} 갭"] = (X[570][0] / pp[3] - 1) * 100 if pp else 0
        if ok: rows.append((d, f, lab))
    return rows

def ci(k, n):
    p = k / n; e = 1.96 * math.sqrt(p * (1 - p) / n); return f"{p*100:4.0f}% ±{e*100:3.0f}"

def logit_walk(rows, keys, warm):
    """앞의 날들로만 학습해서 다음 날을 맞힌다 (미래 정보 없음)."""
    X = np.array([[r[1][k] for k in keys] for r in rows]); y = np.array([1 if r[2] > 0 else 0 for r in rows])
    out = []
    for i in range(warm, len(rows)):
        Xt, yt = X[:i], y[:i]
        mu, sd = Xt.mean(0), Xt.std(0) + 1e-9
        Z = (Xt - mu) / sd; w = np.zeros(Z.shape[1]); b = 0.0
        for _ in range(300):
            pr = 1 / (1 + np.exp(-(Z @ w + b))); g = pr - yt
            w -= 0.1 * (Z.T @ g / len(yt) + 0.05 * w); b -= 0.1 * g.mean()
        out.append((1 / (1 + math.exp(-(((X[i] - mu) / sd) @ w + b))), y[i]))
    return out

for name, tf, rng_end, step, warm in (("A) 5분봉 60일 · 20분 범위", "5m", 590, 5, 25), ("B) 1시간봉 2년 · 60분 범위", "60m", 630, 60, 150)):
    rows = build(tf, rng_end, step)
    br = [r for r in rows if r[2] != 0]
    up = sum(r[2] > 0 for r in br)
    print(f"\n{name}: {len(rows)}일, 범위를 뚫은 날 {len(br)} ({len(br)/len(rows)*100:.0f}%) · 위로 {up} 아래로 {len(br)-up}")
    print(f"  기준(항상 많은 쪽): {ci(max(up, len(br)-up), len(br))}")
    for k in br[0][1]:
        hit = sum(1 for r in br if (r[1][k] > 0) == (r[2] > 0) and r[1][k] != 0)
        n = sum(1 for r in br if r[1][k] != 0)
        print(f"  {k:12s} 방향대로: {ci(hit, n)} ({n}일)")
    agree = [r for r in br if np.sign(r[1]["개장후 흐름"]) == np.sign(r[1]["NVDA 개장후"]) == np.sign(r[1]["SOXX 개장후"])]
    hit = sum(1 for r in agree if (r[1]["개장후 흐름"] > 0) == (r[2] > 0))
    print(f"  SOXL·NVDA·SOXX 개장후 같은 방향일 때: {ci(hit, len(agree))} ({len(agree)}일, 전체의 {len(agree)/len(br)*100:.0f}%)")
    keys = list(br[0][1])
    res = logit_walk(br, keys, warm)
    acc = sum((p > .5) == (y == 1) for p, y in res)
    print(f"  로지스틱 회귀(지난날만 학습, {len(res)}일 예측): {ci(acc, len(res))}")
    for th in (0.6, 0.7):
        sel = [(p, y) for p, y in res if p >= th or p <= 1 - th]
        if sel:
            a = sum((p > .5) == (y == 1) for p, y in sel)
            print(f"    확신 {th:.0%} 이상만: {ci(a, len(sel))} ({len(sel)}일, {len(sel)/len(res)*100:.0f}%)")
