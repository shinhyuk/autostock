"""VWAP 지지·저항 매매. 판단은 SOXL 봉 종가와 VWAP, 체결·손익은 보유 종목(SOXL/SOXS) 다음 봉 시가."""
import sys, statistics, itertools
sys.argv = ["code/multi.py", "data"]; sys.path.insert(0, "code")
import multi
from multi import CAP
FEE, SLIP = 0.0025, 0.0003


def run(days, p, bpm):
    m, start = p["m"] // bpm, max(p.get("start", 15) // bpm, 1)
    res = []
    for d in days:
        L, S = d["L"], d["S"]
        n = len(L)
        pv = vv = 0; vw = []
        for b in L:
            pv += (b[1] + b[2] + b[3]) / 3 * (b[4] or 1); vv += b[4] or 1; vw.append(pv / vv)
        pos, pnl, trades = None, 0.0, []
        i = start
        while i < n - 1:
            o, h, l, c, v = L[i]
            if pos:
                side, i0, entL = pos
                stop = c < vw[i] * (1 - p["s"] / 100) if side > 0 else c > vw[i] * (1 + p["s"] / 100)
                take = p["t"] and ((c / entL - 1) * 100 * side >= p["t"])
                if stop or take or i >= n - 2:
                    bars = L if side > 0 else S
                    ent = bars[i0][0] * (1 + SLIP); qty = int(CAP / (ent * (1 + FEE)))
                    px = bars[i + 1][0] * (1 - SLIP)
                    net = (px - ent) * qty - FEE * (px + ent) * qty
                    pnl += net; trades.append(net); pos = None
                i += 1; continue
            if len(trades) >= p["maxtr"] or i >= n - 30 // bpm or i < m:
                i += 1; continue
            above = all(L[j][3] > vw[j] for j in range(i - m, i))
            below = all(L[j][3] < vw[j] for j in range(i - m, i))
            z = p["z"] / 100
            if above and l <= vw[i] * (1 + z) and c > vw[i] and c > o:
                pos = (1, i + 1, L[i + 1][0])
            elif below and h >= vw[i] * (1 - z) and c < vw[i] and c < o:
                pos = (-1, i + 1, L[i + 1][0])
            i += 1
        res.append((d["date"], pnl, trades))
    return res


def ret(res):
    return sum(x[1] for x in res) / CAP * 100


if __name__ == "__main__":
    multi.TF, multi.MINBARS, multi.D = "1m", 300, "data"; multi._c.clear()
    d1 = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
    multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
    d5 = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
    prev = []
    for dd in d5:
        L = dd["L"]; dd["vol5"] = statistics.mean(prev[-5:]) if len(prev) >= 3 else None
        prev.append((max(b[1] for b in L) - min(b[2] for b in L)) / L[0][0] * 100)
    grid = [dict(m=m, z=z, s=s, t=t, maxtr=mt) for m, z, s, t, mt in
            itertools.product((10, 20, 30), (0.1, 0.3, 0.6), (0.3, 0.7, 1.5), (0, 2, 4), (1, 2, 3))]
    rows = []
    for p in grid:
        r1 = run(d1, p, 1); r5 = run(d5, p, 5)
        mon = {mo: sum(x[1] for x in r5 if x[0].month == mo) / CAP * 100 for mo in (9, 10, 11)}
        rows.append((p, ret(r1[:10]), ret(r1[10:]), ret(r1), ret(r5), mon, sum(len(x[2]) for x in r1)))
    print(f"조합 {len(rows)}개")
    print(f"  1분봉 20일: 중앙값 {statistics.median(r[3] for r in rows):+.1f}%  앞·뒤 10일 모두 이익 {sum(1 for r in rows if r[1] > 0 and r[2] > 0)}개")
    print(f"  5분봉 59일: 중앙값 {statistics.median(r[4] for r in rows):+.1f}%  이익 {sum(1 for r in rows if r[4] > 0)}개 / 9·10·11월 모두 이익 {sum(1 for r in rows if all(v > 0 for v in r[5].values()))}개")
    for key in ("m", "z", "s", "t", "maxtr"):
        vals = sorted(set(r[0][key] for r in rows))
        print(f"   {key:6s} 1분봉20일", {v: round(statistics.median(r[3] for r in rows if r[0][key] == v), 1) for v in vals},
              " 5분봉59일", {v: round(statistics.median(r[4] for r in rows if r[0][key] == v), 1) for v in vals})
    best = sorted(rows, key=lambda r: -min(r[1], r[2], r[4]))[:5]
    print("\n세 구간(1분봉 앞10일·뒤10일, 5분봉 59일) 중 가장 나쁜 값이 가장 좋은 설정:")
    for p, a, b, c, d5r, mon, ntr in best:
        print(f"  {p}  1분봉 앞 {a:+.1f} 뒤 {b:+.1f} (거래 {ntr}) | 5분봉 59일 {d5r:+.1f}% (9월 {mon[9]:+.1f} 10월 {mon[10]:+.1f} 11월 {mon[11]:+.1f})")
