"""Charge-time engine (PRD 3.1~3.3). Pure functions: no DB, FastAPI or clock access."""

import math
from dataclasses import dataclass
from datetime import datetime

LOW_FACTOR = 0.92
HIGH_FACTOR = 1.10


@dataclass(frozen=True)
class Segment:
    """One SoC interval of the calculation, for the "show calculation" UI."""

    name: str  # "constant" (<= sT) or "taper" (> sT)
    soc_from: float
    soc_to: float
    minutes: float  # gamma applied, so segments sum to total_min


@dataclass(frozen=True)
class ChargeTimeResult:
    total_min: float
    low_min: float
    high_min: float
    t1_min: float
    t2_min: float
    p_eff_kw: float
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class VehicleParams:
    """Vehicle-side inputs of the charge-time model (demo example values, PRD 3.1)."""

    battery_kwh: float
    max_kw: float
    efficiency: float = 0.92
    taper_start: float = 80.0
    taper_min_ratio: float = 0.2


@dataclass(frozen=True)
class ActiveSession:
    """Engine-side snapshot of a charging session (decoupled from the ORM model)."""

    battery_kwh: float
    soc_start: float
    soc_target: float
    charger_kw: float
    vehicle_max_kw: float
    efficiency: float
    started_at: datetime
    taper_start: float = 80.0
    taper_min_ratio: float = 0.2
    gamma: float = 1.0
    soc_reported: float | None = None  # charger-reported SoC; preferred over back-calculation


def _validate(
    battery_kwh: float,
    soc_now: float,
    soc_target: float,
    charger_kw: float,
    vehicle_max_kw: float,
    efficiency: float,
    taper_start: float,
    taper_min_ratio: float,
    gamma: float,
) -> None:
    if not (0 <= soc_now < soc_target <= 100):
        raise ValueError(f"require 0 <= soc_now < soc_target <= 100, got {soc_now}, {soc_target}")
    if battery_kwh <= 0 or charger_kw <= 0 or vehicle_max_kw <= 0:
        raise ValueError("battery_kwh, charger_kw and vehicle_max_kw must be positive")
    if not (0 < efficiency <= 1):
        raise ValueError("efficiency must be in (0, 1]")
    if not (0 <= taper_start < 100):
        raise ValueError("taper_start must be in [0, 100)")
    if not (0 < taper_min_ratio <= 1):
        raise ValueError("taper_min_ratio must be in (0, 1]")
    if gamma <= 0:
        raise ValueError("gamma must be positive")


def _hours(
    battery_kwh: float,
    s0: float,
    s1: float,
    p_eff: float,
    taper_start: float,
    taper_min_ratio: float,
) -> tuple[float, float]:
    """Return (T1, T2) in hours, gamma not applied."""
    t1 = battery_kwh * max(min(s1, taper_start) - s0, 0.0) / (100 * p_eff)
    t2 = 0.0
    if s1 > taper_start:
        alpha = 1 - taper_min_ratio
        a = max(s0, taper_start)
        if alpha == 0:  # no tapering: output stays constant
            t2 = battery_kwh * (s1 - a) / (100 * p_eff)
        else:
            span = 100 - taper_start
            k_a = 1 - alpha * (a - taper_start) / span
            k_s1 = 1 - alpha * (s1 - taper_start) / span
            t2 = battery_kwh * span / (100 * alpha * p_eff) * math.log(k_a / k_s1)
    return t1, t2


