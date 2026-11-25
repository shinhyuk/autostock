"""돌파 익절 % 비교: 1분봉 21일(엔비디아·SOXX 동조) + 5분봉 60일. 모의·실계좌와 같은 돌파+박스권(하루 1회)."""
import sys, statistics
sys.argv = ["code/box.py", "data"]; sys.path.insert(0, "code")
import box, multi
from multi import PAIRS
def runset(D, n, win, label):
    print(f"\n{label}")
    b, s, pe, k = [p for p in PAIRS if p[0] == "SOXL"][0]
    d = multi.build(b, s, pe)
    h = len(d) // 2
    for tp in (4, 6, 8, 10, 15, 30):
        orb = dict(n=n, peer=1, stop="mid", sl=1.5, tp=tp, window=win, maxtr=2)
        bx = dict(n=n, z=0.2, t=0.8, s=0.1, maxtr=1, wmin=5, tmax=0)
        r = box.run(d, {"orb": orb, "box": bx}); o = box.stats(r, "orb")
        print(f"  익절 {tp:2d}%: 전체 {box.stats(r)['ret']:+6.1f}% · 돌파분 {o['ret']:+6.1f}% ({o['n']}회 승률 {o['win']}%) · 앞 {box.stats(r[:h])['ret']:+5.1f} 뒤 {box.stats(r[h:])['ret']:+5.1f}")
runset("data", 20, 60, "1분봉 (10/26~11/24 근처)")
multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
runset("data5", 4, 12, "5분봉 60일 (8/31~11/20)")
