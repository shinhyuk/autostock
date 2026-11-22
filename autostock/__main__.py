from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

from . import config
from .brain import ClaudeBrain, RuleBrain
from .engine import Engine, order_test


def check(cfg, market, client) -> int:
    """Claude 키, KIS 시세, 계좌 조회를 차례로 점검한다. 주문은 내지 않는다."""
    from .brokers.kis import KISBroker
    bad = 0

    def step(name, fn):
        nonlocal bad
        try:
            print(f"[OK]   {name}: {fn()}")
        except Exception as e:               # 점검 도구이므로 어떤 오류든 보여주고 계속
            bad += 1
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")

    def claude():
        import anthropic
        return anthropic.Anthropic().models.retrieve(cfg.model).display_name

    def bars():
        b = market.bars(cfg.bull)
        if not b:
            raise RuntimeError("분봉이 비어 있음")
        return f"{len(b)}개, 마지막 {b[-1].ts:%m-%d %H:%M} ET 종가 {b[-1].close}"

    def account(c):
        def run():
            if len(c.account_no) != 8:
                raise ValueError("계좌번호 앞 8자리가 필요")
            br = KISBroker(client(c), c.account_no, c.account_product)
            return {s: (p.qty if (p := br.position(s)) else 0) for s in cfg.symbols}
        return run

    step("Claude API 키 / 모델", claude)
    step(f"KIS 시세 ({market.c.env} 서버) {cfg.bull} 현재가", lambda: market.quote(cfg.bull))
    step(f"KIS 시세 {cfg.bear} 현재가", lambda: market.quote(cfg.bear))
    step("KIS 1분봉", bars)
    for c in (cfg.kis_demo, cfg.kis_real):
        if c.ok:
            step(f"KIS {'모의투자' if c.env == 'demo' else '실전'} 계좌 잔고 조회", account(c))
        else:
            print(f"[--]   KIS {c.env} 키 없음 (건너뜀)")
    print("\n모두 정상입니다." if not bad else f"\n{bad}개 항목 실패.")
    return 1 if bad else 0


def supervise(modes) -> int:
    """MODE 에 여러 모드가 있으면 모드마다 프로세스를 하나씩 띄우고, 죽으면 다시 띄운다."""
    import subprocess
    import time
    log = logging.getLogger("supervisor")
    procs: dict[str, subprocess.Popen] = {}
    try:
        while True:
            for m in modes:
                p = procs.get(m)
                if p is None or p.poll() is not None:
                    if p is not None:
                        log.warning("%s 프로세스 종료(코드 %s) — 다시 시작", m, p.returncode)
                    procs[m] = subprocess.Popen([sys.executable, "-m", "autostock", "--mode", m] + sys.argv[1:])
            time.sleep(15)
    finally:
        for p in procs.values():
            p.terminate()


