from datetime import UTC, datetime, timedelta

import pytest

from app.engine.charge_time import VehicleParams
from app.engine.load import RunningLoad, decide_start, forecast_resume, site_limit_kw

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CAR = VehicleParams(battery_kwh=77.4, max_kw=220)


def test_site_limit_is_lambda_times_contract() -> None:
    assert site_limit_kw(400) == pytest.approx(360)
    assert site_limit_kw(300, 0.8) == pytest.approx(240)


def test_start_at_full_power_when_headroom_is_enough() -> None:
    d = decide_start(NOW, p_eff_kw=92, committed_kw=200, limit_kw=360, running=[])
    assert d.action == "start"
    assert d.alloc_kw == pytest.approx(92)
    assert d.resume_at is None


def test_exact_headroom_is_a_full_start() -> None:
    d = decide_start(NOW, 92, committed_kw=268, limit_kw=360, running=[])
    assert d.action == "start"


def test_limited_start_when_headroom_is_at_least_half_of_p_eff() -> None:
    d = decide_start(NOW, 92, committed_kw=300, limit_kw=360, running=[])  # R = 60 >= 46
    assert d.action == "limit"
    assert d.alloc_kw == pytest.approx(60)
    assert "60" in d.reason


def test_half_boundary_is_limited_not_delayed() -> None:
    d = decide_start(NOW, 92, committed_kw=314, limit_kw=360, running=[])  # R = 46
    assert d.action == "limit"
    assert d.alloc_kw == pytest.approx(46)


def test_delay_when_headroom_is_below_half() -> None:
    d = decide_start(NOW, 92, committed_kw=330, limit_kw=360, running=[])  # R = 30 < 46
    assert d.action == "delay"
    assert d.alloc_kw == 0
    assert d.reason


def test_no_headroom_at_all_is_a_delay() -> None:
    d = decide_start(NOW, 92, committed_kw=400, limit_kw=360, running=[])
    assert d.action == "delay"


def test_delay_reports_when_taper_frees_enough_power() -> None:
    # One session at 70% SoC drawing 202 kW; limit 270. Tapering starts at 80%.
    running = [RunningLoad(soc=70, soc_target=100, vehicle=CAR, charger_kw=350)]
    d = decide_start(NOW, 92, committed_kw=202, limit_kw=240, running=running)
    assert d.action == "delay"
    assert d.resume_at is not None
    assert d.resume_at > NOW


def test_forecast_none_when_never_frees_within_horizon() -> None:
    # Running load that keeps the full limit busy for the whole horizon.
    running = [RunningLoad(soc=5, soc_target=100, vehicle=CAR, charger_kw=350)]
    assert forecast_resume(NOW, running, limit_kw=214, needed_kw=46, horizon_min=10) is None


def test_forecast_uses_session_end_as_release() -> None:
    running = [RunningLoad(soc=89, soc_target=90, vehicle=CAR, charger_kw=350)]
    at = forecast_resume(NOW, running, limit_kw=214, needed_kw=200)
    assert at is not None
    assert NOW < at < NOW + timedelta(minutes=10)


def test_forecast_is_immediate_when_already_enough() -> None:
    assert forecast_resume(NOW, [], limit_kw=100, needed_kw=40) == NOW
