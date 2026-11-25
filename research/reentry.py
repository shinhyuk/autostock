"""돌파 재진입: 진입 마감 시간(개장 후 60/120/390분)과 하루 돌파 횟수(2/3/5) 비교. 돌파 + 박스권 하루 1회, 익절 10%."""
import sys
sys.argv = ["code/box.py", "data"]; sys.path.insert(0, "code")
import box, multi
from multi import PAIRS
def runset(n, per_min, label):
    print(f"\n{label}")
    b, s, pe, k = [p for p in PAIRS if p[0] == "SOXL"][0]
    d = multi.build(b, s, pe); h = len(d) // 2
    for win in (60, 120, 390):
        for mx in (2, 3, 5):
            orb = dict(n=n, peer=1, stop="mid", sl=1.5, tp=10, window=win // per_min, maxtr=mx)
            bx = dict(n=n, z=0.2, t=0.8, s=0.1, maxtr=1, wmin=5, tmax=0)
            r = box.run(d, {"orb": orb, "box": bx}); o = box.stats(r, "orb")
            print(f"  진입 마감 {win:3d}분 · 하루 {mx}회: 전체 {box.stats(r)['ret']:+6.1f}% · 돌파 {o['ret']:+6.1f}% ({o['n']}회 승률 {o['win']}%) · 앞 {box.stats(r[:h])['ret']:+5.1f} 뒤 {box.stats(r[h:])['ret']:+5.1f}")
import shutil, glob
for f in glob.glob("data_nov23/*_1m.json"): shutil.copy(f, "data/")
runset(20, 1, "1분봉 (10/26~11/25)")
multi.TF, multi.MINBARS, multi.D = "5m", 70, "data5"; multi._c.clear()
runset(4, 5, "5분봉 60일 (8/31~11/20)")
