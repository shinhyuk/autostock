"""개장 범위 안 박스권 매매(아래 경계 근처 반등 → SOXL, 위 경계 근처 반락 → SOXS) + 범위 돌파.
청산 판정은 SOXL 가격 수준으로, 체결은 실제 보유 종목 가격으로 계산한다."""
import sys, statistics, itertools
sys.argv = [sys.argv[0], sys.argv[1]] + sys.argv[2:]
sys.path.insert(0, sys.argv[0].rsplit("/", 1)[0])
import multi
import multi
from multi import build, st, CAP, SLIP, PAIRS


def conv(side, refL, stopL, takeL, ent):
    """SOXL 가격 수준을 진입 시점 기준 % 로 바꿔 보유 종목 가격에 적용 (SOXS 는 반대 방향)."""
    sp = abs(stopL / refL - 1); tp = abs(takeL / refL - 1)
    sp = min(max(sp, 0.003), 0.06)
    return (ent * (1 - sp), ent * (1 + tp))


def run(days, P):
    """P: orb(dict|None), box(dict|None)."""
    res = []
    for day in days:
        L, S = day["L"], day["S"]
        o_ = P["orb"]; b_ = P["box"]
        n = (o_ or b_)["n"]
        hh = max(x[1] for x in L[:n]); ll = min(x[2] for x in L[:n]); w = hh - ll; mid = (hh + ll) / 2
        p0 = [pp[0][0] for pp in day["P"]]
        pnl, trades, pos, i, broke, nbox, norb = 0.0, [], None, n, False, 0, 0
        while i < len(L):
            lo_, hi_, cl = L[i][2], L[i][1], L[i][3]
            if pos:
                kind, side, qty, ent, stopP, takeP, i0 = pos            # 보유 종목 자체 가격 기준 (봇과 같은 방식)
                o, h, l, c, v = (L if side == "L" else S)[i]
                ex = None
                if l <= stopP:
                    ex = min(o, stopP)
                elif h >= takeP:
                    ex = max(o, takeP)
                elif i >= len(L) - 5 or (kind == "box" and b_.get("tmax") and i - i0 >= b_["tmax"]):
                    ex = c
                if ex is not None:
                    px = ex * (1 - SLIP)
                    net = (px - ent) * qty - multi.FEE * (px + ent) * qty
                    pnl += net; trades.append((kind, net)); pos = None
                i += 1
                continue
            if i >= len(L) - 20:
                i += 1; continue
            sg = 1 if cl > hh else -1 if cl < ll else 0
            if sg:
                broke = True
            # 돌파 진입
            if o_ and sg and i <= o_["window"] and norb < o_["maxtr"]:
                ok = not o_["peer"] or all(sg * (pp[i][3] / q0 - 1) > 0 for pp, q0 in zip(day["P"], p0))
                if ok and i + 1 < len(L):
                    side = "L" if sg > 0 else "S"
                    ent = (L if side == "L" else S)[i + 1][0] * (1 + SLIP)
                    qty = int(CAP / (ent * (1 + multi.FEE)))
                    refL = L[i + 1][0]
                    if o_["stop"] == "mid":
                        stopL = mid
                    else:
                        stopL = refL * (1 - o_["sl"] / 100) if side == "L" else refL * (1 + o_["sl"] / 100)
                    takeL = refL * (1 + o_["tp"] / 100) if side == "L" else refL * (1 - o_["tp"] / 100)
                    sp, tp_ = conv(side, refL, stopL, takeL, ent)
                    if P.get("risk"):                          # 손절까지 잃는 돈이 자본의 risk% 가 되게 수량 조절
                        qty = min(qty, int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    pos = ("orb", side, qty, ent, sp, tp_, i + 1); norb += 1
                    i += 2; continue
            # 박스권 진입: 아직 범위를 벗어난 적 없고, 경계 근처에서 되돌아오는 봉
            if b_ and not broke and nbox < b_["maxtr"] and i <= b_.get("until", 999) and w / mid * 100 >= b_.get("wmin", 0):
                o, c = L[i][0], cl
                side = None
                if lo_ <= ll + b_["z"] * w and c > o and c < mid:
                    side = "L"
                elif hi_ >= hh - b_["z"] * w and c < o and c > mid:
                    side = "S"
                if side and i + 1 < len(L):
                    ent = (L if side == "L" else S)[i + 1][0] * (1 + SLIP)
                    qty = int(CAP / (ent * (1 + multi.FEE)))
                    if side == "L":
                        stopL, takeL = ll - b_["s"] * w, ll + b_["t"] * w
                    else:
                        stopL, takeL = hh + b_["s"] * w, hh - b_["t"] * w
                    sp, tp_ = conv(side, L[i + 1][0], stopL, takeL, ent)
                    if P.get("risk"):
                        qty = min(qty, int(CAP * P["risk"] / 100 / max(ent - sp, 1e-9)))
                    pos = ("box", side, qty, ent, sp, tp_, i + 1); nbox += 1
                    i += 2; continue
            i += 1
        res.append((day["date"], pnl, trades))
    return res


def stats(res, kind=None):
    tr = [n for r in res for k, n in r[2] if kind is None or k == kind]
    tot = sum(tr)
    return {"ret": round(tot / CAP * 100, 1), "n": len(tr), "win": round(sum(1 for t in tr if t > 0) / max(len(tr), 1) * 100),
            "avg": round(statistics.mean(tr) / CAP * 100, 2) if tr else 0}


if __name__ == "__main__":
    orb_old = dict(n=20, peer=1, stop="pct", sl=1.5, tp=10, window=120, maxtr=2)
    orb_new = dict(n=20, peer=1, stop="mid", sl=1.5, tp=10, window=60, maxtr=2)
    data = {b: build(b, s, pe) for b, s, pe, k in PAIRS}
    d = data["SOXL"]
    print("SOXL/SOXS 돌파만:", stats(run(d, {"orb": orb_new, "box": None})))
    rows = []
    for z, t, s_, m, wmin, tmax in itertools.product((0.1, 0.2, 0.3), (0.5, 0.8), (0.1, 0.25), (1, 2, 4), (0, 3, 5), (0, 15)):
        bx = dict(n=20, z=z, t=t, s=s_, maxtr=m, wmin=wmin, tmax=tmax)
        r = run(d, {"orb": None, "box": bx})
        a, b = stats(r[:10]), stats(r[10:])
        rows.append((bx, stats(r), a["ret"], b["ret"]))
    rets = [x[1]["ret"] for x in rows]
    print(f"\n박스권만 (SOXL/SOXS) 조합 {len(rows)}개: 중앙값 {statistics.median(rets):+.1f}%  이익 조합 {sum(1 for x in rets if x > 0)}  "
          f"앞뒤 모두 이익 {sum(1 for x in rows if x[2] > 0 and x[3] > 0)}")
    for key in ("z", "t", "s", "maxtr", "wmin", "tmax"):
        vals = sorted(set(x[0][key] for x in rows))
        print(f"   {key:6s}", {v: round(statistics.median(x[1]['ret'] for x in rows if x[0][key] == v), 1) for v in vals})
    best = sorted(rows, key=lambda x: -min(x[2], x[3]))[:3]
    for bx, s_, a, b in best:
        print("   가장 안정적:", bx, s_, f"앞 {a:+.1f} 뒤 {b:+.1f}")
    # 다른 짝에서도 같은지
    print("\n다른 짝에서 박스권만 (중간 설정 z=0.2 t=0.5 s=0.25 하루2회):")
    bx = dict(n=20, z=0.2, t=0.5, s=0.25, maxtr=2, wmin=0, tmax=0)
    for name, dd in data.items():
        print(f"   {name:5s}", stats(run(dd, {"orb": None, "box": bx})))