def calc_charge_time(
    battery_kwh: float,
    soc_now: float,
    soc_target: float,
    charger_kw: float,
    vehicle_max_kw: float,
    efficiency: float,
    taper_start: float = 80,
    taper_min_ratio: float = 0.2,
    gamma: float = 1.0,
) -> ChargeTimeResult:
    """Charge time from soc_now to soc_target. Raises ValueError on invalid input."""
    _validate(
        battery_kwh,
        soc_now,
        soc_target,
        charger_kw,
        vehicle_max_kw,
        efficiency,
        taper_start,
        taper_min_ratio,
        gamma,
    )
    p_eff = min(charger_kw, vehicle_max_kw) * efficiency
    t1_h, t2_h = _hours(
        battery_kwh, soc_now, soc_target, p_eff, taper_start, taper_min_ratio
    )
    t1_min = gamma * t1_h * 60
    t2_min = gamma * t2_h * 60
    total = t1_min + t2_min

    segments: list[Segment] = []
    if soc_now < taper_start:
        segments.append(Segment("constant", soc_now, min(soc_target, taper_start), t1_min))
    if soc_target > taper_start:
        segments.append(Segment("taper", max(soc_now, taper_start), soc_target, t2_min))

    return ChargeTimeResult(
        total_min=total,
        low_min=LOW_FACTOR * total,
        high_min=HIGH_FACTOR * total,
        t1_min=t1_min,
        t2_min=t2_min,
        p_eff_kw=p_eff,
        segments=tuple(segments),
    )


def _minutes_between(s: ActiveSession, soc_from: float, soc_to: float) -> float:
    r = calc_charge_time(
        s.battery_kwh,
        soc_from,
        soc_to,
        s.charger_kw,
        s.vehicle_max_kw,
        s.efficiency,
        s.taper_start,
        s.taper_min_ratio,
        s.gamma,
    )
    return r.total_min


def estimate_soc(session: ActiveSession, now: datetime) -> float:
    """Back-calculate current SoC from elapsed time (numeric inverse of the integral).

    Bisection with a fixed iteration count keeps the result deterministic.
    """
    elapsed = (now - session.started_at).total_seconds() / 60
    if elapsed <= 0:
        return session.soc_start
    if elapsed >= _minutes_between(session, session.soc_start, session.soc_target):
        return session.soc_target
    lo, hi = session.soc_start, session.soc_target
    for _ in range(60):
        mid = (lo + hi) / 2
        if _minutes_between(session, session.soc_start, mid) < elapsed:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def remaining_time(session: ActiveSession, now: datetime) -> ChargeTimeResult:
    """Remaining time of an in-progress session, re-calculated from the current SoC."""
    soc = session.soc_reported if session.soc_reported is not None else estimate_soc(session, now)
    if soc >= session.soc_target:
        p_eff = min(session.charger_kw, session.vehicle_max_kw) * session.efficiency
        return ChargeTimeResult(0.0, 0.0, 0.0, 0.0, 0.0, p_eff, ())
    return calc_charge_time(
        session.battery_kwh,
        soc,
        session.soc_target,
        session.charger_kw,
        session.vehicle_max_kw,
        session.efficiency,
        session.taper_start,
        session.taper_min_ratio,
        session.gamma,
    )


def taper_factor(soc: float, taper_start: float, taper_min_ratio: float) -> float:
    """k(s) of PRD 3.2 (2): 1 up to sT, then linear decrease down to kmin at 100%."""
    if soc <= taper_start:
        return 1.0
    alpha = 1 - taper_min_ratio
    return 1 - alpha * (soc - taper_start) / (100 - taper_start)


def p_eff_kw(vehicle: VehicleParams, charger_kw: float) -> float:
    """P_eff = min(Pc, Pv) x eta."""
    return min(charger_kw, vehicle.max_kw) * vehicle.efficiency


def demand_kw(vehicle: VehicleParams, charger_kw: float, soc: float) -> float:
    """Instantaneous power the vehicle would draw at this SoC: P_eff x k(s)."""
    return p_eff_kw(vehicle, charger_kw) * taper_factor(
        soc, vehicle.taper_start, vehicle.taper_min_ratio
    )


def calc_for(
    vehicle: VehicleParams,
    soc_now: float,
    soc_target: float,
    charger_kw: float,
    gamma: float = 1.0,
) -> ChargeTimeResult:
    """calc_charge_time with the vehicle parameters bundled."""
    return calc_charge_time(
        vehicle.battery_kwh,
        soc_now,
        soc_target,
        charger_kw,
        vehicle.max_kw,
        vehicle.efficiency,
        vehicle.taper_start,
        vehicle.taper_min_ratio,
        gamma,
    )
