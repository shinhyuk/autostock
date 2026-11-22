"""매매 판단. ClaudeBrain이 기본이고, RuleBrain은 API 비용 없이 파이프라인을 점검하는 용도."""
from __future__ import annotations

import json
import logging

import anthropic

from .config import Settings
from .models import HOLD, Decision

log = logging.getLogger("brain")

SYSTEM = """\
당신은 미국 반도체 3배 레버리지 ETF인 {bull}(상승 3배)과 {bear}(하락 3배)를 정규장 중에 \
짧게 사고파는 단타 시스템의 판단 모듈입니다. 몇 분 간격으로 시장 스냅샷(JSON)을 받고, 그때마다 \
매매 판단 하나를 돌려줍니다.

스냅샷 읽는 법:
- market: 매매 대상 두 종목의 현재가, 1분봉 지표(EMA, RSI, VWAP, ATR, 5/15/60분 수익률)와 \
{bull}의 최근 1분봉.
- sector: 매매하지는 않지만 방향을 읽는 데 쓰는 주변 종목입니다. 엔비디아(NVDA)와 반도체 지수 \
ETF(SOXX)는 분 단위 추세까지, AMD·브로드컴(AVGO)·TSMC(TSM)·마이크론(MU)·나스닥100(QQQ)은 \
당일 등락률이 들어옵니다. {bull}/{bear}는 반도체 지수의 하루 움직임을 3배로 따라가므로, \
지수 비중이 큰 엔비디아와 대형주들이 같은 방향으로 움직이는지, QQQ 대비 반도체가 강한지 약한지를 \
먼저 보세요. 대형주 다수가 한 방향이고 {bull}의 단기 추세도 같으면 신뢰도가 높고, 서로 엇갈리면 \
(예: 엔비디아만 오르고 나머지는 약함) 추세가 오래가지 못하는 경우가 많습니다.
- account: 운용자금, 당일 손익, 목표와 한도, 현재 포지션.
- closed_trades_today, recent_decisions: 오늘의 거래 결과와 직전 판단들(거부 사유 포함).

매매 방식:
- 한 번에 한 종목만 보유합니다. 오를 것 같으면 {bull}, 내릴 것 같으면 {bear}를 삽니다. 공매도는 없습니다.
- 단타입니다. 주변 종목과 {bull}의 추세가 같은 방향으로 붙을 때 그 방향에 올라타고, 모멘텀이 \
꺾이거나 주변 종목이 먼저 돌아서면 익절/손절 가격에 닿기 전이라도 SELL로 빠져나오세요. \
방향이 반대로 뚜렷해지면 반대 종목으로 갈아탈 수 있습니다.
- 일일 목표 수익(운용자금의 약 10%)과 일일 손실 한도가 있습니다. 목표는 '달성하면 그날 매매를 \
끝내는 지점'이지 반드시 채워야 하는 할당량이 아닙니다. 목표를 채우려고 근거가 약한 거래를 하면 \
기대값이 나빠지므로, 뚜렷한 우위가 없으면 HOLD가 가장 좋은 답입니다. 하루 종일 HOLD여도 괜찮습니다.
- 왕복 수수료(account.round_trip_fee_pct)가 수익에서 빠집니다. 예상 움직임이 수수료와 \
슬리피지를 충분히 넘지 못하면 진입할 이유가 없습니다.
- 손절·익절·일일 한도·거래 횟수·장 마감 전 청산은 코드가 따로 강제합니다. 당신이 제안한 \
손절폭/비중이 한도를 넘으면 코드가 잘라냅니다.
- 방금 손절한 방향으로 곧바로 재진입하는 복수 매매는 피하세요.

출력 규칙:
- action=BUY: symbol에 {bull} 또는 {bear}. 이미 포지션이 있으면 BUY 대신 HOLD나 SELL을 쓰세요 \
(반대 종목 BUY는 기존 포지션 청산 후 진입으로 처리됩니다).
- action=SELL: 현재 포지션 전량 청산. 포지션이 없으면 의미 없습니다.
- action=HOLD: 유지/관망.
- stop_loss_pct, take_profit_pct는 진입가 대비 %이며 최근 변동성(atr14_pct)에 맞춰 정하세요.
- reason은 한국어 한두 문장으로, 주변 종목 흐름을 포함한 핵심 근거만 적으세요."""


