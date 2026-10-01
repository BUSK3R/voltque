from datetime import UTC, datetime, timedelta

import pytest

from app.engine.charge_time import VehicleParams, calc_for
from app.engine.scheduler import NO_SHOW_GRACE_MIN, TAU_MIN
from app.sim.runner import SimManager, find_scenario, load_scenario, run_scenario
from app.sim.world import ChargerSpec, NoChargerError, SimWorld, VehicleInfo

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

CHARGERS = (ChargerSpec(1, 50), ChargerSpec(2, 100), ChargerSpec(3, 350))
VEHICLES = {
    v.model_name: v
    for v in (
        VehicleInfo(1, "아이오닉 5 (예시)", VehicleParams(77.4, 220, 0.92, 80, 0.20)),
        VehicleInfo(2, "EV6 (예시)", VehicleParams(77.4, 233, 0.92, 80, 0.20)),
        VehicleInfo(3, "테슬라 모델 3 (예시)", VehicleParams(60.0, 170, 0.92, 80, 0.25)),
        VehicleInfo(4, "코나 일렉트릭 (예시)", VehicleParams(64.8, 100, 0.92, 80, 0.20)),
        VehicleInfo(5, "레이 EV (예시)", VehicleParams(35.2, 70, 0.92, 80, 0.30)),
    )
}
IONIQ = VEHICLES["아이오닉 5 (예시)"]
RAY = VEHICLES["레이 EV (예시)"]
KONA = VEHICLES["코나 일렉트릭 (예시)"]


def world(chargers: tuple[ChargerSpec, ...] = CHARGERS, mode: str = "controlled",
          contract_kw: float = 400) -> SimWorld:
    return SimWorld(chargers, contract_kw, 0.9, T0, mode)  # type: ignore[arg-type]


def single(contract_kw: float = 400) -> SimWorld:
    return world((ChargerSpec(1, 100),), contract_kw=contract_kw)


def add(w: SimWorld, sid: int, v: VehicleInfo = IONIQ, s0: float = 20, s1: float = 90,
        delay: float = TAU_MIN) -> None:
    w.register(sid, v, f"sim-{sid}", s0, s1, delay)


def minutes_to(w: SimWorld, predicate: object, limit: float = 600) -> float:
    start = w.now
    while not predicate() and (w.now - start).total_seconds() < limit * 60:  # type: ignore[operator]
        w.step()
    return (w.now - start).total_seconds() / 60


# --- charging basics ---------------------------------------------------------------


def test_charge_duration_matches_engine() -> None:
    w = single()
    add(w, 1)
    m = minutes_to(w, lambda: w.sessions[1].status == "done")
    expected = TAU_MIN + calc_for(IONIQ.params, 20, 90, 100).total_min
    assert m == pytest.approx(expected, abs=0.7)  # tick discretisation


def test_register_validates_input() -> None:
    w = single()
    with pytest.raises(ValueError):
        add(w, 1, s0=90, s1=50)
    assert w.sessions == {}


def test_no_charger_available() -> None:
    w = world((ChargerSpec(1, 100, fault=True),))
    with pytest.raises(NoChargerError):
        add(w, 1)


def test_deterministic_runs() -> None:
    def run() -> list[tuple[datetime, float]]:
        w = single()
        add(w, 1)
        add(w, 2, RAY, 30, 80)
        w.advance(3600)
        return w.history

    assert run() == run()


# --- queue behaviour (E-03) ---------------------------------------------------------


def test_following_block_is_pulled_forward_when_current_session_is_cancelled() -> None:
    w = single()
    add(w, 1)
    add(w, 2)
    w.advance(10 * 60)  # 1 is charging, 2 is waiting
    before = w.find_block(2)
    assert before is not None
    w.cancel(1)
    after = w.find_block(2)
    assert after is not None
    assert after[1].start < before[1].start - timedelta(minutes=10)


