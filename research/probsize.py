"""확률에 따른 분할 매수·매도 시험.
1) 지금 실계좌 규칙(개장 되돌림 10분 4% + 20분 범위 돌파 60분·2회·동조·손절 범위 중간·익절 15% + 박스권)으로 진입 신호를 만든다.
2) 신호마다 '이길 확률' p 를 그 전 거래들만으로 학습한 로지스틱 회귀로 추정한다(미래 정보 없음, 30회 쌓이기 전엔 전체 승률).
3) 같은 신호에 금액·분할 방식만 바꿔 결과를 비교한다. 수수료 편도 0.25% + 슬리피지 0.03%.
사용: python probsize.py <1분봉 폴더> <5분봉 폴더>"""
import json, sys, datetime, zoneinfo, math
import numpy as np
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, SLIP = 0.0025, 0.0003

def load(path):
    d = {}
    for t, o, h, l, c, *_ in json.load(open(path)):
        dt = datetime.datetime.fromtimestamp(t, ET); m = dt.hour * 60 + dt.minute
        if 570 <= m < 960: d.setdefault(dt.date(), {})[m] = (o, h, l, c)
    return d

def build(folder, tf, step):
    A = {s: load(f"{folder}/{s}_{tf}.json") for s in ("SOXL", "SOXS", "NVDA", "SOXX")}
    days = []
    for d in sorted(A["SOXL"]):
        if any(d not in A[s] for s in A): continue
        ms = sorted(A["SOXL"][d])
        if len(ms) < 390 // step * 0.8 or ms[0] != 570: continue
        def fill(src):
            out, last = [], None
            for m in ms:
                last = src.get(m, last); out.append(last)
            return out
        day = {"date": d, "m": ms, "L": [A["SOXL"][d][m] for m in ms], "S": fill(A["SOXS"][d]),
               "P": [fill(A["NVDA"][d]), fill(A["SOXX"][d])]}
        if day["S"][0] is None or any(p[0] is None for p in day["P"]): continue
        days.append(day)
    return days

