"""Seed demo data: `python -m app.seed` (idempotent; run `alembic upgrade head` first).

!! The vehicle numbers below are ARBITRARY EXAMPLE VALUES for the demo, NOT manufacturer
!! specifications or measured charging curves. They must be calibrated before any real use.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Charger, ChargeSession, KpiDaily, SessionEvent, Station, VehicleSpec

STATION_NAME = "목포급속 1호점"

# (rated_kw, connector_type)
CHARGERS: list[tuple[int, str]] = [(50, "DC_COMBO"), (100, "DC_COMBO"), (350, "DC_COMBO")]

# Demo example values only. taper_start_soc=80 and efficiency=0.92 follow PRD 3.1 defaults.
# (model_name, battery_kwh, max_dc_kw, max_ac_kw, taper_min_ratio)
VEHICLES: list[tuple[str, float, float, float, float]] = [
    ("아이오닉 5 (예시)", 77.4, 220.0, 11.0, 0.20),  # PRD 3.3 verification case
    ("EV6 (예시)", 77.4, 233.0, 11.0, 0.20),
    ("테슬라 모델 3 (예시)", 60.0, 170.0, 11.0, 0.25),
    ("코나 일렉트릭 (예시)", 64.8, 100.0, 11.0, 0.20),
    ("레이 EV (예시)", 35.2, 70.0, 7.0, 0.30),
]

# (charger_idx, vehicle_idx, anon, soc_start, soc_target, status, queue_pos, start_ago_min)
SESSIONS: list[tuple[int, int, str, float, float, str, int | None, int | None]] = [
    (1, 0, "seed-anon-1", 20, 90, "charging", None, 10),
    (2, 1, "seed-anon-2", 10, 80, "charging", None, 5),
    (1, 3, "seed-anon-3", 30, 100, "waiting", 1, None),
    (1, 4, "seed-anon-4", 15, 80, "waiting", 2, None),
]


# Previous 7 days for the ops KPI cards (oldest first). ARBITRARY EXAMPLE VALUES, not measurements:
# (sessions, avg_wait_min, load_factor = mean / peak load, peak_reduction_kw)
KPI_HISTORY: list[tuple[int, float, float, float]] = [
    (38, 11.8, 0.52, 22.0),
    (41, 12.5, 0.55, 30.0),
    (36, 13.1, 0.50, 18.0),
    (44, 10.9, 0.57, 35.0),
    (40, 12.0, 0.54, 28.0),
    (39, 12.8, 0.53, 25.0),
    (42, 11.5, 0.56, 31.0),
]


def seed_kpi_history(db: Session, station_id: int) -> bool:
    """Insert the example KPI history once; returns whether anything was added."""
    if db.scalar(select(KpiDaily.station_id).where(KpiDaily.station_id == station_id)) is not None:
        return False
    today = datetime.now(UTC).date()
    for i, (sessions, wait, factor, reduction) in enumerate(reversed(KPI_HISTORY), start=1):
        db.add(
            KpiDaily(
                station_id=station_id,
                date=today - timedelta(days=i),
                sessions=sessions,
                avg_wait_min=wait,
                load_factor=factor,
                peak_reduction_kw=reduction,
            )
        )
    return True


def seed(db: Session) -> None:
    existing = db.scalar(select(Station.station_id).where(Station.name == STATION_NAME))
    if existing is not None:
        if seed_kpi_history(db, existing):
            db.commit()
            print("seeded: KPI history only (stations already existed)")
        else:
            print("already seeded; skipping")
        return

    station = Station(name=STATION_NAME, lat=34.8118, lng=126.3922, contract_kw=400, limit_ratio=0.9)
    chargers = [Charger(rated_kw=kw, connector_type=ct, status="idle") for kw, ct in CHARGERS]
    station.chargers.extend(chargers)
    vehicles = [
        VehicleSpec(
            model_name=name,
            battery_kwh=kwh,
            max_dc_kw=dc,
            max_ac_kw=ac,
            taper_start_soc=80,
            taper_min_ratio=ratio,
            efficiency=0.92,
        )
        for name, kwh, dc, ac, ratio in VEHICLES
    ]
    db.add_all([station, *vehicles])
    db.flush()

    now = datetime.now(UTC)
    for c_idx, v_idx, anon, s0, s1, status, pos, ago in SESSIONS:
        started = now - timedelta(minutes=ago) if ago is not None else None
        session = ChargeSession(
            charger_id=chargers[c_idx].charger_id,
            vehicle_id=vehicles[v_idx].vehicle_id,
            anon_user_id=anon,
            soc_start=s0,
            soc_target=s1,
            soc_current=s0,
            status=status,
            queue_pos=pos,
            registered_at=started or now,
            actual_start=started,
        )
        db.add(session)
        db.flush()
        db.add(SessionEvent(session_id=session.session_id, type="seeded", payload={"status": status}))
        if status == "charging":
            chargers[c_idx].status = "charging"
    seed_kpi_history(db, station.station_id)
    db.commit()
    print(f"seeded: 1 station, {len(chargers)} chargers, {len(vehicles)} vehicles, "
          f"{len(SESSIONS)} sessions")


if __name__ == "__main__":
    with SessionLocal() as session_:
        seed(session_)