def test_following_block_is_pulled_forward_when_session_finishes_early() -> None:
    w = single()
    add(w, 1, s0=20, s1=90)
    add(w, 2)
    w.advance(5 * 60)
    planned = w.find_block(2)
    assert planned is not None
    minutes_to(w, lambda: w.sessions[1].status == "done")
    w.advance(5 * 60)
    started = w.sessions[2].actual_start
    assert started is not None
    # the real start is no later than the plan made while 1 was still running (+ tick error)
    assert started <= planned[1].start + timedelta(seconds=30)


def test_cancel_updates_queue_positions() -> None:
    w = single()
    for sid in (1, 2, 3, 4):
        add(w, sid)
        w.advance(1)
    w.advance(10 * 60)
    pos = {sid: w.find_block(sid)[1].queue_pos for sid in (2, 3, 4)}  # type: ignore[index]
    assert pos == {2: 1, 3: 2, 4: 3}
    w.cancel(2)
    assert w.find_block(2) is None
    assert w.find_block(3)[1].queue_pos == 1  # type: ignore[index]
    assert w.find_block(4)[1].queue_pos == 2  # type: ignore[index]
    with pytest.raises(ValueError):
        w.cancel(2)


def test_cancel_emits_event_and_unknown_id_raises() -> None:
    w = single()
    add(w, 1)
    w.cancel(1)
    assert any(e.type == "cancelled" and e.session_id == 1 for e in w.events)
    with pytest.raises(KeyError):
        w.cancel(99)


def test_fifo_order_in_single_queue() -> None:
    w = single()
    for sid in (1, 2, 3):
        add(w, sid)
        w.advance(30)
    minutes_to(w, lambda: all(w.sessions[i].status == "done" for i in (1, 2, 3)))
    starts = [w.sessions[i].actual_start for i in (1, 2, 3)]
    assert starts == sorted(starts)  # type: ignore[type-var]


# --- no-show (P0) -------------------------------------------------------------------


def test_no_show_demotes_to_the_back_and_next_gets_the_slot() -> None:
    w = single()
    add(w, 1, delay=NO_SHOW_GRACE_MIN + 1)  # never shows up within the grace period
    add(w, 2)
    w.advance(30)
    add(w, 3)
    w.advance((NO_SHOW_GRACE_MIN + 1) * 60)
    assert w.sessions[1].no_show_count == 1
    assert w.sessions[1].status in ("waiting", "called")
    assert w.sessions[2].status in ("called", "charging")
    # 1 re-registered behind 3 (queue positions are 1-based; called 2 holds position 1)
    pos = {sid: w.find_block(sid)[1].queue_pos or 0 for sid in (1, 2, 3)}  # type: ignore[index]
    assert pos[2] == 1
    assert pos[3] < pos[1]
    assert any(e.type == "no_show" and e.session_id == 1 for e in w.events)


def test_second_no_show_ends_the_session() -> None:
    w = single()
    add(w, 1, delay=NO_SHOW_GRACE_MIN + 1)
    w.advance(60 * 60)
    assert w.sessions[1].status == "no_show"
    assert w.find_block(1) is None


# --- load control (E-04) --------------------------------------------------------------


def test_controlled_never_exceeds_limit_under_stress() -> None:
    w = world(contract_kw=250)  # limit 225 kW, vs 340 kW of demand
    for sid, (v, s0, s1) in enumerate(
        [(IONIQ, 20, 90), (IONIQ, 10, 100), (KONA, 30, 80), (RAY, 5, 80), (IONIQ, 40, 90)],
        start=1,
    ):
        add(w, sid, v, s0, s1)
    for _ in range(int(4 * 3600 / 10)):
        w.step()
        assert w.site_kw <= w.limit_kw + 1e-6
    assert w.totals.over_limit_s == 0
    assert w.is_idle()


def test_baseline_exceeds_the_limit_in_the_same_situation() -> None:
    w = world(mode="baseline", contract_kw=250)
    for sid, v in enumerate([IONIQ, IONIQ, KONA], start=1):
        add(w, sid, v, 20, 90)
    w.advance(3600)
    assert w.totals.over_limit_s > 0
    assert w.totals.peak_kw > w.limit_kw


