"""공개 연구의 장중 전략을 SOXL/SOXS 에 시험. 수수료 편도 0.25%, 슬리피지 편도 0.03%, 1000만원, 매일 새로 시작.
신호는 봉 종가, 체결은 다음 봉 시가(보유 종목 자체 가격)."""
import sys, statistics, datetime, zoneinfo
sys.argv = ["code/multi.py", "data"]; sys.path.insert(0, "code")
import multi
from multi import CAP
ET = zoneinfo.ZoneInfo("America/New_York")
FEE, SLIP = 0.0025, 0.0003


def trade(side_bars, i_in, i_out, px_out=None):
    ent = side_bars[i_in][0] * (1 + SLIP)
    qty = int(CAP / (ent * (1 + FEE)))
    px = (px_out if px_out is not None else side_bars[i_out][0]) * (1 - SLIP)
    return (px - ent) * qty - FEE * (px + ent) * qty


def noise_area(days, bpm, lookback=14, every=30, vwap_stop=True, mult=1.0):
    """노이즈 영역 돌파. bpm=봉 하나의 분. 매 every 분(HH:00/HH:30)마다 판단."""
    res = []
    for k in range(lookback, len(days)):
        d, L, S = days[k], days[k]["L"], days[k]["S"]
        o = L[0][0]; pc = days[k - 1]["L"][-1][3]
        n = len(L)
        sig = []
        for i in range(n):                                  # 같은 시각의 과거 평균 이동폭
            mv = [abs(days[j]["L"][min(i, len(days[j]["L"]) - 1)][3] / days[j]["L"][0][0] - 1) for j in range(k - lookback, k)]
            sig.append(mult * statistics.mean(mv))
        pv = vv = 0; vw = []
        for b in L:
            pv += (b[1] + b[2] + b[3]) / 3 * (b[4] or 1); vv += b[4] or 1; vw.append(pv / vv)
        pos, pnl, trades = None, 0.0, []
        step = every // bpm
        for i in range(step - 1, n - 1, step):              # 30분 봉이 끝나는 시점
            c = L[i][3]
            up, lo = max(o, pc) * (1 + sig[i]), min(o, pc) * (1 - sig[i])
            want = 1 if c > up else -1 if c < lo else 0
            if pos:
                side, i0 = pos
                stop = max(up, vw[i]) if side > 0 else min(lo, vw[i])
                exit_ = (side > 0 and c < (stop if vwap_stop else up)) or (side < 0 and c > (stop if vwap_stop else lo))
                if exit_ or (want and want != side):
                    net = trade(L if side > 0 else S, i0, i + 1); pnl += net; trades.append(net); pos = None
            if not pos and want:
                pos = (want, i + 1)
        if pos:
            side, i0 = pos
            net = trade(L if side > 0 else S, i0, n - 1, (L if side > 0 else S)[n - 1][3]); pnl += net; trades.append(net)
        res.append((d["date"], pnl, trades))
    return res


def orb5(days, bpm, R=10):
    """첫 5분봉 방향으로 진입, 손절은 첫 봉 반대편, 목표 R배, 장 마감 청산."""
    res = []
    m = 5 // bpm
    for d in days:
        L, S = d["L"], d["S"]
        first_o, first_c = L[0][0], L[m - 1][3]
        hi, lo = max(b[1] for b in L[:m]), min(b[2] for b in L[:m])
        if first_c == first_o:
            res.append((d["date"], 0.0, [])); continue
        side = 1 if first_c > first_o else -1
        bars = L if side > 0 else S
        refL = L[m][0]
        risk = abs(refL - (lo if side > 0 else hi)) / refL           # SOXL 기준 손절 거리 → 보유 종목에 같은 % 적용
        ent = bars[m][0] * (1 + SLIP)
        stop, take = ent * (1 - risk), ent * (1 + R * risk)
        qty = int(CAP / (ent * (1 + FEE)))
        out = None
        for i in range(m, len(L)):
            o, h, l, c, v = bars[i]
            if l <= stop: out = min(o, stop); break
            if h >= take: out = max(o, take); break
        if out is None:
            out = bars[-1][3]
        px = out * (1 - SLIP)
        net = (px - ent) * qty - FEE * (px + ent) * qty
        res.append((d["date"], net, [net]))
    return res


def intramom(days, bpm, first=30, hold=30, thr=0.0):
    """전날 종가→개장 30분 수익률 방향으로 마지막 30분 보유."""
    res = []
    for k in range(1, len(days)):
        L, S = days[k]["L"], days[k]["S"]
        pc = days[k - 1]["L"][-1][3]
        r = L[first // bpm - 1][3] / pc - 1
        if abs(r) * 100 <= thr:
            res.append((days[k]["date"], 0.0, [])); continue
        side = 1 if r > 0 else -1
        bars = L if side > 0 else S
        i0 = len(L) - hold // bpm
        net = trade(bars, i0, len(L) - 1, bars[-1][3])
        res.append((days[k]["date"], net, [net]))
    return res


def summ(res):
    daily = [x[1] / CAP * 100 for x in res]
    tr = [(t[1] if isinstance(t, tuple) else t) for r in res for t in r[2]]
    eq = pk = mdd = 0
    for x in daily:
        eq += x; pk = max(pk, eq); mdd = min(mdd, eq - pk)
    return f"{sum(daily):+7.1f}% ({sum(x[1] for x in res) * 1400 / 1e4:+6.0f}만)  {len(daily):2d}일  거래 {len(tr):3d}  승률 {sum(1 for t in tr if t > 0) / max(len(tr), 1) * 100:3.0f}%  최대낙폭 {mdd:+6.1f}%"


if __name__ == "__main__":
    multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
    d5 = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
    multi.TF, multi.MINBARS, multi.D = "1m", 300, "data"; multi._c.clear()
    d1 = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
    print("■ 5분봉 59일 (8/31~11/20)  ※ 노이즈 영역은 첫 14일을 기준 계산에 써서 45일만 매매")
    nz = noise_area(d5, 5)
    print("  노이즈 영역 돌파 (논문 그대로)       ", summ(nz))
    print("    같은 45일 구간에서 9월/10월/11월:", " / ".join(f"{sum(x[1] for x in nz if x[0].month == mo) * 1400 / 1e4:+.0f}만" for mo in (9, 10, 11)))
    print("  노이즈 영역 (VWAP 손절 없이)        ", summ(noise_area(d5, 5, vwap_stop=False)))
    print("  노이즈 영역 (폭 1.5배)              ", summ(noise_area(d5, 5, mult=1.5)))
    print("  5분 개장 돌파 (논문, 10R)           ", summ(orb5(d5, 5)))
    print("  5분 개장 돌파 (3R)                  ", summ(orb5(d5, 5, R=3)))
    print("  장중 모멘텀 (마지막 30분)            ", summ(intramom(d5, 5)))
    print("  장중 모멘텀 (첫 30분 ±2% 넘을 때만)  ", summ(intramom(d5, 5, thr=2)))
    print("\n■ 1분봉 20일 (10/26~11/20)")
    print("  5분 개장 돌파 (논문, 10R)           ", summ(orb5(d1, 1)))
    print("  장중 모멘텀 (마지막 30분)            ", summ(intramom(d1, 1)))
    print("  노이즈 영역 (14일 기준 → 6일만)      ", summ(noise_area(d1, 1)))
