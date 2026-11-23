"""20거래일 날짜별 거래 내역: 돌파 기존(가상매매) / 돌파 개선+박스권(모의투자, 필터·금액조절 없음)."""
import sys, datetime, zoneinfo
sys.argv = ["code/box.py", "data"]; sys.path.insert(0, "code")
import multi, box
ET, KST = zoneinfo.ZoneInfo("America/New_York"), zoneinfo.ZoneInfo("Asia/Seoul")
src_m = open("code/multi.py").read(); src_b = open("code/box.py").read()
# 거래마다 상세 기록을 남기도록 실행 함수를 복사해 고친다
src_m = src_m.split("PAIRS = [")[0]
src_m = src_m.replace("pos = (side, qty, ent, ent, ent * (1 - slp / 100), ent * (1 + p[\"tp\"] / 100))",
                      "pos = (side, qty, ent, ent, ent * (1 - slp / 100), ent * (1 + p[\"tp\"] / 100)); info = (i + 1,)")
src_m = src_m.replace("if l <= stop:\n                    ex = min(o, stop)", "if l <= stop:\n                    ex = min(o, stop); why = '손절'")
src_m = src_m.replace("elif h >= take:\n                    ex = max(o, take)", "elif h >= take:\n                    ex = max(o, take); why = '익절'")
src_m = src_m.replace("ex = min(o, peak * (1 - tr / 100))", "ex = min(o, peak * (1 - tr / 100)); why = '추적손절'")
src_m = src_m.replace("ex = c\n                pos = (side", "ex = c; why = '마감청산'\n                pos = (side")
src_m = src_m.replace("pnl += net; trades.append(net); pos = None",
                      "pnl += net; trades.append(dict(kind='돌파', side=side, t0=info[0], t1=i, p0=ent, p1=px, qty=qty, why=why, net=net)); pos = None")
ns = {}; exec(src_m, ns)
src_b = src_b.split('if __name__')[0].replace("import multi\nfrom multi import build, st, CAP, SLIP, PAIRS", "import multi\nfrom multi import CAP, SLIP")
src_b = src_b.replace("ex = min(o, stopP)", "ex = min(o, stopP); why = '손절'").replace("ex = max(o, takeP)", "ex = max(o, takeP); why = '익절'")
src_b = src_b.replace("                    ex = c\n                if ex is not None:", "                    ex = c; why = '마감청산'\n                if ex is not None:")
src_b = src_b.replace("pnl += net; trades.append((kind, net)); pos = None",
                      "pnl += net; trades.append(dict(kind='돌파' if kind == 'orb' else '박스권', side=side, t0=i0, t1=i, p0=ent, p1=px, qty=qty, why=why, net=net)); pos = None")
nb = {"multi": multi}; exec(src_b, nb)
d = multi.build("SOXL", "SOXS", ("NVDA", "SOXX"))
import json
ts = {dd["date"]: [t for t in sorted(multi.load("SOXL")) if (9, 30) <= (datetime.datetime.fromtimestamp(t, ET).hour, datetime.datetime.fromtimestamp(t, ET).minute) < (16, 0) and datetime.datetime.fromtimestamp(t, ET).date() == dd["date"]] for dd in d}
OLD = dict(n=20, peer=1, stop="pct", window=120, maxtr=2, sl=1.5, tp=10, trail=3.0)
NEW = {"orb": dict(n=20, peer=1, stop="mid", sl=1.5, tp=10, window=60, maxtr=2), "box": dict(n=20, z=0.2, t=0.8, s=0.1, maxtr=1, tmax=0, wmin=5)}
ro, rn = ns["run"](d, OLD), nb["run"](d, NEW)
def hm(day, i):
    return datetime.datetime.fromtimestamp(ts[day][min(i, len(ts[day]) - 1)], ET).astimezone(KST).strftime("%H:%M")
def line(day, t):
    sym = "SOXL" if t["side"] == "L" else "SOXS"
    return (f"{t['kind']} {sym} {t['qty']}주 {hm(day, t['t0'])} ${t['p0']:.2f} → {hm(day, t['t1'])} ${t['p1']:.2f} "
            f"{t['why']} {t['net'] * 1400 / 1e4:+.0f}만")
md = ["| 미국 날짜 | 범위 (20분) | 지금 가상매매 (돌파 기존) | 손익 | 모의투자 (돌파 개선 + 박스권) | 손익 |", "|---|---|---|---|---|---|"]
to = tn = 0
for (day, po, tro), (_, pn, trn) in zip(ro, rn):
    L = [dd for dd in d if dd["date"] == day][0]["L"]
    hh, ll = max(b[1] for b in L[:20]), min(b[2] for b in L[:20])
    to += po; tn += pn
    md.append(f"| {day:%m/%d} ({'월화수목금'[day.weekday()]}) | ${ll:.2f}~${hh:.2f} ({(hh - ll) / ll * 100:.1f}%) | "
              f"{'<br>'.join(line(day, t) for t in tro) or '거래 없음'} | **{po * 1400 / 1e4:+.0f}만** | "
              f"{'<br>'.join(line(day, t) for t in trn) or '거래 없음'} | **{pn * 1400 / 1e4:+.0f}만** |")
md.append(f"| **합계** | | | **{to * 1400 / 1e4:+.0f}만 → {(1e7 + to * 1400) / 1e4:,.0f}만원** | | **{tn * 1400 / 1e4:+.0f}만 → {(1e7 + tn * 1400) / 1e4:,.0f}만원** |")
open(sys.argv[0].rsplit("/", 1)[0] + "/../daily.md", "w").write("\n".join(md) + "\n")
print("\n".join(md))