def test_limited_start_when_headroom_is_between_half_and_full_p_eff() -> None:
    w = world(contract_kw=300)  # limit 270
    add(w, 1, IONIQ, 20, 90)  # 350kW charger, 202.4 kW
    add(w, 2, IONIQ, 20, 90)  # 100kW charger, P_eff 92 -> R = 67.6 >= 46
    w.advance(5 * 60)
    s2 = w.sessions[2]
    assert s2.alloc_cap_kw == pytest.approx(270 - 202.4)
    assert s2.notice
    assert any(e.type == "limited" and e.session_id == 2 for e in w.events)
    # T is recomputed with the lower output -> longer than the unconstrained estimate
    block = w.find_block(2)
    assert block is not None
    assert (block[1].end - block[1].start) > timedelta(
        minutes=calc_for(IONIQ.params, 20, 90, 100).total_min
    )


def test_delayed_start_gives_reason_and_forecast() -> None:
    w = world(contract_kw=300)
    add(w, 1, IONIQ, 20, 90)
    add(w, 2, IONIQ, 20, 90)
    add(w, 3, KONA, 30, 80)  # 50 kW charger: R ~ 0 < 23 -> delay
    w.advance(5 * 60)
    s3 = w.sessions[3]
    assert s3.status == "waiting"
    assert s3.notice and "지연" in s3.notice
    assert s3.resume_at is not None and s3.resume_at > w.now
    assert any(e.type == "delayed" and e.session_id == 3 for e in w.events)
    # it starts once tapering / session ends free enough power
    minutes_to(w, lambda: w.sessions[3].status in ("called", "charging", "done"))
    assert w.sessions[3].status in ("called", "charging", "done")


def test_freed_headroom_goes_to_the_delayed_waiter() -> None:
    w = world(contract_kw=300)
    add(w, 1, IONIQ, 20, 90)
    add(w, 2, IONIQ, 20, 90)
    add(w, 3, KONA, 30, 80)
    w.advance(60)
    assert w.sessions[3].status == "waiting"
    minutes_to(w, lambda: w.sessions[3].actual_start is not None)
    started = w.sessions[3].actual_start
    assert started is not None
    # still before the first long session is done: it started thanks to tapering/redistribution
    assert w.sessions[1].status != "done" or w.sessions[2].status != "done"


# --- demo scenario (completion criterion) --------------------------------------------


def test_demo_scenario_at_60x_controlled_stays_under_limit_and_beats_baseline() -> None:
    sc = load_scenario(find_scenario("demo"))
    mgr = run_scenario(sc, CHARGERS, VEHICLES, 400, 0.9, T0, speed=60)
    controlled, baseline = mgr.worlds["controlled"], mgr.worlds["baseline"]
    assert mgr.contract_kw == 300  # scenario override
    assert controlled.totals.over_limit_s == 0
    assert max(kw for _, kw in controlled.history) <= controlled.limit_kw + 1e-6
    assert controlled.totals.peak_kw < baseline.totals.peak_kw
    assert baseline.totals.over_limit_s > 0
    assert controlled.is_idle() and baseline.is_idle()


def test_demo_scenario_result_does_not_depend_on_speed() -> None:
    sc = load_scenario(find_scenario("demo"))
    a = run_scenario(sc, CHARGERS, VEHICLES, 400, 0.9, T0, speed=1)
    b = run_scenario(sc, CHARGERS, VEHICLES, 400, 0.9, T0, speed=60)
    assert a.primary.history[:100] == b.primary.history[:100]
    assert a.primary.totals.peak_kw == b.primary.totals.peak_kw
    assert a.primary.kpi()["sessions_done"] == b.primary.kpi()["sessions_done"]


def test_manager_registers_in_both_worlds_with_the_same_id() -> None:
    mgr = SimManager(CHARGERS, VEHICLES, 400, 0.9, T0)
    s = mgr.register(1, None, 20, 90)
    assert s.session_id in mgr.worlds["baseline"].sessions
    mgr.cancel(s.session_id)
    assert mgr.worlds["baseline"].sessions[s.session_id].status == "cancelled"
    with pytest.raises(ValueError):
        mgr.register(1, None, 90, 20)
    assert len(mgr.worlds["baseline"].sessions) == 1  # failed request left nothing behind


