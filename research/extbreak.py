"""시간외 박스 돌파 추종: SOXL 이 직전 60분 박스 위로 나가면 SOXL, 아래로 나가면 SOXS(=SOXL 반대 어림). 5분봉 60일."""
import sys, json, itertools
from datetime import datetime
sys.path.insert(0, '/home/user/autostock')
from autostock import extbox
ET = extbox.ET
rows = json.load(open(sys.argv[1]))
COST = 0.7
def run(L, tgtw, stp, conf, hmin):
    out, done = [], set()
    n = len(rows)
    for i in range(n):
        t = rows[i][0]; dt = datetime.fromtimestamp(t, ET); s = extbox.session(dt)
        if not s: continue
        name, _, close = s; end = min(close.timestamp(), t + hmin * 60)
        win = [r for r in rows[max(0, i - L // 5 - 3):i] if t - L * 60 <= r[0] < t]
        if len(win) < L // 5 * .75 or t + 15 * 60 > end: continue
        hi, lo, p = max(r[2] for r in win), min(r[3] for r in win), rows[i][4]
        w = hi - lo
        if w / p * 100 < 0.5: continue
        side = 1 if p > hi * (1 + conf / 100) else -1 if p < lo * (1 - conf / 100) else 0
        key = (name, dt.date(), side)
        if not side or key in done: continue
        done.add(key)                              # 시간대마다 방향별 한 번
        tgt = p + side * tgtw * w
        stl = (hi - stp * w) if side > 0 else (lo + stp * w)  # 박스 안쪽으로 stp 만큼 되돌아오면 손절
        res = None; last = p
        for r in rows[i + 1:]:
            if r[0] >= end: break
            if (side > 0 and r[3] <= stl) or (side < 0 and r[2] >= stl): last = stl; break
            if (side > 0 and r[2] >= tgt) or (side < 0 and r[3] <= tgt): last = tgt; break
            last = r[4]
        out.append((name, dt.date().isoformat(), side * (last / p - 1) * 100 - COST))
    return out
days = sorted({datetime.fromtimestamp(r[0], ET).date().isoformat() for r in rows}); mid = days[len(days)//2]
res = []
for L, tg, sp, cf, h in itertools.product((30, 60), (0.5, 1.0, 2.0), (0.0, 0.5), (0.0, 0.3), (60, 120)):
    r = run(L, tg, sp, cf, h)
    for sess in ("pre", "post"):
        x = [v for s_, d, v in r if s_ == sess]
        a = [v for s_, d, v in r if s_ == sess and d < mid]; b = [v for s_, d, v in r if s_ == sess and d >= mid]
        if len(a) > 5 and len(b) > 5:
            res.append((sess, L, tg, sp, cf, h, len(x), sum(1 for v in x if v > 0) / len(x) * 100, sum(x) / len(x), sum(a) / len(a), sum(b) / len(b), sum(x)))
for sess in ("pre", "post"):
    rr = [x for x in res if x[0] == sess]
    print(f"{sess}: {len(rr)}개 설정 · 1회 평균 이익 {sum(1 for x in rr if x[8] > 0)} · 앞·뒤 모두 이익 {sum(1 for x in rr if x[9] > 0 and x[10] > 0)}")
    for x in sorted(rr, key=lambda x: -min(x[9], x[10]))[:4]:
        print(f"   박스{x[1]}분 목표{x[2]}폭 손절(안쪽{x[3]}) 확인{x[4]}% {x[5]}분 | {x[6]}회 승률{x[7]:.0f}% 평균{x[8]:+.2f}% (앞 {x[9]:+.2f} 뒤 {x[10]:+.2f}) 합 {x[11]:+.1f}%")
    base = [x for x in rr if x[1:6] == (60, 1.0, 0.0, 0.0, 120)]
    if base: x = base[0]; print(f"   기본(60분 박스, 목표 1폭, 박스로 돌아오면 손절): {x[6]}회 승률{x[7]:.0f}% 평균{x[8]:+.2f}% (앞 {x[9]:+.2f} 뒤 {x[10]:+.2f}) 비용 전 {x[8]+COST:+.2f}%")