class ClaudeBrain:
    def __init__(self, cfg: Settings, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        # 판단이 늦게 도착하면 이미 낡은 정보이므로 타임아웃을 짧게, 재시도는 1회만.
        self.client = client or anthropic.Anthropic(timeout=90.0, max_retries=1)
        self.system = SYSTEM.format(bull=cfg.bull, bear=cfg.bear)

    def decide(self, snapshot: dict) -> Decision:
        """오류·거절 시에는 항상 HOLD를 돌려준다(보유 포지션은 코드 손절이 보호)."""
        req = dict(
            model=self.cfg.model,
            max_tokens=16000,
            system=self.system,
            output_config={"effort": self.cfg.effort},
            output_format=Decision,
            messages=[{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}],
        )
        try:
            if "haiku" in self.cfg.model:
                # Haiku 는 서버 측 대체 모델(fallbacks)을 지원하지 않는다. 거절되면 아래에서 HOLD 처리.
                resp = self.client.messages.parse(**req)
            else:
                # 안전 분류기가 요청을 거절하면 서버가 대체 모델로 같은 요청을 재실행한다.
                resp = self.client.beta.messages.parse(
                    **req, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.RateLimitError as e:
            log.warning("Claude 호출 한도 초과 → HOLD: %s", e)
            return HOLD.model_copy(update={"reason": "API 한도 초과"})
        except anthropic.APIStatusError as e:
            log.error("Claude API 오류 %s → HOLD: %s", e.status_code, e.message)
            return HOLD.model_copy(update={"reason": f"API 오류 {e.status_code}"})
        except anthropic.APIConnectionError as e:
            log.warning("Claude 연결 실패 → HOLD: %s", e)
            return HOLD.model_copy(update={"reason": "API 연결 실패"})
        except ValueError as e:      # 스키마에 맞지 않는 출력(pydantic ValidationError 포함)
            log.error("Claude 응답 해석 실패 → HOLD: %s", e)
            return HOLD.model_copy(update={"reason": "응답 해석 실패"})

        if resp.stop_reason != "end_turn" or resp.parsed_output is None:
            log.warning("Claude 응답 비정상(stop_reason=%s) → HOLD", resp.stop_reason)
            return HOLD.model_copy(update={"reason": f"stop_reason={resp.stop_reason}"})
        u = resp.usage
        log.debug("tokens in=%s out=%s", u.input_tokens, u.output_tokens)
        return resp.parsed_output


class RuleBrain:
    """EMA 정배열 + VWAP 위 + RSI 과열 아님 → 매수. 검증된 전략이 아니라 배선 점검용."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def decide(self, snapshot: dict) -> Decision:
        pos = snapshot["account"]["position"]
        for sym in self.cfg.symbols:
            m = snapshot["market"][sym]
            if None in (m["ema9"], m["ema20"], m["rsi14"], m["vwap"]):
                continue
            up = m["ema9"] > m["ema20"] and m["last"] > m["vwap"] and 50 < m["rsi14"] < 70
            if pos and pos["symbol"] == sym and m["ema9"] < m["ema20"]:
                return Decision(action="SELL", symbol="", confidence=0.7, size_pct=0,
                                stop_loss_pct=0, take_profit_pct=0, reason="EMA 역전")
            if not pos and up:
                atr = m["atr14_pct"] or 0.5
                return Decision(action="BUY", symbol=sym, confidence=0.7, size_pct=100,
                                stop_loss_pct=max(2 * atr, 0.8), take_profit_pct=max(4 * atr, 1.6),
                                reason="EMA9>EMA20, VWAP 위, RSI 50~70")
        return HOLD.model_copy(update={"reason": "조건 없음"})