# --- parked (finished but still plugged in) and operator nudge (A-05) -------------------


def add_parked(w: SimWorld, sid: int, leave: float, s0: float = 70, s1: float = 80) -> None:
    w.register(sid, IONIQ, f"sim-{sid}", s0, s1, TAU_MIN, None, leave)


def test_parked_car_blocks_the_charger_until_it_leaves() -> None:
    w = single()
    add_parked(w, 1, leave=12)
    add(w, 2, RAY, 20, 60)
    minutes_to(w, lambda: w.sessions[1].status == "done")
    assert w.sessions[1].parked and w.schedule()[0].status == "occupied"
    assert w.sessions[2].status == "waiting"  # the head is NOT called while the car is parked
    block = w.schedule()[0].blocks[0]
    assert block.kind == "parked" and block.session_id == 1
    minutes_to(w, lambda: not w.sessions[1].parked)
    assert w.sessions[2].status in ("called", "charging")
    left = [e for e in w.events if e.type == "left"]
    assert len(left) == 1 and left[0].payload["dwell_min"] == pytest.approx(12, abs=0.3)


def test_overstay_is_flagged_once_after_five_minutes() -> None:
    w = single()
    add_parked(w, 1, leave=20)
    minutes_to(w, lambda: w.sessions[1].status == "done")
    done_at = w.sessions[1].actual_end
    assert done_at is not None
    minutes_to(w, lambda: any(e.type == "overstay" for e in w.events))
    flagged = [e for e in w.events if e.type == "overstay"]
    assert len(flagged) == 1
    assert (flagged[0].ts - done_at).total_seconds() / 60 == pytest.approx(5, abs=0.3)
    for _ in range(60):
        w.step()
    assert len([e for e in w.events if e.type == "overstay"]) == 1
    view = w.schedule()[0].blocks[0]
    assert view.overstay_min is not None and view.overstay_min > 5 and not view.nudged


def test_nudge_makes_the_driver_leave_soon_and_is_idempotent() -> None:
    w = single()
    add_parked(w, 1, leave=30)
    minutes_to(w, lambda: w.sessions[1].status == "done")
    w.nudge(1)
    assert w.schedule()[0].blocks[0].nudged
    first = w.sessions[1].leave_at
    w.step()
    w.nudge(1)  # a second press changes nothing
    assert w.sessions[1].leave_at == first
    assert len([e for e in w.events if e.type == "nudged"]) == 1
    minutes_to(w, lambda: not w.sessions[1].parked, limit=5)
    assert not w.sessions[1].parked  # left well before the original 30 min


def test_nudge_rejects_unknown_and_not_parked_sessions() -> None:
    w = single()
    add(w, 1)
    with pytest.raises(KeyError):
        w.nudge(99)
    with pytest.raises(ValueError):
        w.nudge(1)  # still waiting / charging


def test_manager_nudge_keeps_both_worlds_in_step() -> None:
    mgr = SimManager(CHARGERS, VEHICLES, 400, 0.9, T0)
    s = mgr.register(IONIQ.vehicle_id, None, 70, 80, TAU_MIN, 3, 30)
    while not mgr.worlds["controlled"].sessions[s.session_id].parked:
        mgr.advance(10)
    mgr.nudge(s.session_id)
    assert mgr.worlds["baseline"].sessions[s.session_id].nudged_at is not None


def test_load_factor_is_mean_over_peak() -> None:
    w = single()
    add(w, 1)
    minutes_to(w, lambda: w.sessions[1].status == "done")
    k = w.kpi()
    mean = sum(kw for _, kw in w.history) / len(w.history)
    assert k["load_factor"] == pytest.approx(mean / k["peak_kw"])
    assert 0 < k["load_factor"] <= 1


def test_demo_scenario_exercises_overstay() -> None:
    sc = load_scenario(find_scenario("demo"))
    mgr = run_scenario(sc, CHARGERS, VEHICLES, 400, 0.9, T0, speed=60)
    types = {e.type for e in mgr.primary.events}
    assert {"overstay", "left"} <= types
    assert mgr.finished()
