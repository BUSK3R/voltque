"""Peak-aware start control (PRD 3.5). Pure functions.

Loads are expressed in the same unit as P_eff (power delivered to the battery), as in the PRD.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.engine.charge_time import VehicleParams, demand_kw

LIMIT_RATIO = 0.9  # lambda
MIN_START_RATIO = 0.5  # limited start needs R >= 50% of P_eff
FORECAST_HORIZON_MIN = 240.0
FORECAST_STEP_MIN = 1.0


@dataclass(frozen=True)
class RunningLoad:
    """A session that already draws (or has reserved) power, for the release forecast."""

    soc: float
    soc_target: float
    vehicle: VehicleParams
    charger_kw: float


@dataclass(frozen=True)
class StartDecision:
    action: Literal["start", "limit", "delay"]
    alloc_kw: float  # 0 for a delay
    reason: str  # shown to the driver (D-06); empty for a normal start
    resume_at: datetime | None = None  # forecast start time for a delay


def site_limit_kw(contract_kw: float, limit_ratio: float = LIMIT_RATIO) -> float:
    """lambda x P_contract."""
    return contract_kw * limit_ratio


def forecast_resume(
    now: datetime,
    running: Sequence[RunningLoad],
    limit_kw: float,
    needed_kw: float,
    horizon_min: float = FORECAST_HORIZON_MIN,
    step_min: float = FORECAST_STEP_MIN,
) -> datetime | None:
    """First time the headroom reaches `needed_kw`, from session ends and tapering.

    Returns None if it does not happen within the horizon.
    """
    socs = [r.soc for r in running]
    t = 0.0
    while t <= horizon_min:
        draw = 0.0
        for i, r in enumerate(running):
            if socs[i] >= r.soc_target:
                continue
            p = demand_kw(r.vehicle, r.charger_kw, socs[i])
            draw += p
            socs[i] += 100 * p * (step_min / 60) / r.vehicle.battery_kwh
        if limit_kw - draw >= needed_kw - 1e-9:
            return now + timedelta(minutes=t)
        t += step_min
    return None


def decide_start(
    now: datetime,
    p_eff_kw: float,
    committed_kw: float,
    limit_kw: float,
    running: Sequence[RunningLoad],
) -> StartDecision:
    """Decide how a waiting vehicle may start given the current site load.

    R = limit - committed. R >= P_eff: normal start. R >= 50% of P_eff: start limited to R.
    Otherwise delay until the forecast time when enough power is released.
    """
    headroom = limit_kw - committed_kw
    if headroom >= p_eff_kw - 1e-9:
        return StartDecision("start", p_eff_kw, "")
    if headroom >= MIN_START_RATIO * p_eff_kw - 1e-9:
        return StartDecision(
            "limit",
            headroom,
            f"충전소 부하 한도({limit_kw:.0f}kW) 보호를 위해 출력을 {headroom:.0f}kW로 "
            "제한해 시작합니다. 다른 차량의 충전이 끝나도 이 출력으로 계속됩니다.",
        )
    resume = forecast_resume(now, running, limit_kw, MIN_START_RATIO * p_eff_kw)
    return StartDecision(
        "delay",
        0.0,
        f"충전소 부하 한도({limit_kw:.0f}kW)를 넘지 않도록 시작을 지연합니다. "
        "앞 차량의 충전이 끝나거나 출력이 낮아지면 시작됩니다.",
        resume,
    )
