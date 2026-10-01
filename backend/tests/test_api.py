import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.models import Base, ChargeSession, LoadLog, SessionEvent
from app.seed import seed

IONIQ = 1  # seeded first vehicle (77.4 kWh, 220 kW)


def _engine() -> Any:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def factory() -> sessionmaker[Session]:
    maker = sessionmaker(bind=_engine(), expire_on_commit=False)
    with maker() as db:
        seed(db)
    return maker


@pytest.fixture()
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory)) as c:
        yield c


def register(client: TestClient, s0: float = 20, s1: float = 90) -> dict[str, Any]:
    res = client.post("/sessions", json={"vehicle_id": IONIQ, "soc_start": s0, "soc_target": s1})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def test_vehicles_listing(client: TestClient) -> None:
    rows = client.get("/vehicles").json()
    assert len(rows) == 5
    assert rows[0]["battery_kwh"] == 77.4


def test_register_returns_time_and_calculation_basis(client: TestClient) -> None:
    body = register(client)
    calc = body["calc"]
    assert calc["charger_kw"] == 350  # empty station: a large charge goes to the 350 kW one
    assert calc["p_eff_kw"] == pytest.approx(220 * 0.92)  # vehicle-limited
    assert [s["name"] for s in calc["segments"]] == ["constant", "taper"]
    assert body["status"] == "waiting"
    assert body["planned_start"] and body["planned_end"]
    assert body["ahead"] == 0


def test_register_on_100kw_reproduces_prd_example(client: TestClient) -> None:
    # fill the 350 kW charger first so the next large charge lands on the 100 kW one
    register(client)
    body = register(client)
    assert body["calc"]["charger_kw"] == 100
    assert body["calc"]["total_min"] == pytest.approx(36.7, abs=0.1)


def test_register_rejects_invalid_input(client: TestClient) -> None:
    res = client.post("/sessions", json={"vehicle_id": IONIQ, "soc_start": 90, "soc_target": 50})
    assert res.status_code == 422
    assert "soc" in res.text.lower()
    res = client.post("/sessions", json={"vehicle_id": IONIQ, "soc_start": -5, "soc_target": 50})
    assert res.status_code == 422
    res = client.post("/sessions", json={"vehicle_id": 999, "soc_start": 10, "soc_target": 50})
    assert res.status_code == 404


def test_schedule_returns_current_plus_at_most_two_waiting_blocks(client: TestClient) -> None:
    client.post("/sim/start", json={"speed": 1})
    for _ in range(8):
        register(client)
    sched = client.get("/stations/1/schedule").json()
    assert [c["rated_kw"] for c in sched["chargers"]] == [50, 100, 350]
    for c in sched["chargers"]:
        waiting = [b for b in c["blocks"] if b["kind"] == "waiting"]
        assert len(waiting) <= 2
        assert c["queue_total"] >= len(waiting)
    assert sum(c["queue_total"] for c in sched["chargers"]) == 8


def test_unknown_station_is_404(client: TestClient) -> None:
    for tail in ("schedule", "load", "kpi"):
        assert client.get(f"/stations/9/{tail}").status_code == 404


def test_cancel_flow(client: TestClient) -> None:
    a = register(client)
    b = register(client)
    res = client.post(f"/sessions/{a['session_id']}/cancel")
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert client.post(f"/sessions/{a['session_id']}/cancel").status_code == 409
    assert client.post("/sessions/424242/cancel").status_code == 404
    assert client.get(f"/sessions/{b['session_id']}").json()["status"] == "waiting"


def test_sim_start_speed_reset(client: TestClient) -> None:
    state = client.post("/sim/start", json={"scenario": "demo", "speed": 60}).json()
    assert state["running"] is True and state["speed"] == 60 and state["scenario"] == "demo"
    assert client.post("/sim/speed", json={"speed": 10}).json()["speed"] == 10
    assert client.post("/sim/speed", json={"speed": 7}).status_code == 422
    assert client.post("/sim/start", json={"scenario": "../etc"}).status_code == 404
    assert client.post("/sim/start", json={"scenario": "missing"}).status_code == 404
    state = client.post("/sim/reset").json()
    assert state["running"] is False and state["scenario"] is None
    sched = client.get("/stations/1/schedule").json()
    assert all(c["blocks"] == [] for c in sched["chargers"])


def test_load_and_kpi_shapes(client: TestClient) -> None:
    load = client.get("/stations/1/load").json()
    assert load["contract_kw"] == 400 and load["limit_kw"] == pytest.approx(360)
    assert load["controlled"] and load["baseline"]
    kpi = client.get("/stations/1/kpi").json()
    assert set(kpi) >= {"sessions_done", "avg_wait_min", "load_factor", "peak_reduction_kw"}


