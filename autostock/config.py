"""환경변수(.env) 기반 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


# 모드별 덮어쓰기: PAPER__CAPITAL_KRW 처럼 접두어를 붙인 값이 있으면 그 모드에서는 그것을 쓴다.
PREFIX = {"paper": "PAPER__", "kis-demo": "DEMO__", "live": "LIVE__"}
_prefix = ""


def _raw(name: str) -> str:
    return (os.getenv(_prefix + name) or os.getenv(name) or "").strip() if _prefix else (os.getenv(name) or "").strip()


def _f(name: str, default: float) -> float:
    return float(_raw(name) or default)


def _i(name: str, default: int) -> int:
    return int(_raw(name) or default)


def _s(name: str, default: str = "") -> str:
    return _raw(name) or default


@dataclass(frozen=True)
class KisCreds:
    env: str                 # demo | real
    app_key: str = ""
    app_secret: str = ""
    account_no: str = ""
    account_product: str = "01"

    @property
    def ok(self) -> bool:
        return bool(self.app_key and self.app_secret)


@dataclass(frozen=True)
class Settings:
    mode: str = "paper"                 # paper | kis-demo | live (이 프로세스가 돌리는 모드)
    modes: tuple[str, ...] = ("paper",)  # .env 의 MODE 에 쉼표로 적은 전체 목록 (동시 실행)
    live_confirm: str = ""

    model: str = "claude-opus-5-5"
    effort: str = "medium"
    decision_interval_sec: int = 180

    kis_real: KisCreds = KisCreds("real")
    kis_demo: KisCreds = KisCreds("demo")

    capital_krw: float = 1_000_000
    daily_target_krw: float = 100_000
    daily_max_loss_krw: float = 50_000
    usdkrw: float = 1400.0

    max_stop_loss_pct: float = 2.0
    default_take_profit_pct: float = 3.0
    take_profit_max_pct: float = 10.0   # AI 익절폭 상한 (스캘핑은 작게)
    max_hold_min: float = 0             # 이 시간 넘게 들고 있는데 수수료 이상 못 벌었으면 청산 (0=끔)
    max_trades_per_day: int = 8
    max_consecutive_losses: int = 3
    cooldown_after_loss_min: int = 10
    min_confidence: float = 0.6
    no_entry_after_open_min: int = 5
    no_entry_before_close_min: int = 20
    flatten_before_close_min: int = 5
    fee_pct: float = 0.25
    tick_sec: int = 10
    hold_tick_sec: float = 3            # 보유 중에는 더 자주 가격을 본다 (급락 때 손절이 늦게 걸리지 않게)
    trail_atr_mult: float = 2.5         # 추적 손절 폭 = 1분 ATR × 이 값 (아래 범위로 제한)
    trail_min_pct: float = 0.6
    surge_pct: float = 1.0              # 직전 판단 이후 이만큼 움직이면 주기와 무관하게 AI 를 다시 부른다

    # 판단 참고용 주변 종목(매매하지 않음). 앞의 context_bars 개는 분봉 추세까지 본다.
    context: tuple[str, ...] = ("NVDA", "SOXX", "AMD", "AVGO", "TSM", "MU", "QQQ")
    context_bars: int = 2
    strategy: str = "ai"                # ai(매 판단을 Claude) | orb(개장 범위 돌파 규칙 + Claude 검토 의견)
    ext_strategy: str = ""              # 정규장 밖 세션의 전략 (비우면 strategy 와 같음)
    orb_minutes: int = 20               # 개장 후 이 시간 동안의 고가·저가가 범위
    orb_window_min: int = 120           # 개장 후 이 시간까지만 신규 진입
    orb_max_trades: int = 2
    orb_stop_pct: float = 1.5
    orb_take_pct: float = 10.0
    orb_trail_pct: float = 3.0
    orb_peers: tuple[str, ...] = ("NVDA", "SOXX")   # 돌파 방향으로 같이 움직여야 하는 종목
    orb_stop_mode: str = "pct"          # pct(orb_stop_pct) | mid(개장 범위 중간값 — 진입가 대비 %로 바꿔 보유 종목에 적용)
    vol_filter_min: float = 0.0         # 최근 5일 평균 하루 변동폭(%)이 이보다 작으면 그날 정규장 매매 안 함 (0=끔)
    risk_per_trade_pct: float = 0.0     # 손절까지 가면 잃는 돈이 자본의 이 % 가 되도록 수량을 줄임 (0=끔, 전액 매수)
    noise: bool = False                 # 노이즈 영역 돌파 (30분마다, 지난 14일 같은 시점 평균 움직임 밖이면 추세로 봄)
    noise_lookback: int = 14
    noise_every: int = 30
    noise_stop_pct: float = 6.0         # 30분 확인 사이의 안전 손절
    box: bool = False                   # 범위를 아직 벗어나지 않았으면 경계 근처에서 반대로 매매(박스권)
    box_zone: float = 0.2               # 경계에서 범위 폭의 이 비율 안쪽까지 오면 후보
    box_target: float = 0.8             # 반대 경계 쪽으로 범위 폭의 이 비율 지점에서 익절
    box_stop: float = 0.1               # 경계 바깥으로 범위 폭의 이 비율만큼 벗어나면 손절
    box_max: int = 1                    # 세션당 박스권 거래 수
    box_min_width: float = 5.0          # 범위 폭(%)이 이보다 좁은 날은 박스권 매매 안 함(수수료에 먹힘)
    news_pick: bool = False             # 가상매매 실험: 시간외 '항상 매매' 방향을 뉴스 판단(SOXL/SOXS)으로
    scale_in_frac: float = 1.0          # 돌파 진입 때 처음 살 비율 (1=한 번에). 0.5 면 절반 사고
    scale_in_add_pct: float = 1.0       # 보유 종목이 진입가 대비 이 % 오르면 나머지를 산다
    always_hold_min: float = 30.0       # '항상 매매' 보유 시간 상한(분). 0 이면 손절·익절·세션 마감까지 보유
    always_stop_pct: float = 1.5
    always_take_pct: float = 2.0
    always_cooldown_min: float = 0.0    # 청산 뒤 다시 사기까지 쉬는 시간(분)
    fixed_qty: int = 0                  # >0: '항상 매매(always)' 전략이 사는 고정 수량 (가상매매용)
    box_peer_max: float = 0.0           # >0: 동조 종목(엔비디아·SOXX)이 개장가 대비 반대로 이 % 넘게 움직였으면 박스권 진입 안 함
    box_gap_max: float = 0.0            # >0: 개장 갭이 반대 방향으로 이 % 넘으면 그 방향 박스권 진입 안 함 (갭 하락 날 SOXL 반등 매수 등)
    order_test_symbol: str = ""         # 주문 테스트에 쓸 종목 (비우면 매매 종목)
    order_test_sell: bool = True        # False 면 주문 테스트에서 1주를 사기만 하고 포지션으로 넘긴다
    style: str = "normal"               # normal | aggressive(분 단위 초단타)
    sessions: tuple[str, ...] = ("regular",)   # regular(정규장), pre(프리마켓), day(한국 낮 주간거래)
    bull: str = "SOXL"
    bear: str = "SOXS"
    data_dir: str = "data"

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(s for s in (self.bull, self.bear) if s)

    @property
    def capital_usd(self) -> float:
        return self.capital_krw / self.usdkrw

    @property
    def target_usd(self) -> float:
        return self.daily_target_krw / self.usdkrw

    @property
    def max_loss_usd(self) -> float:
        return self.daily_max_loss_krw / self.usdkrw


def _creds(env: str) -> KisCreds:
    """KIS_REAL_* / KIS_DEMO_* 를 읽는다. 예전 방식(KIS_APP_KEY + KIS_ENV)도 받아준다."""
    p = f"KIS_{env.upper()}_"
    if not _s(p + "APP_KEY") and _s("KIS_APP_KEY") and _s("KIS_ENV", "demo") == env:
        p = "KIS_"
    return KisCreds(env, _s(p + "APP_KEY"), _s(p + "APP_SECRET"), _s(p + "ACCOUNT_NO"),
                    _s(p + "ACCOUNT_PRODUCT", "01"))


def load(mode: str | None = None) -> Settings:
    """mode 를 주면 그 모드의 덮어쓰기(PAPER__/DEMO__/LIVE__)를 적용한 설정을 돌려준다."""
    global _prefix
    load_dotenv()
    _prefix = ""
    modes = tuple(m.strip() for m in _s("MODE", "paper").split(",") if m.strip()) or ("paper",)
    mode = mode or modes[0]
    _prefix = PREFIX.get(mode, "")
    try:
        return _build(mode, modes)
    finally:
        _prefix = ""


def _build(mode: str, modes: tuple[str, ...]) -> Settings:
    return Settings(
        mode=mode,
        modes=modes,
        style=_s("STYLE", "normal"),
        order_test_symbol=_s("ORDER_TEST_SYMBOL").upper(),
        strategy=_s("STRATEGY", "ai").lower(),
        ext_strategy=_s("EXT_STRATEGY").lower(),
        orb_minutes=_i("ORB_MINUTES", 20),
        orb_window_min=_i("ORB_WINDOW_MIN", 120),
        orb_max_trades=_i("ORB_MAX_TRADES", 2),
        orb_stop_pct=_f("ORB_STOP_PCT", 1.5),
        orb_take_pct=_f("ORB_TAKE_PCT", 10.0),
        orb_trail_pct=_f("ORB_TRAIL_PCT", 3.0),
        orb_peers=tuple(x.strip().upper() for x in _s("ORB_PEERS", "NVDA,SOXX").split(",") if x.strip()),
        orb_stop_mode=_s("ORB_STOP_MODE", "pct").lower(),
        vol_filter_min=_f("VOL_FILTER_MIN", 0.0),
        risk_per_trade_pct=_f("RISK_PER_TRADE_PCT", 0.0),
        noise=_s("NOISE", "false").lower() in ("true", "1", "yes"),
        noise_lookback=_i("NOISE_LOOKBACK", 14),
        noise_every=_i("NOISE_EVERY", 30),
        noise_stop_pct=_f("NOISE_STOP_PCT", 6.0),
        box=_s("BOX", "false").lower() in ("true", "1", "yes"),
        box_zone=_f("BOX_ZONE", 0.2),
        box_target=_f("BOX_TARGET", 0.8),
        box_stop=_f("BOX_STOP", 0.1),
        box_max=_i("BOX_MAX", 1),
        fixed_qty=_i("FIXED_QTY", 0),
        always_hold_min=_f("ALWAYS_HOLD_MIN", 30.0),
        always_stop_pct=_f("ALWAYS_STOP_PCT", 1.5),
        always_take_pct=_f("ALWAYS_TAKE_PCT", 2.0),
        always_cooldown_min=_f("ALWAYS_COOLDOWN_MIN", 0.0),
        scale_in_frac=_f("SCALE_IN_FRAC", 1.0),
        scale_in_add_pct=_f("SCALE_IN_ADD_PCT", 1.0),
        news_pick=_s("NEWS_PICK", "false").lower() in ("1", "true", "yes"),
        box_peer_max=_f("BOX_PEER_MAX", 0.0),
        box_gap_max=_f("BOX_GAP_MAX", 0.0),
        box_min_width=_f("BOX_MIN_WIDTH", 5.0),
        order_test_sell=_s("ORDER_TEST_SELL", "true").lower() not in ("false", "0", "no"),
        live_confirm=_s("LIVE_TRADING_CONFIRM"),
        model=_s("CLAUDE_MODEL", "claude-opus-5-5"),
        effort=_s("CLAUDE_EFFORT", "medium"),
        decision_interval_sec=_i("DECISION_INTERVAL_SEC", 180),
        kis_real=_creds("real"),
        kis_demo=_creds("demo"),
        capital_krw=_f("CAPITAL_KRW", 1_000_000),
        daily_target_krw=_f("DAILY_TARGET_KRW", 100_000),
        daily_max_loss_krw=_f("DAILY_MAX_LOSS_KRW", 50_000),
        usdkrw=_f("USDKRW", 1400),
        max_stop_loss_pct=_f("MAX_STOP_LOSS_PCT", 2.0),
        default_take_profit_pct=_f("DEFAULT_TAKE_PROFIT_PCT", 3.0),
        take_profit_max_pct=_f("TAKE_PROFIT_MAX_PCT", 10.0),
        max_hold_min=_f("MAX_HOLD_MIN", 0),
        max_trades_per_day=_i("MAX_TRADES_PER_DAY", 8),
        max_consecutive_losses=_i("MAX_CONSECUTIVE_LOSSES", 3),
        cooldown_after_loss_min=_i("COOLDOWN_AFTER_LOSS_MIN", 10),
        min_confidence=_f("MIN_CONFIDENCE", 0.6),
        no_entry_after_open_min=_i("NO_ENTRY_AFTER_OPEN_MIN", 5),
        no_entry_before_close_min=_i("NO_ENTRY_BEFORE_CLOSE_MIN", 20),
        flatten_before_close_min=_i("FLATTEN_BEFORE_CLOSE_MIN", 5),
        fee_pct=_f("FEE_PCT", 0.25),
        tick_sec=_i("TICK_SEC", 10),
        hold_tick_sec=_f("HOLD_TICK_SEC", 3),
        bull=_s("BULL_SYMBOL", "SOXL").upper(),
        bear="" if _s("BEAR_SYMBOL", "SOXS").upper() in ("NONE", "-") else _s("BEAR_SYMBOL", "SOXS").upper(),
        trail_atr_mult=_f("TRAIL_ATR_MULT", 2.5),
        trail_min_pct=_f("TRAIL_MIN_PCT", 0.6),
        surge_pct=_f("SURGE_PCT", 1.0),
        sessions=tuple(x.strip() for x in _s("SESSIONS", "regular").split(",")
                       if x.strip() in ("regular", "day", "pre", "post")) or ("regular",),
        context=tuple(x.strip().upper() for x in _s("CONTEXT_SYMBOLS", "NVDA,SOXX,AMD,AVGO,TSM,MU,QQQ").split(",")
                      if x.strip() and x.strip().upper() not in (_s("BULL_SYMBOL", "SOXL").upper(),
                                                                 _s("BEAR_SYMBOL", "SOXS").upper())),
    )
