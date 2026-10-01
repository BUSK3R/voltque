# VoltQueue

입력값(차종·SoC·충전기 출력)으로 잔여 충전 시간을 공식으로 계산하고, 대기열과 충전소 부하를 함께 관제하는 EV 충전 회전율·부하 분산 프로토타입입니다. 요구사항의 기준은 [PRD.md](PRD.md)입니다.

> 현재 단계: **1단계(프로젝트 골격 · 데이터 모델 · 시드)**. 계산 엔진, 스케줄러, 화면은 이후 단계에서 구현합니다.

## 빠른 시작

필요한 것: Python 3.11+, Node.js 20+, GNU make (Docker는 선택).

```bash
make install   # backend venv + frontend 의존성
make seed      # 마이그레이션 + 시드 (충전기 3대, 차종 5종, 세션 4건)
make dev       # http://localhost:8000/health , http://localhost:5173/m , /ops
make test
```

Docker: `make docker-up` (PostgreSQL까지 쓰려면 `docker compose --profile postgres up` 하고
`DATABASE_URL=postgresql+psycopg://voltqueue:voltqueue@postgres:5432/voltqueue`).

Windows에서 make가 없으면 `winget install ezwinports.make` 후 새 터미널을 여세요.

## 구조

- `backend/` FastAPI, SQLAlchemy 2, Alembic, pytest
- `frontend/` React + TypeScript + Vite + Tailwind. `/m/*` 운전자 모바일, `/ops/*` 관제 PC
- DB는 기본 SQLite. `DATABASE_URL`만 바꾸면 PostgreSQL로 전환됩니다 (`backend/.env.example` 참고).

데이터 모델은 PRD 6장 그대로입니다 (station, charger, vehicle_spec, charge_session, session_event, load_log, kpi_daily). `charge_session`에는 `soc_start < soc_target`, SoC 0~100 CHECK 제약과 `(charger_id, status, queue_pos)` 인덱스가 있습니다.

## 시연용 가정값 (중요)

`backend/app/seed.py`의 차종 5종(배터리 용량, 최대 수용 출력, 테이퍼링 비율)은 **임의로 정한 예시값**이며, 제조사 공개 사양이나 실측 충전 곡선이 아닙니다. 차종명에 "(예시)"를 붙인 이유입니다. 충전 효율 0.92, 테이퍼링 시작 80%도 PRD 3장의 시연용 가정이며, 실사용 전에 캘리브레이션이 필요합니다. 충전소(목포급속 1호점, 계약전력 400kW)와 충전기 3대(50/100/350kW)도 모의 데이터입니다.