def test_db_mirror_has_sessions_events_and_load_logs(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    body = register(client)
    client.post(f"/sessions/{body['session_id']}/cancel")
    with factory() as db:
        row = db.get(ChargeSession, body["session_id"])
        assert row is not None and row.status == "cancelled"
        assert row.calc_detail and "segments" in row.calc_detail
        types = set(
            db.scalars(select(SessionEvent.type).where(SessionEvent.session_id == row.session_id))
        )
        assert {"registered", "cancelled"} <= types
        assert (db.scalar(select(func.count()).select_from(LoadLog)) or 0) >= 2  # both modes
        assert db.get(ChargeSession, 1) is not None  # seeded demo sessions untouched
    client.post("/sim/reset")
    with factory() as db:
        assert db.get(ChargeSession, body["session_id"]) is None
        assert db.get(ChargeSession, 1) is not None


def test_websocket_pushes_snapshot_then_updates_on_events(client: TestClient) -> None:
    with client.websocket_connect("/ws/stations/1") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["reason"] == "connected"
        body = register(client)
        pushed = ws.receive_json()
        assert pushed["reason"] == "registered"
        blocks = [b for c in pushed["schedule"]["chargers"] for b in c["blocks"]]
        assert any(b["session_id"] == body["session_id"] for b in blocks)
        client.post(f"/sessions/{body['session_id']}/cancel")
        pushed = ws.receive_json()
        assert pushed["reason"] == "cancelled"
        blocks = [b for c in pushed["schedule"]["chargers"] for b in c["blocks"]]
        assert not any(b["session_id"] == body["session_id"] for b in blocks)


def test_websocket_rejects_unknown_station(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/stations/9") as ws:
        ws.receive_json()


def test_ticker_advances_clock_only_when_running(client: TestClient) -> None:
    t0 = client.get("/sim/state").json()["elapsed_min"]
    time.sleep(0.8)
    assert client.get("/sim/state").json()["elapsed_min"] == t0  # paused
    client.post("/sim/start", json={"speed": 60})
    time.sleep(1.3)
    assert client.get("/sim/state").json()["elapsed_min"] > t0


def test_not_seeded_database_answers_503() -> None:
    maker = sessionmaker(bind=_engine(), expire_on_commit=False)
    with TestClient(create_app(maker)) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/vehicles").status_code == 503


def test_demo_scenario_through_the_api_keeps_live_load_under_limit(client: TestClient) -> None:
    client.post("/sim/start", json={"scenario": "demo", "speed": 60})
    deadline = time.time() + 6
    worst = 0.0
    while time.time() < deadline:
        load = client.get("/stations/1/load").json()
        worst = max(worst, load["now_kw"])
        assert load["now_kw"] <= load["limit_kw"] + 1e-6
        time.sleep(0.2)
    assert client.get("/sim/state").json()["elapsed_min"] > 4  # 60x: ~1 sim minute per real second
    assert worst > 0


# --- step 4 additions ---------------------------------------------------------------


def test_estimate_does_not_register_and_matches_registration(client: TestClient) -> None:
    body = {"vehicle_id": IONIQ, "soc_start": 20, "soc_target": 90}
    est = client.post("/estimate", json=body).json()
    assert client.get("/stations/1/schedule").json()["chargers"][2]["blocks"] == []
    reg = client.post("/sessions", json=body).json()
    assert est["charger_id"] == reg["charger_id"]
    assert est["calc"]["total_min"] == pytest.approx(reg["calc"]["total_min"])
    assert est["expected_start"] == reg["planned_start"]
    assert est["expected_end"] == reg["planned_end"]


def test_estimate_on_100kw_charger_reproduces_prd_example(client: TestClient) -> None:
    est = client.post(
        "/estimate", json={"vehicle_id": IONIQ, "soc_start": 20, "soc_target": 90, "charger_id": 2}
    ).json()
    assert est["charger_id"] == 2
    assert est["calc"]["total_min"] == pytest.approx(36.7, abs=0.1)
    assert est["calc"]["low_min"] == pytest.approx(33.8, abs=0.1)
    assert est["calc"]["high_min"] == pytest.approx(40.4, abs=0.1)


def test_estimate_validation(client: TestClient) -> None:
    bad = client.post("/estimate", json={"vehicle_id": IONIQ, "soc_start": 80, "soc_target": 80})
    assert bad.status_code == 422
    unknown = {"vehicle_id": 999, "soc_start": 10, "soc_target": 50}
    assert client.post("/estimate", json=unknown).status_code == 404
    no_such = {"vehicle_id": IONIQ, "soc_start": 10, "soc_target": 50, "charger_id": 99}
    assert client.post("/estimate", json=no_such).status_code == 409


def test_register_on_chosen_charger(client: TestClient) -> None:
    body = {"vehicle_id": IONIQ, "soc_start": 20, "soc_target": 90, "charger_id": 1}
    assert client.post("/sessions", json=body).json()["charger_id"] == 1


def test_session_out_has_fields_the_mobile_screens_need(client: TestClient) -> None:
    client.post("/sim/start", json={"speed": 60})
    first = register(client)
    register(client)
    time.sleep(1.5)
    me = client.get(f"/sessions/{first['session_id']}").json()
    assert me["battery_kwh"] == 77.4
    assert me["lane"] and me["lane"][-1]["is_me"] is True
    sched = client.get("/stations/1/schedule").json()
    assert sched["station_name"]
    assert all(c["free_at"] for c in sched["chargers"])


def test_called_session_exposes_no_show_deadline(client: TestClient) -> None:
    client.post("/sim/start", json={"speed": 60})
    sid = client.post(
        "/sessions",
        json={"vehicle_id": IONIQ, "soc_start": 20, "soc_target": 90, "enter_delay_min": 6},
    ).json()["session_id"]
    deadline = time.time() + 5
    me: dict[str, Any] = {}
    while time.time() < deadline:
        me = client.get(f"/sessions/{sid}").json()
        if me["status"] == "called":
            break
        time.sleep(0.1)
    assert me["status"] == "called"
    assert me["called_at"] and me["no_show_at"]


def _park(client: TestClient, leave: float = 30) -> dict[str, Any]:
    """Register a short charge whose driver then stays plugged in; run it until done."""
    res = client.post(
        "/sessions",
        json={"vehicle_id": IONIQ, "soc_start": 70, "soc_target": 80, "leave_delay_min": leave},
    )
    assert res.status_code == 201, res.text
    sid = res.json()["session_id"]
    mgr = client.app.state.runtime.mgr  # type: ignore[attr-defined]
    for _ in range(600):
        mgr.advance(30)
        if mgr.primary.sessions[sid].parked:
            break
    body: dict[str, Any] = client.get(f"/sessions/{sid}").json()
    return body


def test_nudge_flow(client: TestClient) -> None:
    body = _park(client)
    assert body["status"] == "done" and body["parked"] is True and body["nudged_at"] is None
    res = client.post(f"/sessions/{body['session_id']}/nudge")
    assert res.status_code == 200 and res.json()["nudged_at"] is not None
    assert client.post("/sessions/424242/nudge").status_code == 404
    plain = register(client)
    assert client.post(f"/sessions/{plain['session_id']}/nudge").status_code == 409


def test_events_endpoint_and_snapshot_carry_the_log(client: TestClient) -> None:
    body = _park(client)
    client.post(f"/sessions/{body['session_id']}/nudge")
    rows = client.get("/stations/1/events?limit=20").json()
    types = [r["type"] for r in rows]
    assert {"registered", "done", "nudged"} <= set(types)
    assert [r["seq"] for r in rows] == sorted((r["seq"] for r in rows), reverse=True)  # newest first
    assert rows[0]["model_name"]
    with client.websocket_connect("/ws/stations/1") as ws:
        snap = ws.receive_json()
        assert snap["events"] and snap["events"][0]["seq"] == rows[0]["seq"]
        assert "kpi" in snap


def test_parked_block_is_in_the_schedule(client: TestClient) -> None:
    body = _park(client)
    sched = client.get("/stations/1/schedule").json()
    parked = [
        b for c in sched["chargers"] for b in c["blocks"] if b["session_id"] == body["session_id"]
    ]
    assert len(parked) == 1 and parked[0]["kind"] == "parked"
    assert parked[0]["overstay_min"] is not None and parked[0]["nudged"] is False


def test_kpi_history_is_seeded_oldest_first(client: TestClient) -> None:
    rows = client.get("/stations/1/kpi/history").json()
    assert len(rows) == 7
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert set(rows[0]) == {"date", "sessions", "avg_wait_min", "load_factor", "peak_reduction_kw"}


def test_sim_pause_and_scenario_loaded_without_autostart(client: TestClient) -> None:
    state = client.post(
        "/sim/start", json={"scenario": "demo", "speed": 10, "autostart": False}
    ).json()
    assert state["running"] is False and state["scenario"] == "demo" and state["speed"] == 10
    assert client.post("/sim/start", json={"speed": 10}).json()["running"] is True
    assert client.post("/sim/pause").json()["running"] is False