def signals(days, step):
    """실계좌 규칙대로 진입 신호와 그때의 특징, 이후 보유 종목 가격 경로를 만든다 (한 번에 한 포지션, 기본 청산)."""
    out, widths = [], []
    for day in days:
        L, S, ms = day["L"], day["S"], day["m"]
        n20, n10 = 20 // step, 10 // step
        hh = max(x[1] for x in L[:n20]); ll = min(x[2] for x in L[:n20]); mid = (hh + ll) / 2; w = hh - ll
        wid = w / mid * 100; vol5 = sum(widths[-5:]) / len(widths[-5:]) if widths else wid
        dayrng = (max(x[1] for x in L) / min(x[2] for x in L) - 1) * 100; widths.append(dayrng)
        o0 = L[0][0]; p0 = [p[0][0] for p in day["P"]]
        i, broke, norb, busy_until, fade_done = n10, False, 0, -1, False
        while i < len(L) - 6:
            if i <= busy_until: i += 1; continue
            c = L[i][3]; mins = ms[i] - 570 + step
            sig = None
            # 개장 되돌림
            if not fade_done and i == n10 - 1 + 1 - 1 + 0 and True:
                pass
            if not fade_done and mins == 10 + step:
                fade_done = True
                pre = L[:n10]; p = pre[-1][3]; mv = (p / o0 - 1) * 100
                if abs(mv) >= 4:
                    sd = 1 if mv < 0 else -1
                    ext = min(x[2] for x in pre) if sd > 0 else max(x[1] for x in pre)
                    stpL = ext * (1 - .02) if sd > 0 else ext * 1.02
                    tgL = p + (o0 - p) * 0.5
                    sig = dict(kind="fade", sd=sd, stpL=stpL, tgL=tgL, hold=120 // step, mv=mv)
            if sig is None and i >= n20:
                sg = 1 if c > hh else -1 if c < ll else 0
                if sg: broke = True
                if sg and mins <= 60 and norb < 2:
                    pm = [(pp[i][3] / q - 1) * 100 for pp, q in zip(day["P"], p0)]
                    if all(sg * x > 0 for x in pm):
                        refL = L[i + 1][0]
                        sig = dict(kind="orb", sd=sg, stpL=mid, tgL=refL * (1 + sg * .15), hold=999,
                                   brk=(c - (hh if sg > 0 else ll)) / w * sg, peer=min(sg * x for x in pm))
                        norb += 1
                elif not broke and wid >= 5:
                    o, lo_, hi_ = L[i][0], L[i][2], L[i][1]
                    if lo_ <= ll + .2 * w and c > o and c < mid:
                        sig = dict(kind="box", sd=1, stpL=ll - .1 * w, tgL=ll + .8 * w, hold=999)
                    elif hi_ >= hh - .2 * w and c < o and c > mid:
                        sig = dict(kind="box", sd=-1, stpL=hh + .1 * w, tgL=hh - .8 * w, hold=999)
            if sig is None: i += 1; continue
            j = i + 1; H = L if sig["sd"] > 0 else S
            ent = H[j][0]; refL = L[j][0]
            sp = min(max(abs(sig["stpL"] / refL - 1), .003), .06); tp = abs(sig["tgL"] / refL - 1)
            path = H[j:min(len(L) - 5, j + sig["hold"]) + 1]
            mv10 = (L[n10 - 1][3] / o0 - 1) * 100
            feat = [sig["kind"] == "orb", sig["kind"] == "box", sig["sd"] > 0, abs(mv10) / 5, wid / 10, vol5 / 10,
                    mins / 60, sig.get("brk", 0), sig.get("peer", 0), sig["sd"] * mv10 / 5, tp / sp / 3]
            t = dict(date=day["date"], m=ms[i], sd=sig["sd"], kind=sig["kind"], sym="SOXL" if sig["sd"] > 0 else "SOXS", ent=ent,
                     stop=ent * (1 - sp), take=ent * (1 + tp), path=path, x=feat, tp=tp, sp=sp)
            r, k = execute(t, 1.0, {}); t["win"] = r > 0; t["base"] = r
            out.append(t); busy_until = j + k
            i = j + 1
    return out

def execute(t, f, sc):
    """자본 대비 f 비율로 진입. sc: add(분할매수: 처음 a 비율 → +add% 에서 나머지), out(분할매도: +t1% 에서 q 비율 매도, 나머지 본전 손절).
    반환: (자본 대비 손익 %, 보유 봉 수)."""
    ent = t["ent"] * (1 + SLIP)
    a = sc.get("a", 1.0) if sc.get("add") else 1.0
    qty, cash, stop, take = f * a / ent, -f * a * (1 + FEE), t["stop"], t["take"]
    todo = f * (1 - a); sold = False
    for k, (o, h, l, c) in enumerate(t["path"]):
        if l <= stop:
            px = min(o, stop) * (1 - SLIP); cash += qty * px * (1 - FEE); return cash * 100, k
        if h >= take:
            px = max(o, take) * (1 - SLIP); cash += qty * px * (1 - FEE); return cash * 100, k
        if todo and h >= t["ent"] * (1 + sc["add"] / 100):
            px = max(o, t["ent"] * (1 + sc["add"] / 100)) * (1 + SLIP)
            qty += todo / px; cash -= todo * (1 + FEE); todo = 0
        if sc.get("out") and not sold and h >= t["ent"] * (1 + sc["out"] / 100):
            px = max(o, t["ent"] * (1 + sc["out"] / 100)) * (1 - SLIP); q = qty * sc["q"]
            cash += q * px * (1 - FEE); qty -= q; sold = True
            if sc.get("be"): stop = max(stop, t["ent"] * (1 + 2 * FEE))
    px = t["path"][-1][3] * (1 - SLIP); cash += qty * px * (1 - FEE)
    return cash * 100, len(t["path"]) - 1

# ── 확률 추정: 그 전 거래만으로 학습한 로지스틱 회귀 (L2) ──
def fit(X, y, lam=1.0, it=300):
    X = np.c_[np.ones(len(X)), X]; w = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) / len(y) + lam * np.r_[0, w[1:]] / len(y)
        Hm = (X.T * (p * (1 - p))) @ X / len(y) + lam * np.eye(len(w)) / len(y)
        w -= np.linalg.solve(Hm + 1e-9 * np.eye(len(w)), g)
    return w

def probs(trades, prior=None, warm=30):
    """prior: 앞선 기간 거래(학습만). 각 거래 p = 그 날짜 이전 거래로 학습한 모델."""
    hist = list(prior or [])
    for t in trades:
        past = [h for h in hist if h["date"] < t["date"]]
        if len(past) < warm:
            t["p"] = (sum(h["win"] for h in past) + 1) / (len(past) + 2)
        else:
            w = fit(np.array([h["x"] for h in past], float), np.array([h["win"] for h in past], float), lam=3.0)
            t["p"] = float(1 / (1 + math.exp(-(w[0] + np.dot(w[1:], t["x"])))))
        hist.append(t)

def rolling(trades, prior=None, n=10):
    """최근 n 번 거래의 실제 승률 (그 거래 전까지). 확률을 '요즘 이 전략이 맞는 정도'로 본다."""
    hist = list(prior or [])
    for t in trades:
        past = [h["win"] for h in hist if h["date"] < t["date"]][-n:]
        t["r"] = (sum(past) + 1) / (len(past) + 2)
        hist.append(t)

def kelly(t):
    b = t["tp"] / t["sp"]; p = t["p"]
    return max(0.0, min(1.0, p - (1 - p) / b))

