"""프리마켓 갭(09:00 기준)을 보고 정규장 개장 09:30 에 진입 → 10:30 / 장 마감. 2년 1시간봉."""
import runpy, sys, io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): g = runpy.run_path("code/ext2y.py")
L, tr, show = g["L"], g["tr"], g["show"]
for th in (1, 2, 3, 5):
    for mode in (1, -1):
        for ex in ((10, 30), (15, 30)):
            def f(p, d, n, th=th, mode=mode, ex=ex):
                try: gp = (L[d][(9, 0)][3] / L[p][(15, 30)][3] - 1) * 100
                except KeyError: return None
                if abs(gp) < th: return None
                return tr(mode * (1 if gp > 0 else -1), d, (9, 30), 0, d, ex, 0 if ex == (10, 30) else 3, 0.1)
            show(f"갭 {th}%↑ {'추종' if mode > 0 else '되돌림'} 09:30 → {'10:30' if ex == (10, 30) else '16:00'}", f)
