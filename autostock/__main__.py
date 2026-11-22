from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

from . import config
from .brain import ClaudeBrain, RuleBrain
from .engine import Engine


def main() -> int:
    ap = argparse.ArgumentParser(prog="autostock", description="SOXL/SOXS AI 단타 자동매매")
    ap.add_argument("--mode", choices=["paper", "kis-demo", "live"], help=".env의 MODE 대신 사용")
    ap.add_argument("--brain", choices=["claude", "rule"], default="claude",
                    help="rule = API 비용 없이 단순 규칙으로 배선 점검")
    ap.add_argument("--simulate", type=int, metavar="MINUTES", default=0,
                    help="가짜 랜덤 시세로 N분을 빠르게 돌려보기 (증권사/장 시간 불필요)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname).1s %(name)s  %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load()
    if a.mode:
        cfg = dataclasses.replace(cfg, mode=a.mode)
    brain = RuleBrain(cfg) if a.brain == "rule" else ClaudeBrain(cfg)

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
    if cfg.mode == "live":
        if cfg.live_confirm != "I_UNDERSTAND" or cfg.kis_env != "real":
            print("실계좌 모드는 .env에 LIVE_TRADING_CONFIRM=I_UNDERSTAND 와 KIS_ENV=real 이 모두 필요합니다.",
                  file=sys.stderr)
            return 2
    elif cfg.mode == "kis-demo" and cfg.kis_env != "demo":
        print("kis-demo 모드는 KIS_ENV=demo(모의투자 키)여야 합니다.", file=sys.stderr)
        return 2

    client = KISClient(cfg.kis_app_key, cfg.kis_app_secret, cfg.kis_env, cfg.data_dir)
    market = KISMarket(client)
    if cfg.mode == "paper":
        broker = PaperBroker()
        eng = Engine(cfg, market, broker, brain)
        if t := eng.st.open:              # 가상 포지션은 상태 파일에서 복원
            broker.restore(t.symbol, t.qty, t.entry_price)
    else:
        broker = KISBroker(client, cfg.kis_account_no, cfg.kis_account_product)
        eng = Engine(cfg, market, broker, brain)

    logging.getLogger("engine").info(
        "모드=%s  자금 %s원 ($%.0f)  목표 +%s원  손실한도 -%s원  AI=%s",
        cfg.mode, f"{cfg.capital_krw:,.0f}", cfg.capital_usd, f"{cfg.daily_target_krw:,.0f}",
        f"{cfg.daily_max_loss_krw:,.0f}", cfg.model if a.brain == "claude" else "rule")
    try:
        eng.run()
    except KeyboardInterrupt:
        print("\n중단됨. 보유 포지션:", eng.st.open or "없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
