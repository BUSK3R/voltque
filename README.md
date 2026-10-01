# VoltQueue

입력값(차종·SoC·충전기 출력)으로 잔여 충전 시간을 공식으로 계산하고, 대기열과 충전소 부하를 함께 관제하는 EV 충전 회전율·부하 분산 프로토타입입니다. 실제 충전기 없이 **시뮬레이터로 전체 흐름을 재현**합니다. 요구사항의 기준은 [PRD.md](PRD.md)입니다.

| 화면 | 주소 | 대상 |
| --- | --- | --- |
| 운전자 모바일 | `/m` (360px) | 차종·SoC 입력 → 예상 시간 → 대기 타임라인 → 충전 타이머 → 완료 |
| 관제 대시보드 | `/ops` (1440×900, 1920×1080) | 간트차트 · 부하 게이지 · 부하 추이 · KPI 4종 · 이벤트 로그 |

두 화면은 같은 WebSocket 스냅샷을 구독하므로 모바일에서 등록한 세션이 관제 간트차트에 바로 나타납니다.

시연 순서는 [docs/DEMO.md](docs/DEMO.md), 발표 질의응답은 [docs/QA.md](docs/QA.md)를 보세요.

## 빠른 시작

필요한 것: Python 3.11+, Node.js 20+, GNU make (Docker는 선택).

```bash
make install   # backend venv + frontend 의존성
make seed      # 마이그레이션 + 시드 (충전기 3대, 차종 5종, 세션 4건, 전일 KPI 7일치)
make dev       # http://localhost:8000/health , http://localhost:5173/m , /ops
make test      # backend pytest + frontend tsc 타입체크
make e2e       # Playwright로 7.3 시연 재현 (별도 DB·포트, 시스템 Chrome 필요)
```

Docker: `make docker-up` (PostgreSQL까지 쓰려면 `docker compose --profile postgres up` 하고
`DATABASE_URL=postgresql+psycopg://voltqueue:voltqueue@postgres:5432/voltqueue`).

Windows에서 make가 없으면 `winget install ezwinports.make` 후 새 터미널을 여세요.

> `make dev`를 끌 때는 터미널에서 Ctrl+C로 종료하세요. 창만 닫으면 `--reload` 워커가 남아 8000 포트를 계속 잡고 옛 코드로 응답할 수 있습니다.

## 아키텍처

```text
 ┌──────────────── 브라우저 ────────────────┐
 │  /m  운전자 모바일 (360px)               │   /ops  관제 PC (1440~1920px)
 │  등록 · 대기 · 충전 타이머 · 알림 배너     │   간트 · 게이지 · 부하 추이 · KPI · 로그
 └───────┬──────────────────────────────────┴───────────┬──────────────┘
         │ REST  /api/sessions · /estimate               │ REST  /api/sim/* · /sessions/{id}/nudge
         │ WebSocket  /api/ws/stations/1  (스냅샷 푸시 ≈0.5초) ◄─────────┘  (두 화면이 같은 피드를 구독)
 ┌───────▼───────────────────────────────────────────────────────────────┐
 │ backend/app/api   얇은 API 계층: routes · runtime(DB 미러·푸시·티커) · schemas │
 └───────┬───────────────────────────────┬───────────────────────────────┘
         │ 호출                           │ 미러링
 ┌───────▼──────────────┐       ┌────────▼───────────────────────────────┐
 │ app/sim  시뮬레이터     │       │ SQLAlchemy 2 + Alembic                  │
 │  world  가상 시계 상태기계│       │ SQLite(기본) ↔ PostgreSQL (DATABASE_URL) │
 │  runner 시나리오 · 두 월드│       │ station · charger · vehicle_spec        │
 │  (controlled / baseline)│       │ charge_session · session_event          │
 └───────┬──────────────┘       │ load_log · kpi_daily                    │
         │ 순수 함수 호출         └────────────────────────────────────────┘
 ┌───────▼──────────────────────────────────────┐
 │ app/engine  계산 로직 (DB·FastAPI·시계 의존 없음)    │
 │  charge_time  충전 시간  ·  scheduler  대기열/타임블록 │
 │  load         부하 인지 시작 제어 (출력 제한/지연)      │
 └──────────────────────────────────────────────┘
```

- **계산 로직은 순수 함수**입니다. 시간(now)은 인자로 받고, 난수·현재 시각을 읽지 않아 같은 입력이면 항상 같은 결과가 나옵니다.
- **시뮬레이터는 두 월드를 같은 도착 순서로 나란히 돌립니다.** `controlled`는 VoltQueue(부하 제어 적용), `baseline`은 제어 없이 모든 차량이 즉시 최대 출력으로 시작합니다. 부하 추이 그래프의 점선/실선과 "피크 경감량" KPI가 이 두 월드의 차이입니다.
- DB는 시뮬레이션 상태의 **미러**입니다. 서버를 재시작하면 시뮬레이션 행은 지워집니다.
- DB는 `DATABASE_URL`만 바꾸면 PostgreSQL로 전환됩니다 (`backend/.env.example` 참고).

## 공식 근거

모든 예상 시간 옆의 "계산 근거 보기"에 입력·공식·구간별 시간이 그대로 나옵니다 (PRD 3장).

