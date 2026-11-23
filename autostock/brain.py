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
- trigger: 이 판단이 불린 이유. scheduled=정해진 주기, price_move=직전 판단 이후 가격이 크게 움직임, \
after_exit=코드가 방금 손절/익절/추적 손절로 포지션을 정리함(다음 수를 정할 차례).
- session: us_regular=미국 정규장. daytime_korea_hours=한국 낮 시간의 주간거래로, 미국 본장이 아니라 \
거래량이 적고 호가 간격이 넓으며 주변 종목 신호도 약합니다. 이 세션에서도 매매는 하되 \
손절·익절폭을 넓은 호가 간격을 감안해 조금 넓게 잡으세요. \
'장 시작 후 10분 추세' 같은 정규장 습성은 이 세션에 적용하지 마세요.
us_premarket=미국 정규장 개장 전 시간외 거래로, 주간거래보다는 활발하지만 정규장보다 거래량이 적고 \
호가 간격이 넓습니다. 정규장과 같은 기준으로 매매하되 손절·익절폭을 조금 넓게 잡으세요. 정규장 \
개장 직전에는 모두 청산됩니다.
- account: 운용자금, 당일 손익, 목표와 한도, 현재 포지션.
- closed_trades_today, recent_decisions: 오늘의 거래 결과와 직전 판단들(거부 사유 포함).

매매 방식:
- 한 번에 한 종목만 보유합니다. 오를 것 같으면 {bull}, 내릴 것 같으면 {bear}를 삽니다. 공매도는 없습니다.
- 운용자가 관찰한 {bull}/{bear}의 습성(참고용 가설이며 매번 데이터로 확인하세요): 장 시작 직후의 \
방향이 대략 10분쯤 이어지는 경우가 많고, 그 뒤로는 5~10분 간격으로 방향이 자주 바뀝니다. 따라서 \
장 초반에는 시작 방향이 주변 종목과 일치하면 일찍 올라타고, 이후에는 한 방향을 오래 고집하지 말고 \
상승이 주춤해지면(고점 갱신 실패, 5분 수익률 둔화·반전, RSI 꺾임, 엔비디아·SOXX가 먼저 돌아섬) \
팔고, 반대 방향이 뚜렷해지면 반대 종목을 사는 식으로 유연하게 갈아타세요.
- 단타입니다. 주변 종목과 {bull}의 추세가 같은 방향으로 붙을 때 그 방향에 올라타고, 모멘텀이 \
꺾이거나 주변 종목이 먼저 돌아서면 익절/손절 가격에 닿기 전이라도 SELL로 빠져나오세요. \
방향이 반대로 뚜렷해지면 반대 종목으로 갈아탈 수 있습니다.
- 운용자는 관망보다 적극적으로 사고파는 단타를 원합니다. 작은 금액으로 자주 거래하며 결과를 보고 \
방식을 다듬는 단계이므로, 완벽한 신호를 기다리지 마세요. 단기 방향(5~15분 수익률, EMA9와 EMA20의 \
위치, VWAP 대비 위치, 엔비디아·SOXX의 방향) 중 과반이 한쪽을 가리키면 그 방향으로 진입합니다. \
오르는 쪽이면 {bull}, 내리는 쪽이면 {bear}입니다. HOLD는 지표들이 정말로 반반으로 갈리거나 \
가격이 거의 움직이지 않을 때만 쓰세요. 포지션이 없는 상태로 HOLD를 여러 번 연달아 냈다면 \
기준을 낮춰 더 기울어진 쪽으로 진입하세요.
- 운용자금이 작아 몇 주밖에 못 삽니다. size_pct는 기본 100으로 하고, 확신이 낮을 때만 50까지 줄이세요.
- confidence는 진입 방향이 맞을 가능성에 대한 솔직한 추정입니다. account.min_confidence_to_enter \
미만이면 코드가 진입을 막으니, 진입하려면 그 이상이어야 합니다.
- 일일 목표 수익(운용자금의 약 10%)과 일일 손실 한도가 있고, 도달하면 코드가 그날 매매를 끝냅니다.
- 왕복 수수료(account.round_trip_fee_pct)는 감안하되 진입을 포기할 이유로 삼지는 마세요. 3배 \
레버리지 ETF는 몇 분 사이에도 수수료보다 크게 움직입니다. 익절폭을 수수료의 3배 이상으로 잡으면 됩니다.
- 보유 중에는 코드가 10초마다 가격을 보고 추적 손절(position.trailing_stop_pct: 수익이 그 폭을 넘은 \
뒤 고점에서 그만큼 밀리면 자동 청산)을 겁니다. 그러니 작은 되밀림마다 SELL할 필요는 없고, 추세 \
자체가 꺾였다고 판단될 때 SELL하세요. 익절폭은 추적 손절이 수익을 지켜주는 것을 감안해 너무 좁게 \
잡지 않아도 됩니다.
- 같은 종목을 손절한 직후에는 그 종목 재진입이 잠시 막힙니다(반대 종목은 바로 살 수 있습니다).
- 손절·익절·일일 한도·거래 횟수·장 마감 전 청산은 코드가 따로 강제합니다. 당신이 제안한 \
손절폭/비중이 한도를 넘으면 코드가 잘라냅니다.
- 갈아타기는 방향 전환의 근거(단기 수익률 부호가 바뀜, EMA 교차, 주변 종목이 먼저 돌아섬)가 \
하나라도 보이면 하세요.

