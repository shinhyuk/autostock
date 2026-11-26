"""돌파 매매 분할매수·분할매도 비교 (실계좌 설정: 돌파 종일 5회 + 박스권 1회, 손절 범위 중간, 익절 6%, 위험 3%).
분할매수: 처음 a 만큼 사고, 보유 종목이 +add% 가면 나머지 추가 (같은 손절·익절).
분할매도: +t1% 에서 f 만큼 팔고, be 면 나머지 손절을 본전으로."""
import sys
sys.argv = ["code/box.py", "data"]; sys.path.insert(0, "code")
import box, multi
from box import conv
from multi import CAP, SLIP, PAIRS
def run(days, P, Sc):
    res = []
    for day in days:
        L, S = day["L"], day["S"]; o_, b_ = P["orb"], P.get("box"); n = o_["n"]
        hh = max(x[1] for x in L[:n]); ll = min(x[2] for x in L[:n]); w = hh - ll; mid = (hh + ll) / 2
        p0 = [pp[0][0] for pp in day["P"]]
        pnl, trades, pos, i, broke, nbox, norb = 0.0, [], None, n, False, 0, 0
        def fill(px, q, buy):                          # 수수료·슬리피지 포함 현금 변화
            return (-px * (1 + SLIP) * q - multi.FEE * px * q) if buy else (px * (1 - SLIP) * q - multi.FEE * px * q)
        while i < len(L):
            if pos:
                D = L if pos["side"] == "L" else S
                o, h, l, c, v = D[i]
                done = None
                if l <= pos["stop"]: done = min(o, pos["stop"])
                elif h >= pos["take"]: done = max(o, pos["take"])
                elif i >= len(L) - 5: done = c
                else:
                    if pos["kind"] == "orb" and Sc.get("f") and not pos["scaled"] and h >= pos["e0"] * (1 + Sc["t1"] / 100):
                        px = max(o, pos["e0"] * (1 + Sc["t1"] / 100)); q = int(pos["qty"] * Sc["f"])
                        if q: pos["cash"] += fill(px, q, False); pos["qty"] -= q
                        pos["scaled"] = True
                        if Sc.get("be"): pos["stop"] = max(pos["stop"], pos["e0"])
                    if pos["kind"] == "orb" and pos["todo"] and h >= pos["e0"] * (1 + Sc["add"] / 100):
                        px = max(o, pos["e0"] * (1 + Sc["add"] / 100)); q = pos["todo"]
                        pos["cash"] += fill(px, q, True); pos["qty"] += q; pos["todo"] = 0
                if done is not None:
                    pos["cash"] += fill(done, pos["qty"], False)
                    pnl += pos["cash"]; trades.append((pos["kind"], pos["cash"])); pos = None
                i += 1; continue
            if i >= len(L) - 20: i += 1; continue
            cl = L[i][3]; sg = 1 if cl > hh else -1 if cl < ll else 0
            if sg: broke = True
            if sg and i <= o_["window"] and norb < o_["maxtr"]:
                ok = all(sg * (pp[i][3] / q0 - 1) > 0 for pp, q0 in zip(day["P"], p0))
                if ok and i + 1 < len(L):
                    side = "L" if sg > 0 else "S"; D = L if side == "L" else S
                    ent = D[i + 1][0]; refL = L[i + 1][0]
                    takeL = refL * (1 + o_["tp"] / 100) if side == "L" else refL * (1 - o_["tp"] / 100)
                    sp, tp_ = conv(side, refL, mid, takeL, ent * (1 + SLIP))
                    full = int(CAP / (ent * 1.01))
                    if P["risk"]: full = min(full, int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    q0 = max(1, int(full * Sc.get("a", 1)))
                    pos = {"kind": "orb", "side": side, "qty": q0, "todo": full - q0, "e0": ent, "stop": sp, "take": tp_,
                           "scaled": False, "cash": fill(ent, q0, True)}
                    norb += 1; i += 2; continue
            if not broke and nbox < P.get("boxmax", 1) and w / mid * 100 >= 5:
                o, c = L[i][0], cl; lo_, hi_ = L[i][2], L[i][1]; side = None
                if lo_ <= ll + .2 * w and c > o and c < mid: side = "L"
                elif hi_ >= hh - .2 * w and c < o and c > mid: side = "S"
                if side and i + 1 < len(L):
                    D = L if side == "L" else S; ent = D[i + 1][0]
                    stopL, takeL = (ll - .1 * w, ll + .8 * w) if side == "L" else (hh + .1 * w, hh - .8 * w)
                    sp, tp_ = conv(side, L[i + 1][0], stopL, takeL, ent * (1 + SLIP))
                    q = int(CAP / (ent * 1.01))
                    if P["risk"]: q = min(q, int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    pos = {"kind": "box", "side": side, "qty": q, "todo": 0, "e0": ent, "stop": sp, "take": tp_, "scaled": False, "cash": fill(ent, q, True)}
                    nbox += 1; i += 2; continue
            i += 1
        res.append((day["date"], pnl, trades))
    return res

import itertools, json
def evaluate(d, n, per):
    out = {}
    h = len(d) // 2
    for win, mx, tp, sc, risk, bm in itertools.product((60, 120, 390), (2, 5), (6, 10, 15, 30), ((1, 0), (.5, 1), (.5, 2)), (0, 3), (1, 99)):
        r = run(d, {"orb": dict(n=n, tp=tp, window=win // per, maxtr=mx), "risk": risk, "boxmax": bm}, {"a": sc[0], "add": sc[1]} if sc[0] < 1 else {})
        eq = 1.0; pk = 1.0; mdd = 0.0
        for x in r:                                     # 복리: 그날 손익률을 누적
            eq *= 1 + x[1] / CAP; pk = max(pk, eq); mdd = min(mdd, eq / pk - 1)
        a = sum(x[1] for x in r[:h]) / CAP * 100; b = sum(x[1] for x in r[h:]) / CAP * 100
        out[f"{win}|{mx}|{tp}|{sc[0]}/{sc[1]}|{risk}|{bm}"] = (round((eq - 1) * 100, 1), round(mdd * 100, 1), round(a, 1), round(b, 1))
    return out
import shutil, glob
for f in glob.glob("data_nov23/*_1m.json"): shutil.copy(f, "data/")
b_, s_, pe, k = [p for p in PAIRS if p[0] == "SOXL"][0]
d1 = multi.build(b_, s_, pe); r1 = evaluate(d1, 20, 1)
multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
d5 = multi.build(b_, s_, pe); r5 = evaluate(d5, 4, 5)
json.dump({"m1": r1, "m5": r5, "n1": len(d1), "n5": len(d5)}, open("grid.json", "w"))
print("done", len(r1))
