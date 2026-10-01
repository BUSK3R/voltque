from datetime import UTC, datetime, timedelta

import pytest

from app.engine.charge_time import (
    ActiveSession,
    calc_charge_time,
    estimate_soc,
    remaining_time,
)

PRD = {
    "battery_kwh": 77.4,
    "soc_now": 20,
    "soc_target": 90,
    "charger_kw": 100,
    "vehicle_max_kw": 220,
    "efficiency": 0.92,
}


def test_prd_3_3_example() -> None:
    r = calc_charge_time(**PRD)
    assert r.p_eff_kw == pytest.approx(92.0)
    assert r.t1_min == pytest.approx(30.3, abs=0.1)
    assert r.t2_min == pytest.approx(6.4, abs=0.1)
    assert r.total_min == pytest.approx(36.7, abs=0.1)
    assert r.low_min == pytest.approx(33.8, abs=0.1)
    assert r.high_min == pytest.approx(40.4, abs=0.1)


def test_no_taper_segment_when_target_at_or_below_80() -> None:
    for target in (50, 79.9, 80):
        r = calc_charge_time(**{**PRD, "soc_target": target})
        assert r.t2_min == 0
        assert r.total_min == pytest.approx(r.t1_min)
        assert len(r.segments) == 1


def test_total_monotonic_increasing_above_80() -> None:
    totals = [
        calc_charge_time(**{**PRD, "soc_target": t}).total_min for t in (81, 85, 90, 95, 100)
    ]
    assert totals == sorted(totals)
    assert len(set(totals)) == len(totals)


def test_vehicle_limit_applies_when_charger_is_stronger() -> None:
    r = calc_charge_time(**{**PRD, "charger_kw": 350, "vehicle_max_kw": 100})
    assert r.p_eff_kw == pytest.approx(100 * 0.92)


def test_charger_limit_applies_when_vehicle_is_stronger() -> None:
    r = calc_charge_time(**{**PRD, "charger_kw": 50, "vehicle_max_kw": 220})
    assert r.p_eff_kw == pytest.approx(50 * 0.92)


@pytest.mark.parametrize(
    "now,target",
    [(90, 90), (95, 90), (-1, 50), (20, 101), (20, -5), (101, 102)],
)
def test_invalid_soc_raises(now: float, target: float) -> None:
    with pytest.raises(ValueError):
        calc_charge_time(**{**PRD, "soc_now": now, "soc_target": target})


@pytest.mark.parametrize(
    "field,value",
    [
        ("battery_kwh", 0),
        ("charger_kw", 0),
        ("vehicle_max_kw", -1),
        ("efficiency", 0),
        ("efficiency", 1.5),
    ],
)
def test_invalid_hardware_params_raise(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        calc_charge_time(**{**PRD, field: value})


def test_deterministic_100_calls() -> None:
    first = calc_charge_time(**PRD)
    assert all(calc_charge_time(**PRD) == first for _ in range(100))


def test_start_at_or_above_80_has_zero_t1() -> None:
    r = calc_charge_time(**{**PRD, "soc_now": 85, "soc_target": 95})
    assert r.t1_min == 0
    assert r.t2_min > 0
    assert r.total_min == pytest.approx(r.t2_min)


def test_gamma_scales_total_and_range() -> None:
    base = calc_charge_time(**PRD)
    winter = calc_charge_time(**PRD, gamma=1.10)
    assert winter.total_min == pytest.approx(base.total_min * 1.10)
    assert winter.low_min == pytest.approx(winter.total_min * 0.92)
    assert winter.high_min == pytest.approx(winter.total_min * 1.10)


def test_segments_cover_requested_range_and_sum_to_total() -> None:
    r = calc_charge_time(**PRD)
    assert r.segments[0].soc_from == 20
    assert r.segments[-1].soc_to == 90
    for a, b in zip(r.segments, r.segments[1:]):
        assert a.soc_to == b.soc_from
    assert sum(s.minutes for s in r.segments) == pytest.approx(r.total_min)


# --- remaining_time / estimate_soc -------------------------------------------------

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _session(**over: object) -> ActiveSession:
    base: dict[str, object] = {
        "battery_kwh": 77.4,
        "soc_start": 20.0,
        "soc_target": 90.0,
        "charger_kw": 100.0,
        "vehicle_max_kw": 220.0,
        "efficiency": 0.92,
        "started_at": T0,
    }
    base.update(over)
    return ActiveSession(**base)  # type: ignore[arg-type]


def test_estimate_soc_at_start_and_end() -> None:
    s = _session()
    assert estimate_soc(s, T0) == pytest.approx(20.0)
    total = calc_charge_time(**PRD).total_min
    assert estimate_soc(s, T0 + timedelta(minutes=total)) == pytest.approx(90.0, abs=1e-3)
    assert estimate_soc(s, T0 + timedelta(minutes=total + 30)) == 90.0


def test_estimate_soc_before_start_is_start_soc() -> None:
    assert estimate_soc(_session(), T0 - timedelta(minutes=5)) == 20.0


def test_estimate_soc_is_inverse_of_calc_charge_time() -> None:
    s = _session()
    for soc in (30.0, 60.0, 80.0, 85.0, 89.0):
        minutes = calc_charge_time(**{**PRD, "soc_target": soc}).total_min
        got = estimate_soc(s, T0 + timedelta(minutes=minutes))
        assert got == pytest.approx(soc, abs=1e-3)


def test_remaining_time_at_start_equals_full_calc() -> None:
    r = remaining_time(_session(), T0)
    assert r.total_min == pytest.approx(calc_charge_time(**PRD).total_min)


def test_remaining_time_decreases_and_is_consistent() -> None:
    s = _session()
    full = calc_charge_time(**PRD).total_min
    left = [remaining_time(s, T0 + timedelta(minutes=m)).total_min for m in (0, 10, 20, 30, 36)]
    assert left == sorted(left, reverse=True)
    # elapsed + remaining stays the whole charge time (uses reverse-calculated SoC)
    r = remaining_time(s, T0 + timedelta(minutes=20))
    assert 20 + r.total_min == pytest.approx(full, abs=0.01)


def test_remaining_time_zero_when_done() -> None:
    r = remaining_time(_session(), T0 + timedelta(hours=3))
    assert r.total_min == 0
    assert r.segments == ()


def test_remaining_time_uses_reported_soc_when_given() -> None:
    s = _session(soc_reported=85.0)
    r = remaining_time(s, T0 + timedelta(minutes=5))
    expected = calc_charge_time(**{**PRD, "soc_now": 85}).total_min
    assert r.total_min == pytest.approx(expected)


def test_remaining_time_deterministic() -> None:
    s = _session()
    now = T0 + timedelta(minutes=17)
    first = remaining_time(s, now)
    assert all(remaining_time(s, now) == first for _ in range(100))
