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
        L, S = day["L"], day["S"]; o_, b_ = P["orb"], P["box"]; n = o_["n"]
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
                    full = int(CAP / (ent * 1.01)); full = min(full, int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    q0 = max(1, int(full * Sc.get("a", 1)))
                    pos = {"kind": "orb", "side": side, "qty": q0, "todo": full - q0, "e0": ent, "stop": sp, "take": tp_,
                           "scaled": False, "cash": fill(ent, q0, True)}
                    norb += 1; i += 2; continue
            if not broke and nbox < 1 and w / mid * 100 >= 5:
                o, c = L[i][0], cl; lo_, hi_ = L[i][2], L[i][1]; side = None
                if lo_ <= ll + .2 * w and c > o and c < mid: side = "L"
                elif hi_ >= hh - .2 * w and c < o and c > mid: side = "S"
                if side and i + 1 < len(L):
                    D = L if side == "L" else S; ent = D[i + 1][0]
                    stopL, takeL = (ll - .1 * w, ll + .8 * w) if side == "L" else (hh + .1 * w, hh - .8 * w)
                    sp, tp_ = conv(side, L[i + 1][0], stopL, takeL, ent * (1 + SLIP))
                    q = min(int(CAP / (ent * 1.01)), int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    pos = {"kind": "box", "side": side, "qty": q, "todo": 0, "e0": ent, "stop": sp, "take": tp_, "scaled": False, "cash": fill(ent, q, True)}
                    nbox += 1; i += 2; continue
            i += 1
        res.append((day["date"], pnl, trades))
    return res
WIN, MX = 60, 2
VARS = [("한 번에 사고 한 번에 팜 (지금)", {}),
        ("분할매도: +3% 에 절반 팜", {"f": .5, "t1": 3}),
        ("분할매도: +3% 에 절반, 나머지 본전 손절", {"f": .5, "t1": 3, "be": 1}),
        ("분할매도: +2% 에 1/3, 나머지 본전 손절", {"f": .34, "t1": 2, "be": 1}),
        ("분할매수: 절반 → +1% 가면 추가", {"a": .5, "add": 1}),
        ("분할매수: 절반 → +2% 가면 추가", {"a": .5, "add": 2}),
        ("분할매수 절반→+1% 추가 + 분할매도 +3% 절반·본전", {"a": .5, "add": 1, "f": .5, "t1": 3, "be": 1})]
def go(label, n, per):
    b, s, pe, k = [p for p in PAIRS if p[0] == "SOXL"][0]
    d = multi.build(b, s, pe); h = len(d) // 2
    print(f"\n{label} ({len(d)}일, 1000만원 기준, 위험 3%)")
    for name, sc in VARS:
        r = run(d, {"orb": dict(n=n, tp=6, window=WIN // per, maxtr=MX), "box": None, "risk": 3}, sc)
        tot = sum(x[1] for x in r); a = sum(x[1] for x in r[:h]); bb = sum(x[1] for x in r[h:])
        days = [x[1] for x in r]; eq = pk = mdd = 0
        for x in days: eq += x; pk = max(pk, eq); mdd = min(mdd, eq - pk)
        print(f"  {name:40s} 합 {tot/CAP*100:+6.1f}% · 앞 {a/CAP*100:+5.1f} 뒤 {bb/CAP*100:+5.1f} · 최대낙폭 {mdd/CAP*100:+5.1f}%")
import shutil, glob
for f in glob.glob("data_nov23/*_1m.json"): shutil.copy(f, "data/")
for WIN, MX in ((60, 2), (390, 5)):
    print(f"=== 돌파 진입 {WIN}분 · 하루 {MX}회")
    go("1분봉 1달", 20, 1)
multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
for WIN, MX in ((60, 2), (390, 5)):
    print(f"=== 돌파 진입 {WIN}분 · 하루 {MX}회")
    go("5분봉 60일", 4, 5)
