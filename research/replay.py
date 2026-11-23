"""실제 1분봉을 봇 엔진에 재생해서 백테스트와 같은 매매를 하는지 비교한다."""
import sys, json, datetime, zoneinfo, dataclasses, tempfile, logging
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from autostock.config import Settings
from autostock.engine import Engine
from autostock.brokers.paper import PaperBroker
from autostock.models import Bar, Quote, HOLD
from bt import build, run, STRATS
import bt
ET = zoneinfo.ZoneInfo("America/New_York")
logging.basicConfig(level=logging.WARNING)
raw = {s: {t: v for t, *v in json.load(open(f"{sys.argv[3]}/{s}_1m.json"))} for s in ("SOXL", "SOXS", "NVDA", "SOXX")}
series = {s: sorted(raw[s]) for s in raw}


class Replay:
    def __init__(self): self.now = None
    def _upto(self, s):
        cut = self.now.timestamp()
        return [t for t in series[s] if t + 60 <= cut]            # 다 끝난 봉만
    def quote(self, s):
        ts = self._upto(s); t = ts[-1]
        return Quote(s, raw[s][t][3], raw[s][t][3])
    def bars(self, s, n=120):
        return [Bar(datetime.datetime.fromtimestamp(t, ET), *raw[s][t][:4], raw[s][t][4]) for t in self._upto(s)[-n:]]


class NoAI:
    def decide(self, snap): return HOLD


P = dict(n=20, peer=1, tp=10, sl=1.5, trail=3.0, window=120, maxtr=2, hold=0)
days = build(sys.argv[3])
bt.SLIP = 0.0005            # 가상 체결 슬리피지와 맞춤
ok = 0
for day in days:
    d0 = day["date"]
    cfg = dataclasses.replace(Settings(), data_dir=tempfile.mkdtemp(), strategy="orb", capital_krw=10_000_000,
                              daily_target_krw=1_000_000, daily_max_loss_krw=1_000_000, max_stop_loss_pct=1.5,
                              take_profit_max_pct=10, orb_minutes=20, orb_window_min=120, orb_max_trades=2,
                              orb_stop_pct=1.5, orb_take_pct=10, orb_trail_pct=3, max_trades_per_day=16, tick_sec=60)
    m = Replay()
    m.now = datetime.datetime.combine(d0, datetime.time(9, 30), ET)
    e = Engine(cfg, m, PaperBroker(slippage_pct=0.05), NoAI(), clock=lambda: m.now)
    e.snapshot = lambda now: {}
    while m.now.time() < datetime.time(16, 0):
        m.now += datetime.timedelta(seconds=20)
        try:
            e.tick()
        except Exception as ex:
            print("ERR", d0, ex); break
    eng = [(h["symbol"], h["reason"].split(" ")[0], round(h["pnl_usd"] * 1400 / 1e4)) for h in e.st.history]
    btr = run([day], STRATS["orb2"], P)[0][2]
    btt = [("SOXL" if s == "L" else "SOXS", w, round(net * 1400 / 1e4)) for s, w, net, _ in btr]
    same = [x[0] for x in eng] == [x[0] for x in btt]
    ok += same
    print(d0, "같음" if same else "다름", "| 엔진:", eng, "| 백테스트:", btt)
print(f"\n종목·순서 일치 {ok}/{len(days)}일")
