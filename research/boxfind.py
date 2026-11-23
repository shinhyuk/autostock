"""고정 박스 찾기 실험: 경계 터치 2회 이상, 박스는 종가 2봉 이탈 때까지 고정. 옛 방식(직전 60분 고저)과 박스 매매 결과 비교."""
import json, sys, statistics
from datetime import datetime
sys.path.insert(0, '/home/user/autostock')
from autostock import extbox
ET = extbox.ET

def find_boxes(rows, step, min_min=30, max_min=120, tol=0.2, wmin=0.6, wmax=5.0, touches=2, out_n=2, out_m=0.1):
    """rows [[ts,o,h,l,c]] 시간순. 각 봉 시점의 활성 박스를 돌려준다: list of (hi, lo) or None (그 봉 '이전'까지로 만든 박스)."""
    res, box, outside, frm = [], None, 0, 0
    nmin, nmax = max(3, min_min // step), max_min // step
    for i in range(len(rows)):
        res.append(box)                         # i 봉 시점에 쓸 수 있는 박스 (i-1 까지의 정보)
        r = rows[i]
        if i and r[0] - rows[i - 1][0] > 3600:  # 큰 공백(밤사이)이면 새로 시작
            box, outside, frm = None, 0, i
        if box:
            hi, lo = box; w = hi - lo
            outside = outside + 1 if (r[4] > hi + out_m * w or r[4] < lo - out_m * w) else 0
            if outside >= out_n:
                box, outside, frm = None, 0, i - out_n + 1
            continue
        for n in range(min(nmax, i + 1 - frm), nmin - 1, -1):
            win = rows[i - n + 1:i + 1]
            hs = sorted(x[2] for x in win); ls = sorted(x[3] for x in win)
            hi, lo = hs[-2], ls[1]               # 꼬리 한 번은 무시
            w = hi - lo; mid = (hi + lo) / 2
            if not (wmin <= w / mid * 100 <= wmax): continue
            if any(x[4] > hi + out_m * w or x[4] < lo - out_m * w for x in win): continue
            def grp(flags):
                g, prev = 0, False
                for f in flags:
                    if f and not prev: g += 1
                    prev = f
                return g
            if grp([x[2] >= hi - tol * w for x in win]) >= touches and grp([x[3] <= lo + tol * w for x in win]) >= touches:
                box = (hi, lo); break
    return res

def rolling(rows, step):
    res = []
    for i in range(len(rows)):
        t = rows[i][0]; win = [r for r in rows[max(0, i - 60 // step - 3):i] if t - 3600 <= r[0] < t]
        res.append((max(r[2] for r in win), min(r[3] for r in win)) if len(win) >= 60 // step * .75 else None)
    return res

def trades(rows, boxes, cost=0.7):
    out, last = [], {}
    for i, r in enumerate(rows):
        t = r[0]; dt = datetime.fromtimestamp(t, ET); s = extbox.session(dt); b = boxes[i]
        if not s or not b: last.pop(s[0] if s else None, None); continue
        hi, lo = b; p = r[4]; w = hi - lo
        z = extbox.zone(p, hi, lo); key = (s[0], dt.date())
        prev, last[key] = last.get(key), (z, b)
        if z not in ("top", "bottom") or prev == (z, b): continue
        end = min(s[2].timestamp(), t + 7200)
        if t + 900 > end: continue
        long = z == "bottom"
        tgt = lo + .8 * w if long else hi - .8 * w; stp = lo - .1 * w if long else hi + .1 * w
        res, lastp = "none", p
        for x in rows[i + 1:]:
            if x[0] >= end: break
            if (long and x[3] <= stp) or (not long and x[2] >= stp): res, lastp = "loss", stp; break
            if (long and x[2] >= tgt) or (not long and x[3] <= tgt): res, lastp = "win", tgt; break
            lastp = x[4]
        out.append((s[0], dt.date().isoformat(), res, (lastp / p - 1) * 100 * (1 if long else -1) - cost, w / p * 100))
    return out

def summ(name, tr, mid):
    for sess in ("pre", "post"):
        x = [t for t in tr if t[0] == sess]
        if not x: print(f"  {name} {sess}: 없음"); continue
        a = [t[3] for t in x if t[1] < mid]; b = [t[3] for t in x if t[1] >= mid]
        m = lambda v: f"{statistics.mean(v):+.2f}" if v else " - "
        print(f"  {name:10s} {sess:4s} {len(x):4d}회 목표 {sum(t[2]=='win' for t in x)/len(x)*100:3.0f}% 손절 {sum(t[2]=='loss' for t in x)/len(x)*100:3.0f}% "
              f"평균 {statistics.mean(t[3] for t in x):+.2f}% (앞 {m(a)} 뒤 {m(b)}) 비용 전 {statistics.mean(t[3] for t in x)+.7:+.2f}% 폭 {statistics.median(t[4] for t in x):.1f}%")

for path, step in ((sys.argv[1], 5), (sys.argv[2], 1)):
    rows = [r[:5] for r in json.load(open(path))]
    days = sorted({datetime.fromtimestamp(r[0], ET).date().isoformat() for r in rows}); mid = days[len(days) // 2]
    print(f"{path.split('/')[-1]} {step}분봉 {days[0]}~{days[-1]}")
    summ("직전60분", trades(rows, rolling(rows, step)), mid)
    for kw in (dict(), dict(touches=3), dict(min_min=45, max_min=180), dict(wmin=1.0)):
        summ("고정 " + ",".join(f"{k}={v}" for k, v in kw.items()), trades(rows, find_boxes(rows, step, **kw)), mid)
