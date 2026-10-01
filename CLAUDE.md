# CLAUDE.md — VoltQueue

**PRD.md가 요구사항의 기준이다.** 구현이 PRD와 어긋나면 코드가 아니라 PRD를 먼저 확인하고, PRD를 바꿔야 한다면 사용자에게 물어본다. 공식은 PRD 3장, 데이터 모델은 6장, 스택은 7장을 따른다.

## 실행 / 테스트 명령 (루트에서)

| 명령 | 동작 |
|---|---|
| `make install` | backend venv 생성 + 의존성, frontend `npm install` |
| `make dev` | 백엔드(:8000, `/health`) + 프론트(:5173, `/m`, `/ops`) 동시 실행 |
| `make seed` | Alembic 마이그레이션 적용 후 시드 입력 (멱등) |
| `make migrate` | `alembic upgrade head` |
| `make test` | backend `pytest` + frontend `tsc` 타입체크 |
| `make docker-up` | 같은 스택을 Docker Compose로 실행 (`--profile postgres`로 PostgreSQL) |

새 마이그레이션: `cd backend && .venv/Scripts/alembic revision --autogenerate -m "msg"` (macOS/Linux는 `.venv/bin/alembic`).

## 폴더 구조

```
backend/   FastAPI + SQLAlchemy 2 + Alembic (Python >=3.11)
  app/main.py        FastAPI 앱 (/health)
  app/config.py      DATABASE_URL 등 설정 (DB 교체는 여기 한 곳)
  app/db.py          engine / session
  app/models/        PRD 6장 테이블 7개
  app/engine/        계산 로직: 순수 함수만 (DB·FastAPI import 금지)
                     charge_time(충전 시간) · scheduler(대기열·타임블록) · load(부하 제어)
  app/sim/           결정론적 시뮬레이터 (world: 가상 시계 상태기계, runner: 시나리오·baseline/controlled).
                     DB·FastAPI import 금지, 시간은 step()/advance()로만 진행
  app/api/           얇은 API 계층: routes(REST+WebSocket), runtime(DB 미러·푸시·티커), schemas
  app/seed.py        데모 시드
  scenarios/         시뮬레이션 시나리오 JSON (demo.json — 수치는 임의 예시값)
  alembic/           마이그레이션
  tests/
frontend/  React + TS + Vite + Tailwind
  src/mobile/        /m/*  운전자 모바일 (360px)
  src/ops/           /ops/* 관제 PC (1440x900, 1920x1080)
scripts/dev.py       make dev 런처
```

## 코딩 규칙

- **타입 필수**: Python은 모든 함수에 타입 힌트(mypy strict 기준), TypeScript는 `strict`, `any` 금지.
- **계산 로직은 순수 함수**로 `backend/app/engine/`에 분리한다. DB 세션·시계·FastAPI에 의존하지 않고, 시간(now)은 인자로 받는다. API/DB 계층은 얇게 유지한다.
- 같은 입력이면 항상 같은 결과(결정론). 난수·현재 시각을 함수 내부에서 읽지 않는다.
- DB는 SQLAlchemy 범용 타입만 사용해 SQLite ↔ PostgreSQL 전환이 `DATABASE_URL` 변경만으로 되게 한다. 스키마 변경은 반드시 Alembic 마이그레이션으로.
- 차종·충전기 수치는 **시연용 임의 예시값**이다. 실제 제원처럼 서술하지 않는다.
- 개인정보 미수집: 차량번호 등 금지, 익명 세션 ID만 사용 (PRD 4.4).
- 프론트 API 호출은 `/api` 프록시 경유. 4단계부터 msw 등으로 백엔드를 목킹하지 않는다.