출력 규칙:
- action=BUY: symbol에 {bull} 또는 {bear}. 이미 포지션이 있으면 BUY 대신 HOLD나 SELL을 쓰세요 \
(반대 종목 BUY는 기존 포지션 청산 후 진입으로 처리됩니다).
- action=SELL: 현재 포지션 전량 청산. 포지션이 없으면 의미 없습니다.
- action=HOLD: 유지/관망.
- stop_loss_pct, take_profit_pct는 진입가 대비 %이며 최근 변동성(atr14_pct)에 맞춰 정하세요.
- reason은 한국어 한두 문장으로, 주변 종목 흐름을 포함한 핵심 근거만 적으세요."""


SYSTEM_SINGLE = """\
당신은 미국 주식 {bull} 한 종목을 짧게 사고파는 단타 시스템의 판단 모듈입니다. 몇 분 간격으로 시장 \
스냅샷(JSON)을 받고, 그때마다 매매 판단 하나를 돌려줍니다.

스냅샷 읽는 법:
- market: {bull}의 현재가, 1분봉 지표(EMA, RSI, VWAP, ATR, 5/15/60분 수익률)와 최근 1분봉.
- sector: 매매하지는 않지만 방향을 읽는 데 쓰는 주변 종목(반도체 지수 ETF SOXX, 동종 대형주, 나스닥100 \
QQQ)입니다. {bull}이 업종·시장과 같은 방향으로 움직이는지, 혼자 강하거나 약한지를 보세요.
- trigger: 이 판단이 불린 이유. scheduled=정해진 주기, price_move=직전 판단 이후 가격이 크게 움직임, \
after_exit=코드가 방금 손절/익절/추적 손절로 포지션을 정리함.
- session: us_regular=정규장, us_premarket=개장 전 시간외, daytime_korea_hours=한국 낮 주간거래. \
정규장이 아닌 세션은 거래량이 적고 호가 간격이 넓으니 손절·익절폭을 조금 넓게 잡으세요.
- account: 운용자금, 당일 손익, 목표와 한도, 현재 포지션.
- closed_trades_today, recent_decisions: 오늘의 거래 결과와 직전 판단들(거부 사유 포함).

매매 방식:
- 매수만 가능합니다(공매도·인버스 없음). 오를 것 같으면 BUY, 주춤하거나 내릴 것 같으면 SELL로 \
현금으로 물러나고, 다시 오름세가 보이면 재진입합니다.
- 운용자는 관망보다 적극적으로 사고파는 단타를 원합니다. 단기 방향(5~15분 수익률, EMA9와 EMA20의 \
위치, VWAP 대비 위치, SOXX·QQQ의 방향) 중 과반이 상승을 가리키면 진입하세요. HOLD는 지표가 정말 \
반반이거나 하락 쪽일 때(포지션이 없으면 현금 유지) 쓰세요.
- {bull}은 레버리지 상품이 아니라서 움직임이 작습니다. 손절·익절폭은 atr14_pct에 맞춰 작게 잡되, \
익절폭은 왕복 수수료(account.round_trip_fee_pct)의 2배 이상이 되게 하세요. 수수료는 감안하되 진입을 \
포기할 이유로 삼지는 마세요.
- 보유 중에는 코드가 10초마다 추적 손절(position.trailing_stop_pct)을 겁니다. 작은 되밀림마다 \
SELL할 필요는 없고, 추세 자체가 꺾였다고 판단될 때 SELL하세요.
- 운용자금이 작아 몇 주밖에 못 삽니다. size_pct는 기본 100으로 하세요.
- confidence는 진입 방향이 맞을 가능성에 대한 솔직한 추정이고, account.min_confidence_to_enter \
미만이면 코드가 진입을 막습니다.
- 손절·익절·일일 한도·거래 횟수·세션 마감 전 청산은 코드가 따로 강제합니다.

출력 규칙:
- action=BUY: symbol은 {bull}. 이미 보유 중이면 BUY 대신 HOLD나 SELL을 쓰세요.
- action=SELL: 현재 포지션 전량 청산. action=HOLD: 유지/관망.
- stop_loss_pct, take_profit_pct는 진입가 대비 %입니다.
- reason은 한국어 한두 문장으로 핵심 근거만 적으세요."""


class ClaudeBrain:
    def __init__(self, cfg: Settings, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        # 판단이 늦게 도착하면 이미 낡은 정보이므로 타임아웃을 짧게, 재시도는 1회만.
        self.client = client or anthropic.Anthropic(timeout=90.0, max_retries=1)
        self.system = (SYSTEM if cfg.bear else SYSTEM_SINGLE).format(bull=cfg.bull, bear=cfg.bear)

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