def main() -> int:
    ap = argparse.ArgumentParser(prog="autostock", description="SOXL/SOXS AI 단타 자동매매")
    ap.add_argument("--mode", choices=["paper", "kis-demo", "live"], help=".env의 MODE 대신 사용")
    ap.add_argument("--brain", choices=["claude", "rule"], default="claude",
                    help="rule = API 비용 없이 단순 규칙으로 배선 점검")
    ap.add_argument("--simulate", type=int, metavar="MINUTES", default=0,
                    help="가짜 랜덤 시세로 N분을 빠르게 돌려보기 (증권사/장 시간 불필요)")
    ap.add_argument("--max-minutes", type=float, default=0,
                    help="이 시간이 지나면 종료 코드 75로 끝냄 (다음 실행이 이어받는 용도)")
    ap.add_argument("--exit-when-closed", action="store_true", help="장이 끝나면 대기하지 않고 종료")
    ap.add_argument("--check", action="store_true", help="키와 연결만 점검하고 종료 (주문 없음)")
    ap.add_argument("--order-test", action="store_true",
                    help="kis-demo/live 모드에서 1주 매수→매도로 주문 경로 확인")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname).1s %(name)s  %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load()
    bad = [m for m in cfg.modes if m not in ("paper", "kis-demo", "live")]
    if bad:
        print(f".env 의 MODE 값이 잘못됐습니다: {bad}", file=sys.stderr)
        return 2
    if a.mode:
        cfg = dataclasses.replace(cfg, mode=a.mode)
    elif len(cfg.modes) > 1 and not (a.simulate or a.check or a.order_test):
        return supervise(cfg.modes)
    brain = None if a.check or a.order_test else RuleBrain(cfg) if a.brain == "rule" else ClaudeBrain(cfg)

    if a.simulate:
        from .brokers.paper import FakeMarket, PaperBroker
        cfg = dataclasses.replace(cfg, mode="sim", decision_interval_sec=max(cfg.decision_interval_sec, 60))
        mkt = FakeMarket(cfg.bull, cfg.bear, seed=a.seed)
        eng = Engine(cfg, mkt, PaperBroker(), brain, clock=lambda: mkt.now)
        eng.st.__init__()                 # 시뮬레이션은 매번 새 상태로
        for _ in range(a.simulate):
            eng.tick()
            mkt.step()
        st = eng.st
        print(f"\n[시뮬레이션 {a.simulate}분] 거래 {st.trades}회 (승 {st.wins} / 패 {st.losses}), "
              f"실현손익 ${st.realized_usd:+.2f} ({eng._krw(st.realized_usd)}), 종료사유: {st.halted or '-'}")
        return 0

    from .brokers.kis import KISBroker, KISClient, KISMarket
    from .brokers.paper import PaperBroker
    real, demo = cfg.kis_real, cfg.kis_demo
    if cfg.mode == "live" and cfg.live_confirm != "I_UNDERSTAND":
        print("실계좌 모드는 .env에 LIVE_TRADING_CONFIRM=I_UNDERSTAND 가 필요합니다.", file=sys.stderr)
        return 2
    need = {"live": real, "kis-demo": demo}.get(cfg.mode)
    if need and not (need.ok and need.account_no):
        print(f"{cfg.mode} 모드는 .env에 KIS_{need.env.upper()}_APP_KEY / _APP_SECRET / _ACCOUNT_NO 가 필요합니다.",
              file=sys.stderr)
        return 2
    if not (real.ok or demo.ok):
        print(".env에 KIS 키가 없습니다 (KIS_REAL_* 또는 KIS_DEMO_*).", file=sys.stderr)
        return 2

    def client(c):
        return KISClient(c.app_key, c.app_secret, c.env, cfg.data_dir)

    # 시세는 실전 키가 있으면 실전 서버에서 가져온다(분봉 조회는 모의투자 서버가 지원하지 않을 수 있음).
    # 시세 조회는 주문과 무관하므로 실전 키를 써도 돈이 움직이지 않는다.
    md = client(real if real.ok else demo)
    market = KISMarket(md)
    if a.check:
        return check(cfg, market, client)
    if a.order_test and cfg.mode == "paper":
        print("주문 테스트는 kis-demo 또는 live 모드에서만 됩니다. 먼저 ./bot mode kis-demo", file=sys.stderr)
        return 2
    if cfg.mode == "paper":
        broker = PaperBroker()
        eng = Engine(cfg, market, broker, brain)
        if t := eng.st.open:              # 가상 포지션은 상태 파일에서 복원
            broker.restore(t.symbol, t.qty, t.entry_price)
    else:
        c = need
        broker = KISBroker(md if c.env == md.env else client(c), c.account_no, c.account_product)
        if a.order_test:
            from .market_hours import is_open, now_et
            if not is_open(now_et()):
                print("정규장 시간(09:30~16:00 ET, 한국시간 밤 11:30~새벽 6:00)에만 테스트할 수 있습니다.")
                return 2
            ok = order_test(cfg, market, broker, out=print)
            print("\n주문 경로 정상입니다." if ok else "\n주문 테스트 실패.")
            return 0 if ok else 1
        eng = Engine(cfg, market, broker, brain)

    logging.getLogger("engine").info(
        "모드=%s  자금 %s원 ($%.0f)  목표 +%s원  손실한도 -%s원  AI=%s",
        cfg.mode, f"{cfg.capital_krw:,.0f}", cfg.capital_usd, f"{cfg.daily_target_krw:,.0f}",
        f"{cfg.daily_max_loss_krw:,.0f}", cfg.model if a.brain == "claude" else "rule")
    try:
        if eng.run(a.max_minutes, a.exit_when_closed) == "handoff":
            return 75
    except KeyboardInterrupt:
        print("\n중단됨. 보유 포지션:", eng.st.open or "없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
