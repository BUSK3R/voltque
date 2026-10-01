import datetime as dt
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.scheduler import TAU_MIN


class VehicleOut(BaseModel):
    vehicle_id: int
    model_name: str
    battery_kwh: float
    max_dc_kw: float


class SessionCreate(BaseModel):
    vehicle_id: int
    soc_start: float = Field(ge=0, le=100)
    soc_target: float = Field(ge=0, le=100)
    anon_user_id: str | None = Field(default=None, max_length=64)  # anonymous id only (PRD 4.4)
    enter_delay_min: float = Field(default=TAU_MIN, ge=0, le=30)  # simulated driver response
    leave_delay_min: float = Field(default=0, ge=0, le=60)  # > 0: stays plugged in after done
    charger_id: int | None = None  # None = automatic assignment


class EstimateIn(BaseModel):
    vehicle_id: int
    soc_start: float = Field(ge=0, le=100)
    soc_target: float = Field(ge=0, le=100)
    charger_id: int | None = None


class SegmentOut(BaseModel):
    name: str
    soc_from: float
    soc_to: float
    minutes: float


class CalcOut(BaseModel):
    """Everything "계산 근거 보기" needs."""

    total_min: float
    low_min: float
    high_min: float
    t1_min: float
    t2_min: float
    p_eff_kw: float
    charger_kw: float
    segments: list[SegmentOut]


class EstimateOut(BaseModel):
    charger_id: int
    calc: CalcOut
    expected_start: datetime
    expected_end: datetime


class LaneBlock(BaseModel):
    """One block of my charger's lane up to and including mine (M3 timeline)."""

    session_id: int
    kind: str
    status: str
    start: datetime
    end: datetime
    is_me: bool


class SessionOut(BaseModel):
    session_id: int
    status: str
    charger_id: int
    vehicle_id: int
    model_name: str
    soc_start: float
    soc_target: float
    soc_current: float
    battery_kwh: float
    charged_kwh: float
    current_kw: float
    queue_pos: int | None  # 1-based among called+waiting
    ahead: int  # vehicles in front, including the one charging
    planned_start: datetime | None
    planned_end: datetime | None
    alloc_kw: float | None  # set when the start was output-limited
    notice: str | None  # reason for a limit / delay (D-06)
    resume_at: datetime | None
    called_at: datetime | None
    no_show_at: datetime | None  # called_at + grace period
    no_show_count: int
    actual_start: datetime | None
    actual_end: datetime | None
    parked: bool  # finished but still plugged in (blocks the charger)
    leave_at: datetime | None
    nudged_at: datetime | None  # the operator asked the driver to move the car (A-05)
    lane: list[LaneBlock]
    calc: CalcOut


class BlockOut(BaseModel):
    session_id: int
    kind: str
    status: str
    start: datetime
    end: datetime
    queue_pos: int | None
    model_name: str
    soc_start: float
    soc_target: float
    soc_current: float
    alloc_kw: float | None
    notice: str | None
    overstay_min: float | None  # parked blocks: minutes since the charge finished
    nudged: bool


class ChargerOut(BaseModel):
    charger_id: int
    rated_kw: float
    connector_type: str
    status: str
    queue_total: int
    free_at: datetime  # when the last planned block ends (now if nothing is planned)
    blocks: list[BlockOut]  # current + up to 2 waiting


class ScheduleOut(BaseModel):
    station_id: int
    station_name: str
    now: datetime
    running: bool
    speed: int
    contract_kw: float
    limit_kw: float
    chargers: list[ChargerOut]


class LoadPoint(BaseModel):
    ts: datetime
    kw: float


class LoadOut(BaseModel):
    station_id: int
    now: datetime
    contract_kw: float
    limit_kw: float
    now_kw: float
    baseline_now_kw: float
    controlled: list[LoadPoint]
    baseline: list[LoadPoint]


class KpiOut(BaseModel):
    station_id: int
    sessions_done: int
    avg_wait_min: float
    load_factor: float
    peak_kw: float
    baseline_peak_kw: float
    peak_reduction_kw: float
    over_limit_min: float
    baseline_over_limit_min: float


class EventOut(BaseModel):
    """One row of the operator event log (A-05)."""

    seq: int
    ts: datetime
    type: str
    session_id: int | None
    model_name: str | None
    payload: dict[str, Any]


class KpiDayOut(BaseModel):
    date: dt.date
    sessions: int
    avg_wait_min: float
    load_factor: float
    peak_reduction_kw: float


class SimState(BaseModel):
    running: bool
    speed: int
    scenario: str | None
    now: datetime
    elapsed_min: float


class SimStart(BaseModel):
    scenario: str | None = None  # file name in backend/scenarios without .json
    speed: Literal[1, 10, 60] = 1
    autostart: bool = True  # False: load the scenario but leave the clock stopped


class SimSpeed(BaseModel):
    speed: Literal[1, 10, 60]
