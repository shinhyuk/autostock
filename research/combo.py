"""노이즈 영역 돌파 + 박스권 + 변동성 필터 조합 (5분봉). 한 번에 한 포지션.
- 노이즈: 30분마다 노이즈 영역 밖이면 진입, 다시 영역 안으로 들어오거나 반대 신호면 청산 (VWAP 손절 없음)
- 박스권: 개장 20분 범위가 아직 안 깨졌고 폭 5% 이상이면 경계 근처 반등/반락에 진입 (기존과 같음)
- 변동성 필터: 최근 5일 평균 하루 변동폭 8% 미만이면 그날 쉼"""
import sys, statistics
sys.argv = ["code/multi.py", "data"]; sys.path.insert(0, "code")
import multi
from multi import CAP
FEE, SLIP = 0.0025, 0.0003
BPM = 5


def sim(days, use_noise=True, use_box=True, use_orb=False, vol=8, risk=None, lookback=14):
    res = []
    for k in range(lookback, len(days)):
        d, L, S = days[k], days[k]["L"], days[k]["S"]
        if vol and (d["vol5"] is None or d["vol5"] < vol):
            res.append((d["date"], 0.0, [])); continue
        n, o0, pc = len(L), L[0][0], days[k - 1]["L"][-1][3]
        sig = [statistics.mean(abs(days[j]["L"][min(i, len(days[j]["L"]) - 1)][3] / days[j]["L"][0][0] - 1)
                               for j in range(k - lookback, k)) for i in range(n)]
        r = 20 // BPM
        hh, ll = max(b[1] for b in L[:r]), min(b[2] for b in L[:r]); w, mid = hh - ll, (hh + ll) / 2
        p0 = [pp[0][0] for pp in d["P"]]
        broke, nbox, norb, pos, pnl, trades = False, 0, 0, None, 0.0, []

        def close_pos(i_out, px_raw):
            nonlocal pos, pnl
            kind, side, qty, ent = pos[:4]
            px = px_raw * (1 - SLIP)
            net = (px - ent) * qty - FEE * (px + ent) * qty
            pnl += net; trades.append((kind, net)); pos = None

        def open_pos(kind, side, i, stop_frac=None, take_frac=None):
            nonlocal pos
            bars = L if side > 0 else S
            ent = bars[i + 1][0] * (1 + SLIP)
            qty = int(CAP / (ent * (1 + FEE)))
            if risk and stop_frac:
                qty = min(qty, int(CAP * risk / 100 / (ent * stop_frac)))
            pos = (kind, side, qty, ent, ent * (1 - stop_frac) if stop_frac else None,
                   ent * (1 + take_frac) if take_frac else None)

        step = 30 // BPM
        for i in range(r, n - 1):
            c = L[i][3]
            if c > hh or c < ll:
                broke = True
            checkpoint = (i + 1) % step == 0
            up, lo = max(o0, pc) * (1 + sig[i]), min(o0, pc) * (1 - sig[i])
            want = 1 if c > up else -1 if c < lo else 0
            if pos:
                kind, side = pos[0], pos[1]
                bars = L if side > 0 else S
                bo, bh, bl, bc = bars[i][:4]
                if kind in ("box", "orb"):
                    if bl <= pos[4]:
                        close_pos(i, min(bo, pos[4])); continue
                    if bh >= pos[5]:
                        close_pos(i, max(bo, pos[5])); continue
                elif kind == "noise" and checkpoint and (side * (c - (up if side > 0 else lo)) < 0 or (want and want != side)):
                    close_pos(i, bars[i + 1][0]); continue
                if i >= n - 2:
                    close_pos(i, bc)
                continue
            if i >= n - 20 // BPM:
                continue
            if use_noise and checkpoint and want:
                open_pos("noise", want, i); continue
            if use_orb and norb < 2 and i <= 60 // BPM:
                sg = 1 if c > hh else -1 if c < ll else 0
                if sg and all(sg * (pp[i][3] / q - 1) > 0 for pp, q in zip(d["P"], p0)):
                    sf = min(max(abs(c / mid - 1), 0.005), 0.06)
                    open_pos("orb", sg, i, sf, 0.10); norb += 1; continue
            if use_box and not broke and nbox < 1 and w / mid * 100 >= 5:
                bo, bh, bl, bc = L[i][:4]
                if bl <= ll + 0.2 * w and bc > bo and bc < mid:
                    open_pos("box", 1, i, abs((ll - 0.1 * w) / bc - 1), abs((ll + 0.8 * w) / bc - 1)); nbox += 1
                elif bh >= hh - 0.2 * w and bc < bo and bc > mid:
                    open_pos("box", -1, i, abs((hh + 0.1 * w) / bc - 1), abs((hh - 0.8 * w) / bc - 1)); nbox += 1
        if pos:
            close_pos(n - 1, (L if pos[1] > 0 else S)[n - 1][3])
        res.append((d["date"], pnl, trades))
    return res


def show(label, res):
    daily = [x[1] / CAP * 100 for x in res]
    tr = [t for r in res for t in r[2]]
    eq = pk = mdd = 0
    for x in daily:
        eq += x; pk = max(pk, eq); mdd = min(mdd, eq - pk)
    mon = " / ".join(f"{sum(x[1] for x in res if x[0].month == mo) * 1400 / 1e4:+5.0f}만" for mo in (9, 10, 11))
    kinds = {}
    for kd, net in tr:
        kinds.setdefault(kd, []).append(net)
    kd = "  ".join(f"{k} {len(v)}회 {sum(v) * 1400 / 1e4:+.0f}만" for k, v in kinds.items())
    print(f"{label:38s} {mon} | {sum(daily):+6.1f}% → {(1e7 + sum(x[1] for x in res) * 1400) / 1e4:,.0f}만원  "
          f"승률 {sum(1 for t in tr if t[1] > 0) / max(len(tr), 1) * 100:3.0f}%  최대낙폭 {mdd:+5.1f}%  [{kd}]")


if __name__ == "__main__":
    multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
    d5 = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
    prev = []
    for dd in d5:
        L = dd["L"]; dd["vol5"] = statistics.mean(prev[-5:]) if len(prev) >= 3 else None
        prev.append((max(b[1] for b in L) - min(b[2] for b in L)) / L[0][0] * 100)
    print("같은 45거래일 (9/21~11/20, 5분봉, 1000만원)  9월 / 10월 / 11월")
    show("지금 설정 (돌파+박스권+필터+금액조절)", sim(d5, use_noise=False, use_orb=True, risk=3))
    show("노이즈+필터", sim(d5, use_box=False))
    show("노이즈+박스권+필터", sim(d5))
    show("노이즈+박스권+필터+박스 금액조절", sim(d5, risk=3))
    show("노이즈+박스권 (필터 없이)", sim(d5, vol=0))
    show("노이즈+돌파+박스권+필터", sim(d5, use_orb=True))
    show("노이즈+돌파+박스권+필터+금액조절", sim(d5, use_orb=True, risk=3))
