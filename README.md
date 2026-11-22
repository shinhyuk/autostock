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
2. **연결 점검** — `.env`에 키를 넣은 뒤, 주문 없이 Claude/KIS 연결만 확인합니다.
   ```bash
   python -m autostock --check
   ```
3. **paper** — KIS 실시간 시세 + Claude 판단 + 가상 체결. 주문은 나가지 않습니다.
4. **kis-demo** — KIS 모의투자 계좌로 실제 주문 API 호출 (`KIS_DEMO_*` 키 필요).
5. **live** — 실계좌 (`KIS_REAL_*` 키와 `LIVE_TRADING_CONFIRM=I_UNDERSTAND` 필요).

모드는 `.env`의 `MODE`로 정하고 `python -m autostock`으로 실행합니다. 시세는 실전 키가 있으면
실전 서버에서 가져옵니다(시세 조회는 주문과 무관).

## 서버에서 운영 (`./bot`)

```bash
./bot setup      # 자동 실행 + 5분마다 GitHub 최신 코드 자동 반영 (처음 한 번)
./bot check      # 키/연결 점검
./bot status     # 실행 상태, 오늘 손익, 최근 로그
./bot logs       # 실시간 로그
./bot mode kis-demo   # 모드 변경 (paper | kis-demo | live) 후 재시작
./bot update     # 지금 바로 최신 코드 반영
./bot web        # 결과 웹페이지 켜기 → http://<서버IP>:8080/?k=<토큰> (보안 그룹에서 TCP 8080 허용 필요)
```

자동 업데이트와 모드 변경은 보유 포지션이 있으면 미뤄집니다.

여러 모드를 동시에 돌리려면 쉼표로 적습니다: `./bot mode kis-demo,live`. 실주문 모드(kis-demo, live)는
개장 후 1주 매수→매도 테스트를 자동으로 먼저 하고, 통과해야 매매를 시작합니다. live는 kis-demo 테스트가
먼저 통과할 때까지 기다리며, 테스트가 실패한 모드는 그날 매매하지 않고 다음 거래일에 다시 시도합니다.

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
| Secret | `KIS_REAL_APP_KEY`, `KIS_REAL_APP_SECRET`, `KIS_REAL_ACCOUNT_NO` | 실전 앱키/시크릿/계좌 앞 8자리 |
| Secret | `KIS_DEMO_APP_KEY`, `KIS_DEMO_APP_SECRET`, `KIS_DEMO_ACCOUNT_NO` | 모의투자 앱키/시크릿/계좌 앞 8자리 |
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