SCHEMES = [
    ("올인 (지금 방식에서 분할 없음)", lambda t: 1.0, {}),
    ("올인 + 분할매수 절반→+1% (지금 실계좌)", lambda t: 1.0, {"add": 1, "a": .5}),
    ("항상 절반만", lambda t: .5, {}),
    ("확률 비례: p 0.35→25% ~ 0.65→100%", lambda t: min(1, max(.25, (t["p"] - .35) / .3 * .75 + .25)), {}),
    ("확률 비례 + 분할매수 절반→+1%", lambda t: min(1, max(.25, (t["p"] - .35) / .3 * .75 + .25)), {"add": 1, "a": .5}),
    ("켈리 (p·손익비)", kelly, {}),
    ("절반 켈리", lambda t: kelly(t) / 2, {}),
    ("p<0.4 건너뜀, 나머지 올인", lambda t: 0.0 if t["p"] < .4 else 1.0, {}),
    ("p<0.4 건너뜀 + 분할매수", lambda t: 0.0 if t["p"] < .4 else 1.0, {"add": 1, "a": .5}),
    ("최근 10회 승률<40% 쉼 · 40~55% 절반 · 55%↑ 올인", lambda t: 0.0 if t["r"] < .4 else .5 if t["r"] < .55 else 1.0, {}),
    ("최근 10회 승률<40% 25% · 40~55% 절반 · 55%↑ 올인", lambda t: .25 if t["r"] < .4 else .5 if t["r"] < .55 else 1.0, {}),
    ("최근 10회 승률 비례 (승률 그대로 투입)", lambda t: t["r"], {}),
    ("최근 승률 3단계 + 분할매수", lambda t: .25 if t["r"] < .4 else .5 if t["r"] < .55 else 1.0, {"add": 1, "a": .5}),
    ("분할매도 +3% 절반", lambda t: 1.0, {"out": 3, "q": .5}),
    ("분할매도 +3% 절반 · 나머지 본전손절", lambda t: 1.0, {"out": 3, "q": .5, "be": 1}),
    ("분할매도 +3% (1-p) 만큼 · 본전손절", lambda t: 1.0, {"out": 3, "q": None, "be": 1}),
    ("분할매수 + 분할매도 +3% (1-p) · 본전", lambda t: 1.0, {"add": 1, "a": .5, "out": 3, "q": None, "be": 1}),
]

def report(trades, label):
    days = sorted({t["date"] for t in trades})
    print(f"\n=== {label}: {days[0]} ~ {days[-1]}, 신호 {len(trades)}회 (되돌림 {sum(t['kind'] == 'fade' for t in trades)}"
          f" · 돌파 {sum(t['kind'] == 'orb' for t in trades)} · 박스 {sum(t['kind'] == 'box' for t in trades)}), 기본 승률 "
          f"{sum(t['win'] for t in trades) / len(trades) * 100:.0f}% ===")
    ps = np.array([t["p"] for t in trades]); ws = np.array([t["win"] for t in trades])
    for lo, hi in ((0, .4), (.4, .5), (.5, .6), (.6, 1.01)):
        m = (ps >= lo) & (ps < hi)
        if m.any(): print(f"  추정 확률 {lo:.1f}~{min(hi, 1):.1f}: {m.sum():3d}회 실제 승률 {ws[m].mean() * 100:3.0f}%")
    print(f"  {'방식':<38} {'누적':>7} {'최대낙폭':>8} {'평균투입':>8} {'승률':>5}")
    for name, fz, sc in SCHEMES:
        eq, peak, mdd, used, wins, n = 1.0, 1.0, 0.0, [], 0, 0
        for t in trades:
            f = fz(t)
            if f <= 0: continue
            s = dict(sc)
            if s.get("q") is None and "out" in s: s["q"] = max(0.0, min(1.0, 1 - t["p"]))
            r, _ = execute(t, f, s)
            eq *= 1 + r / 100; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
            used.append(f); wins += r > 0; n += 1
        print(f"  {name:<38} {(eq - 1) * 100:+6.1f}% {mdd * 100:7.1f}% {np.mean(used) * 100:7.0f}% {wins / max(n, 1) * 100:4.0f}%")

if __name__ == "__main__":
    T5 = signals(build(sys.argv[2], "5m", 5), 5)
    T1 = signals(build(sys.argv[1], "1m", 1), 1)
    probs(T5); rolling(T5)
    report(T5, "5분봉 60일 (확률은 그 전 거래로만 학습)")
    cut = min(t["date"] for t in T1)
    probs(T1, prior=[t for t in T5 if t["date"] < cut]); rolling(T1, prior=[t for t in T5 if t["date"] < cut])
    report(T1, "1분봉 최근 한 달 (5분봉 이전 기간으로 미리 학습)")
    h = len(T5) // 2
    a, b = T5[:h], T5[h:]
    report(a, "5분봉 앞 절반"); report(b, "5분봉 뒤 절반")