```text
P_eff = min(Pc, Pv) × η                         유효 출력 (충전기·차량 중 낮은 쪽 × 충전 효율)
k(s)  = 1                       (s ≤ sT)        테이퍼링 계수 (sT 이후 선형 감소, α = 1 − kmin)
        1 − α·(s − sT)/(100 − sT)  (s > sT)
T1    = C·(min(s1, sT) − s0)⁺ / (100·P_eff)     일정 출력 구간 (h)
T2    = C·(100 − sT) / (100·α·P_eff) · ln(k(a)/k(s1)),  a = max(s0, sT)   테이퍼링 구간 (s1 > sT일 때만)
T     = γ·(T1 + T2)·60 [분],   오차 범위 [0.92·T, 1.10·T]
```

- 검증 예시: C=77.4kWh, 20→90%, Pc=100kW, Pv=220kW, η=0.92, sT=80, kmin=0.2 → **36.7분** (`backend/tests/test_charge_time.py`가 이 값을 고정합니다).
- 대기열: `S_q1 = max(now, E_cur) + τ`, `E = S + T`, `S_next = E + τ`. 우선순위는 선착순 + 노쇼 강등 + 짧은 충전 가산(`score = wait + β·max(0, 30 − T)`, 대기 30분 초과자는 에이징 보호).
- 부하 제어: `P_site ≤ λ·P_contract` (λ=0.9). 여유 출력 R이 `P_eff`의 50% 이상이면 **출력 제한 시작**, 미만이면 **시작 지연**하고 사유와 시각을 안내합니다.

## 관제 KPI 정의 (PRD 5.3)

| KPI | 정의 |
| --- | --- |
| 일일 회전수 | 완료된 충전 세션 수 (충전기당 평균 병기) |
| 평균 대기시간 | 대기 등록부터 충전 시작까지의 평균 (분) |
| 전력 사용 효율 | 부하율 = 평균 부하 ÷ 최대 부하 |
| 피크 경감량 | 제어 없음의 최대 kW − 적용 시 최대 kW |

"전일 대비"는 시드의 7일치 예시값과 비교합니다. 오늘 값은 시뮬레이션 시작 이후의 누적이라 시연 초반에는 "집계 중"으로 표시합니다.

## 시연용 가정값 (중요)

아래 수치는 모두 **시연용으로 임의로 정한 값**이며 제조사 공개 사양, 실측 충전 곡선, 실제 운영 데이터가 아닙니다. 실사용 전에 캘리브레이션이 필요합니다.

| 구분 | 값 | 위치 |
| --- | --- | --- |
| 차종 5종 (이름에 "(예시)") | 배터리 용량 35.2~77.4kWh, 최대 수용 출력 70~233kW, 테이퍼링 최저 비율 0.20~0.30 | `backend/app/seed.py` |
| 충전 효율 η · 테이퍼 시작 sT · 보정 계수 γ | 0.92 · 80% · 1.0 (세션별 재추정은 미구현) | seed · `engine/charge_time.py` |
| 오차 범위 | 0.92T ~ 1.10T | `engine/charge_time.py` |
| 충전소 | 목포급속 1호점, 계약전력 400kW (모의) | `seed.py` |
| 충전기 | 3대: 50 / 100 / 350kW | `seed.py` |
| 시연 시나리오 | 계약전력 300kW로 덮어씀, 도착 10건 (차종·SoC·시각 임의) | `backend/scenarios/demo.json` |
| 차량 교체 여유 τ · 노쇼 유예 · 에이징 · β | 3분 · 5분 · 30분 · 0.5 | `engine/scheduler.py` |
| 부하 한도 λ · 출력 제한 시작 최소 비율 | 0.9 · P_eff의 50% | `engine/load.py` |
| 방치 판정 · 알림 후 이동 | 완료 후 5분 · 알림 2분 뒤 가상 운전자가 이동 | `sim/world.py` |
| 가상 운전자 | 호출 후 진입 3분(옵션 6분=노쇼), 완료 후 이동 즉시(옵션 12분=방치) | 모바일 "시연 옵션" |
| 전일 KPI | 7일치 예시값 | `seed.py` |

방치 차량은 실제로 충전기를 점유합니다(그동안 다음 대기자는 호출되지 않음). PRD 6장의 `charger.status`는 `idle/charging/fault`만 허용하므로, DB 미러에서는 점유 중인 충전기를 `charging`으로 기록하고 API에서만 `occupied`로 구분합니다.

## 구조

- `backend/` FastAPI, SQLAlchemy 2, Alembic, pytest
- `frontend/` React + TypeScript + Vite + Tailwind, Recharts. `src/mobile/` `/m/*`, `src/ops/` `/ops/*`, `src/feed.tsx` 공용 WebSocket 피드, `e2e/` Playwright
- `docs/` 시연 스크립트(DEMO.md), 예상 질문(QA.md), `screenshots/` E2E가 만든 화면

데이터 모델은 PRD 6장 그대로입니다 (station, charger, vehicle_spec, charge_session, session_event, load_log, kpi_daily). `charge_session`에는 `soc_start < soc_target`, SoC 0~100 CHECK 제약과 `(charger_id, status, queue_pos)` 인덱스가 있습니다.
