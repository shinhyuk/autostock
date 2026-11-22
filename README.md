# autostock — SOXL/SOXS AI 단타 자동매매

미국 정규장 동안 Claude가 몇 분마다 시세를 보고 SOXL(반도체 3배 상승) / SOXS(3배 하락) 중
하나를 사거나, 팔거나, 관망합니다. 주문은 한국투자증권(KIS) Open API로 나갑니다.

- **AI가 하는 일**: 진입 방향·비중·손절/익절폭 제안, 재량 청산
- **코드가 강제하는 일** (AI가 넘을 수 없음): 손절·익절 감시(10초 주기), 일일 목표/손실 한도,
  거래 횟수, 연속 손실 중단, 손절 후 쿨다운, 장 마감 전 강제 청산(오버나이트 없음)

## 시작하기

```bash
pip install -r requirements.txt
cp .env.example .env        # 키와 한도 입력
```

1. **배선 점검** — 키 없이, 가짜 시세 + 단순 규칙으로 하루(390분)를 돌려봅니다.
   ```bash
   python -m autostock --simulate 390 --brain rule
   ```
2. **paper** — KIS 실시간 시세 + Claude 판단 + 가상 체결. 주문은 나가지 않습니다.
   `.env`에 `ANTHROPIC_API_KEY`, `KIS_APP_KEY`, `KIS_APP_SECRET` 필요.
   ```bash
   python -m autostock
   ```
3. **kis-demo** — KIS 모의투자 계좌로 실제 주문 API 호출 (`KIS_ENV=demo`, 계좌번호 입력).
   ```bash
   python -m autostock --mode kis-demo
   ```
4. **live** — 실계좌. `.env`에 `KIS_ENV=real`, `LIVE_TRADING_CONFIRM=I_UNDERSTAND` 둘 다 있어야 실행됩니다.
   ```bash
   python -m autostock --mode live
   ```

정규장은 09:30~16:00 ET (한국시간 23:30~06:00, 서머타임 중 22:30~05:00)이며 그 외 시간에는 대기합니다.
매매 기록은 `data/journal_<mode>.jsonl`, 당일 상태는 `data/state_<mode>.json`에 남고,
재시작해도 당일 손익과 한도가 이어집니다.

## GitHub Actions로 자동 실행

`.github/workflows/trade.yml`이 평일 13:05 UTC(개장 전)에 봇을 띄웁니다. 러너는 작업당 6시간 제한이
있어 320분 뒤 스스로 끝나고 다음 실행이 이어받으며, 당일 상태는 `bot-state` 브랜치에 저장됩니다.

저장소 **Settings → Secrets and variables → Actions**에서 설정합니다.

| 종류 | 이름 | 값 |
|---|---|---|
| Secret | `ANTHROPIC_API_KEY` | Claude API 키 |
| Secret | `KIS_APP_KEY`, `KIS_APP_SECRET` | KIS 앱키/시크릿 |
| Secret | `KIS_ACCOUNT_NO` | 계좌번호 앞 8자리 |
| Variable | `KIS_ENV` | `demo` 또는 `real` (위 키의 종류) |
| Variable | `MODE` | `paper` → `kis-demo` → `live` |
| Variable | `USDKRW`, `FEE_PCT` 등 | `.env.example`의 항목 (없으면 기본값) |
| Variable | `LIVE_TRADING_CONFIRM` | 실계좌일 때만 `I_UNDERSTAND` |
| Variable | `BOT_ENABLED` | `true`일 때만 실행됨 (끄려면 삭제) |

Actions 탭의 **trade → Run workflow**로 수동 실행도 됩니다. 워크플로는 기본 브랜치에 있어야 예약 실행됩니다.

## 기본 한도 (`.env`에서 변경)

| 항목 | 기본값 |
|---|---|
| 운용자금 | 100만원 |
| 일일 목표 (도달 시 청산 후 종료) | +10만원 |
| 일일 손실 한도 (도달 시 청산 후 종료) | -5만원 |
| 1회 최대 손절폭 | 2% |
| 일일 최대 거래 / 연속 손실 중단 | 8회 / 3연패 |
| 손절 후 쿨다운 | 10분 |
| 진입 금지 | 개장 후 5분, 마감 전 20분 |
| 강제 청산 | 마감 5분 전 |
| AI 판단 주기 | 3분 |

## 구조

```
autostock/
  engine.py        메인 루프 (포지션 보호 → AI 판단 → 주문)
  brain.py         Claude 판단(구조화 출력) / 점검용 RuleBrain
  risk.py          코드 레벨 한도
  brokers/kis.py   KIS 시세·주문 (지정가로 즉시 체결 시도, 미체결 시 취소)
  brokers/paper.py 가상 체결, 시뮬레이션용 가짜 시세
  state.py         당일 상태 저장
tests/             pytest
```

## 알아둘 점

- **하루 10%는 목표가 아니라 상한선입니다.** 100만원으로 매일 10만원은 3배 레버리지 ETF로도
  꾸준히 나올 수 없는 수익률이고, AI가 판단한다고 기대값이 양수가 되는 것도 아닙니다.
  손실 한도 안에서 잃는 날이 더 많을 수 있다는 전제로, paper → kis-demo에서 몇 주치 기록을
  확인한 뒤 실계좌를 결정하세요.
- **KIS 주문 코드는 실제 서버로 검증되지 않았습니다.** 공식 샘플의 엔드포인트/TR ID를 따랐고
  모의 서버 응답으로 테스트했지만, 이 저장소를 만들 때 KIS 키가 없어 실서버 호출은 못 해봤습니다.
  반드시 `kis-demo`로 매수→매도 한 사이클을 먼저 확인하세요.
- **수수료**: 기본 편도 0.25%로 계산합니다. 왕복 0.5%는 단타에 큰 비용이니 본인 계좌 수수료율로 `FEE_PCT`를 맞추세요.
- **환율**: 손익/한도 환산은 `.env`의 `USDKRW` 고정값을 씁니다. 계좌에는 달러(또는 통합증거금)가 있어야 합니다.
- **API 비용**: 3분 주기면 하루 약 130회 호출입니다. 기본 모델(claude-opus-5-5) 기준 대략 하루 몇 달러 수준으로
  예상되며, `DECISION_INTERVAL_SEC`, `CLAUDE_MODEL`, `CLAUDE_EFFORT`로 조절합니다.
- **휴장일/조기폐장**은 달력으로 알지 못합니다. 대신 1분봉이 3분 넘게 갱신되지 않으면 신규 진입을 막습니다.
- 프로그램이 죽거나 네트워크가 끊기면 손절 감시도 멈춥니다. 실계좌라면 항상 켜진 서버에서 돌리고 계좌를 따로 확인하세요.
