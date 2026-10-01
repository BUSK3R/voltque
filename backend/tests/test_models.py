from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, ChargeSession, Charger, Station, VehicleSpec


@pytest.fixture()
def db() -> Iterator[Session]:
    engine: Engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        station = Station(name="s", lat=0, lng=0, contract_kw=400)
        station.chargers.append(Charger(rated_kw=100, connector_type="DC_COMBO"))
        session.add_all([station, VehicleSpec(model_name="v", battery_kwh=70, max_dc_kw=150, max_ac_kw=11)])
        session.commit()
        yield session


def _session(**kw: object) -> ChargeSession:
    base: dict[str, object] = dict(
        charger_id=1, vehicle_id=1, anon_user_id="a", soc_start=20, soc_target=80, status="waiting"
    )
    return ChargeSession(**{**base, **kw})


def test_valid_session_inserts(db: Session) -> None:
    db.add(_session())
    db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"soc_start": 80, "soc_target": 80},  # start == target
        {"soc_start": 90, "soc_target": 50},  # start > target
        {"soc_start": -1},
        {"soc_target": 101},
        {"status": "bogus"},
    ],
)
def test_check_constraints_reject(db: Session, overrides: dict[str, object]) -> None:
    db.add(_session(**overrides))
    with pytest.raises(IntegrityError):
        db.commit()


def test_queue_index_exists(db: Session) -> None:
    indexes = inspect(db.get_bind()).get_indexes("charge_session")
    assert ["charger_id", "status", "queue_pos"] in [i["column_names"] for i in indexes]
