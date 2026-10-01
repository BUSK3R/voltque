"""Deterministic in-memory station simulation.

No DB, FastAPI, randomness or wall clock: time only moves through `step()` / `advance()`.
All decisions are delegated to the pure functions in `app.engine`.

Modes
- "controlled": VoltQueue (peak-aware start control, PRD 3.5)
- "baseline": same queue and chargers, but every vehicle starts at full power at once
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from app.engine.charge_time import (
    VehicleParams,
    calc_for,
    demand_kw,
    p_eff_kw,
)
from app.engine.load import RunningLoad, decide_start, site_limit_kw
from app.engine.scheduler import (
    NO_SHOW_GRACE_MIN,
    TAU_MIN,
    Block,
    ChargerInfo,
    QueueEntry,
    assign_charger,
    compute_blocks,
    demote_no_show,
    expected_start,
    find_no_shows,
    order_queue,
)

TICK_S = 10.0
LOG_INTERVAL_S = 60.0
MAX_NO_SHOWS = 2  # the second no-show ends the session (status no_show)
OVERSTAY_MIN = 5.0  # a finished vehicle still plugged in after this long is "abandoned" (PRD A-05)
NUDGE_LEAVE_MIN = 2.0  # simulated driver: leaves this long after the operator reminder
ACTIVE = ("waiting", "called", "charging")

Mode = Literal["baseline", "controlled"]


class NoChargerError(Exception):
    """No compatible, working charger exists for the vehicle."""


@dataclass(frozen=True)
class ChargerSpec:
    charger_id: int
    rated_kw: float
    connector_type: str = "DC_COMBO"
    fault: bool = False


@dataclass(frozen=True)
class VehicleInfo:
    vehicle_id: int
    model_name: str
    params: VehicleParams


@dataclass
class SimSession:
    session_id: int
    vehicle: VehicleInfo
    anon_user_id: str
    charger_id: int
    soc_start: float
    soc_target: float
    soc: float
    registered_at: datetime
    first_registered_at: datetime
    enter_delay_min: float = TAU_MIN
    leave_delay_min: float = 0.0  # simulated driver: minutes the car stays plugged in after done
    status: str = "waiting"  # waiting | called | charging | done | cancelled | no_show
    called_at: datetime | None = None
    enter_at: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    alloc_cap_kw: float | None = None  # P_alloc of a limited start; None = uncapped
    reserved_kw: float = 0.0  # power held while called but not yet charging
    p_kw: float = 0.0  # current draw
    no_show_count: int = 0
    notice: str | None = None  # why the driver is limited / delayed (D-06)
    resume_at: datetime | None = None  # forecast start of a delayed head
    calc_minutes: float | None = None
    parked: bool = False  # done, but the car still occupies the charger
    leave_at: datetime | None = None  # when a parked car will leave
    nudged_at: datetime | None = None  # operator reminder (A-05)
    overstay_flagged: bool = False


@dataclass(frozen=True)
class SimEvent:
    seq: int
    ts: datetime
    type: str
    session_id: int | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class BlockView:
    session_id: int
    kind: str  # charging | waiting | parked
    status: str  # charging | called | waiting | done (parked)
    start: datetime
    end: datetime
    queue_pos: int | None  # 1-based among called+waiting; None while charging
    model_name: str
    soc_start: float
    soc_target: float
    soc_current: float
    alloc_kw: float | None
    notice: str | None
    overstay_min: float | None = None  # parked blocks: minutes since the charge finished
    nudged: bool = False  # parked blocks: the operator already reminded the driver


@dataclass(frozen=True)
class ChargerView:
    charger_id: int
    rated_kw: float
    connector_type: str
    status: str
    blocks: tuple[BlockView, ...]


@dataclass
class _Totals:
    peak_kw: float = 0.0
    over_limit_s: float = 0.0


@dataclass
class SimWorld:
    chargers: tuple[ChargerSpec, ...]
    contract_kw: float
    limit_ratio: float
    t0: datetime
    mode: Mode = "controlled"
    now: datetime = field(init=False)
    sessions: dict[int, SimSession] = field(default_factory=dict)
    events: list[SimEvent] = field(default_factory=list)
    history: list[tuple[datetime, float]] = field(default_factory=list)
    totals: _Totals = field(default_factory=_Totals)
    _carry_s: float = 0.0
    _next_log: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.now = self.t0
        self._next_log = self.t0
        self._log_load(0.0)

    # ---- helpers ------------------------------------------------------------------

    @property
    def limit_kw(self) -> float:
        return site_limit_kw(self.contract_kw, self.limit_ratio)

    @property
    def site_kw(self) -> float:
        return sum(s.p_kw for s in self.sessions.values() if s.status == "charging")

    def _spec(self, charger_id: int) -> ChargerSpec:
        return next(c for c in self.chargers if c.charger_id == charger_id)

    def _emit(self, type_: str, session_id: int | None, **payload: Any) -> None:
        self.events.append(SimEvent(len(self.events) + 1, self.now, type_, session_id, payload))

    def _log_load(self, kw: float) -> None:
        self.history.append((self.now, kw))
        self._next_log = self.now + timedelta(seconds=LOG_INTERVAL_S)

    def _on_charger(self, charger_id: int, *statuses: str) -> list[SimSession]:
        return sorted(
            (
                s
                for s in self.sessions.values()
                if s.charger_id == charger_id and s.status in statuses
            ),
            key=lambda s: s.session_id,
        )

    def _parked_on(self, charger_id: int) -> list[SimSession]:
        return sorted(
            (s for s in self.sessions.values() if s.parked and s.charger_id == charger_id),
            key=lambda s: s.session_id,
        )

    def _entry(self, s: SimSession) -> QueueEntry:
        return QueueEntry(
            session_id=s.session_id,
            registered_at=s.registered_at,
            vehicle=s.vehicle.params,
            soc_start=s.soc_start,
            soc_target=s.soc_target,
            called_at=s.called_at if s.status == "called" else None,
        )

    def _queue(self, charger_id: int) -> list[QueueEntry]:
        rated = self._spec(charger_id).rated_kw
        entries = [self._entry(s) for s in self._on_charger(charger_id, "waiting", "called")]
        return order_queue(entries, self.now, rated)

    def _remaining_min(self, s: SimSession) -> float:
        if s.soc >= s.soc_target:
            return 0.0
        kw = self._spec(s.charger_id).rated_kw
        if s.alloc_cap_kw is not None:
            kw = min(kw, s.alloc_cap_kw / s.vehicle.params.efficiency)
        return calc_for(s.vehicle.params, s.soc, s.soc_target, kw).total_min

    def _charger_infos(self) -> list[ChargerInfo]:
        infos: list[ChargerInfo] = []
        for c in self.chargers:
            charging = self._on_charger(c.charger_id, "charging")
            parked = self._parked_on(c.charger_id)
            current: Block | None = None
            if charging:
                s = charging[0]
                end = self.now + timedelta(minutes=self._remaining_min(s))
                current = Block(s.session_id, "charging", s.actual_start or self.now, end)
            elif parked:
                s = parked[0]
                current = Block(
                    s.session_id, "parked", s.actual_end or self.now, s.leave_at or self.now
                )
            if c.fault:
                status = "fault"
            elif charging:
                status = "charging"
            else:
                status = "occupied" if parked else "idle"
            infos.append(ChargerInfo(c.charger_id, c.rated_kw, c.connector_type, status, current))
        return infos

    # ---- public commands -------------------------------------------------------------

    def register(
        self,
        session_id: int,
        vehicle: VehicleInfo,
        anon_user_id: str,
        soc_start: float,
        soc_target: float,
        enter_delay_min: float = TAU_MIN,
        charger_id: int | None = None,
        leave_delay_min: float = 0.0,
    ) -> SimSession:
        """Put a vehicle into the queue of the charger with the earliest expected start
        (or of `charger_id` when the driver picked one).

        Raises ValueError for invalid SoC input and NoChargerError if nothing can serve it.
        """
        if session_id in self.sessions:
            raise ValueError(f"duplicate session id {session_id}")
        fastest = max(c.rated_kw for c in self.chargers)
        calc_for(vehicle.params, soc_start, soc_target, fastest)  # validates the input
        entry = QueueEntry(
            session_id, self.now, vehicle.params, soc_start, soc_target, None, None
        )
        charger_id = self._pick_charger(entry, charger_id)
        s = SimSession(
            session_id=session_id,
            vehicle=vehicle,
            anon_user_id=anon_user_id,
            charger_id=charger_id,
            soc_start=soc_start,
            soc_target=soc_target,
            soc=soc_start,
            registered_at=self.now,
            first_registered_at=self.now,
            enter_delay_min=enter_delay_min,
            leave_delay_min=leave_delay_min,
            calc_minutes=calc_for(
                vehicle.params, soc_start, soc_target, self._spec(charger_id).rated_kw
            ).total_min,
        )
        self.sessions[session_id] = s
        self._emit("registered", session_id, charger_id=charger_id)
        return s

    def _pick_charger(self, entry: QueueEntry, wanted: int | None) -> int:
        infos = self._charger_infos()
        queues = {c.charger_id: self._queue(c.charger_id) for c in self.chargers}
        if wanted is None:
            picked = assign_charger(self.now, entry, infos, queues)
        else:
            ok = any(c.charger_id == wanted and not c.fault for c in self.chargers)
            picked = wanted if ok else None
        if picked is None:
            raise NoChargerError("이용 가능한 충전기가 없습니다.")
        return picked

    def preview(
        self,
        vehicle: VehicleInfo,
        soc_start: float,
        soc_target: float,
        charger_id: int | None = None,
    ) -> tuple[int, datetime]:
        """(charger, expected start) a new registration would get now; changes nothing."""
        fastest = max(c.rated_kw for c in self.chargers)
        calc_for(vehicle.params, soc_start, soc_target, fastest)  # validates the input
        entry = QueueEntry(-1, self.now, vehicle.params, soc_start, soc_target, None, None)
        picked = self._pick_charger(entry, charger_id)
        info = next(i for i in self._charger_infos() if i.charger_id == picked)
        return picked, expected_start(self.now, info, self._queue(picked))

    def cancel(self, session_id: int) -> SimSession:
        s = self.sessions.get(session_id)
        if s is None:
            raise KeyError(session_id)
        if s.status not in ACTIVE:
            raise ValueError(f"session {session_id} is already {s.status}")
        was = s.status
        s.status = "cancelled"
        s.actual_end = self.now
        s.p_kw = 0.0
        s.reserved_kw = 0.0
        self._emit("cancelled", session_id, was=was)
        return s

    def nudge(self, session_id: int) -> SimSession:
        """Operator reminder to a parked driver (A-05): the simulated driver leaves shortly."""
        s = self.sessions.get(session_id)
        if s is None:
            raise KeyError(session_id)
        if not s.parked:
            raise ValueError(f"session {session_id} is not parked")
        if s.nudged_at is None:
            s.nudged_at = self.now
            s.leave_at = min(
                s.leave_at or self.now, self.now + timedelta(minutes=NUDGE_LEAVE_MIN)
            )
            self._emit("nudged", session_id, charger_id=s.charger_id)
        return s

    # ---- time ----------------------------------------------------------------------

    def advance(self, seconds: float) -> None:
        """Move the clock forward in TICK_S steps (the remainder is carried over)."""
        total = self._carry_s + seconds
        n = math.floor(total / TICK_S + 1e-9)
        for _ in range(n):
            self.step()
        self._carry_s = total - n * TICK_S

    def step(self) -> None:
        dt_h = TICK_S / 3600
        self.now += timedelta(seconds=TICK_S)
        self._charge(dt_h)
        self._enter_or_no_show()
        self._leave_or_overstay()
        self._call_heads()

    def _charge(self, dt_h: float) -> None:
        total = 0.0
        for s in sorted(self.sessions.values(), key=lambda x: x.session_id):
            if s.status != "charging":
                continue
            rated = self._spec(s.charger_id).rated_kw
            p = demand_kw(s.vehicle.params, rated, s.soc)
            if self.mode == "controlled" and s.alloc_cap_kw is not None:
                p = min(p, s.alloc_cap_kw)
            s.p_kw = p
            total += p
            s.soc = min(100.0, s.soc + 100 * p * dt_h / s.vehicle.params.battery_kwh)
            if s.soc >= s.soc_target - 1e-9:
                s.soc = s.soc_target
                s.status = "done"
                s.actual_end = self.now
                s.p_kw = 0.0
                s.parked = s.leave_delay_min > 0
                s.leave_at = self.now + timedelta(minutes=s.leave_delay_min) if s.parked else None
                self._emit("done", s.session_id, charger_id=s.charger_id, parked=s.parked)
        self.totals.peak_kw = max(self.totals.peak_kw, total)
        if total > self.limit_kw + 1e-6:
            self.totals.over_limit_s += TICK_S
        if self.now >= self._next_log:
            self._log_load(total)

    def _enter_or_no_show(self) -> None:
        called = [s for s in self.sessions.values() if s.status == "called"]
        entries = [self._entry(s) for s in called]
        no_shows = set(find_no_shows(entries, self.now, NO_SHOW_GRACE_MIN))
        for s in sorted(called, key=lambda x: x.session_id):
            if s.enter_at is not None and self.now >= s.enter_at:
                self._enter(s)
            elif s.session_id in no_shows:
                self._no_show(s)

    def _leave_or_overstay(self) -> None:
        for s in sorted(self.sessions.values(), key=lambda x: x.session_id):
            if not s.parked or s.actual_end is None:
                continue
            if s.leave_at is not None and self.now >= s.leave_at:
                s.parked = False
                dwell = (self.now - s.actual_end).total_seconds() / 60
                self._emit("left", s.session_id, charger_id=s.charger_id, dwell_min=round(dwell, 1))
            elif not s.overstay_flagged and self.now - s.actual_end >= timedelta(
                minutes=OVERSTAY_MIN
            ):
                s.overstay_flagged = True
                self._emit("overstay", s.session_id, charger_id=s.charger_id)

    def _enter(self, s: SimSession) -> None:
        rated = self._spec(s.charger_id).rated_kw
        s.status = "charging"
        s.actual_start = self.now
        s.reserved_kw = 0.0
        demand = demand_kw(s.vehicle.params, rated, s.soc)
        s.p_kw = demand if s.alloc_cap_kw is None else min(demand, s.alloc_cap_kw)
        self._emit(
            "started",
            s.session_id,
            charger_id=s.charger_id,
            alloc_kw=s.alloc_cap_kw,
            limited=s.alloc_cap_kw is not None,
        )

    def _no_show(self, s: SimSession) -> None:
        s.no_show_count += 1
        s.reserved_kw = 0.0
        s.alloc_cap_kw = None
        s.notice = None
        if s.no_show_count >= MAX_NO_SHOWS:
            s.status = "no_show"
            s.actual_end = self.now
            self._emit("no_show", s.session_id, final=True)
            return
        demoted = demote_no_show(self._entry(s), self.now)
        s.status = "waiting"
        s.called_at = None
        s.enter_at = None
        s.registered_at = demoted.registered_at
        old = s.charger_id
        # give up the old slot first, then re-register at the back of the best queue
        infos = self._charger_infos()
        queues = {c.charger_id: self._queue(c.charger_id) for c in self.chargers}
        queues[old] = [e for e in queues[old] if e.session_id != s.session_id]
        new_id = assign_charger(self.now, demoted, infos, queues)
        s.charger_id = new_id if new_id is not None else old
        self._emit("no_show", s.session_id, final=False, from_charger=old, to_charger=s.charger_id)

    def _call_heads(self) -> None:
        """Call the head of every free charger's queue (or delay it under load control)."""
        free: list[tuple[SimSession, ChargerSpec]] = []
        for c in self.chargers:
            if (
                c.fault
                or self._on_charger(c.charger_id, "charging", "called")
                or self._parked_on(c.charger_id)
            ):
                continue
            queue = self._queue(c.charger_id)
            if queue:
                free.append((self.sessions[queue[0].session_id], c))
        free.sort(key=lambda x: (x[0].registered_at, x[0].session_id))
        for head, c in free:
            self._call(head, c)

    def _committed_kw(self) -> float:
        return sum(
            s.p_kw if s.status == "charging" else s.reserved_kw
            for s in self.sessions.values()
            if s.status in ("charging", "called")
        )

    def _running_loads(self) -> list[RunningLoad]:
        return [
            RunningLoad(s.soc, s.soc_target, s.vehicle.params, self._spec(s.charger_id).rated_kw)
            for s in self.sessions.values()
            if s.status in ("charging", "called")
        ]

    def _call(self, head: SimSession, charger: ChargerSpec) -> None:
        p_eff = p_eff_kw(head.vehicle.params, charger.rated_kw)
        if self.mode == "baseline":
            alloc, cap, reason = p_eff, None, ""
        else:
            d = decide_start(
                self.now, p_eff, self._committed_kw(), self.limit_kw, self._running_loads()
            )
            if d.action == "delay":
                if head.notice != d.reason:
                    self._emit("delayed", head.session_id, reason=d.reason)
                head.notice = d.reason
                head.resume_at = d.resume_at
                return
            alloc = d.alloc_kw
            cap = d.alloc_kw if d.action == "limit" else None
            reason = d.reason
        head.status = "called"
        head.called_at = self.now
        head.reserved_kw = alloc
        head.alloc_cap_kw = cap
        head.notice = reason or None
        head.resume_at = None
        delay = head.enter_delay_min
        head.enter_at = self.now + timedelta(minutes=delay) if delay < NO_SHOW_GRACE_MIN else None
        if cap is not None:
            self._emit("limited", head.session_id, alloc_kw=cap, reason=reason)
        self._emit("called", head.session_id, charger_id=charger.charger_id)

    # ---- views -----------------------------------------------------------------------

    def schedule(self) -> tuple[ChargerView, ...]:
        """Per charger: current block + one block per queued vehicle."""
        out: list[ChargerView] = []
        infos = {i.charger_id: i for i in self._charger_infos()}
        for c in self.chargers:
            info = infos[c.charger_id]
            queue = self._queue(c.charger_id)
            head = self.sessions[queue[0].session_id] if queue else None
            not_before = head.resume_at if head and head.status == "waiting" else None
            first_start = head.enter_at if head and head.status == "called" else None
            blocks = compute_blocks(
                self.now, info, queue, not_before=not_before, first_start=first_start
            )
            views: list[BlockView] = []
            for b in blocks:
                s = self.sessions[b.session_id]
                pos = None
                if b.kind == "waiting":
                    pos = [e.session_id for e in queue].index(b.session_id) + 1
                overstay = None
                if b.kind == "parked" and s.actual_end is not None:
                    overstay = max(0.0, (self.now - s.actual_end).total_seconds() / 60)
                views.append(
                    BlockView(
                        session_id=s.session_id,
                        kind=b.kind,
                        status=s.status,
                        start=b.start,
                        end=b.end,
                        queue_pos=pos,
                        model_name=s.vehicle.model_name,
                        soc_start=s.soc_start,
                        soc_target=s.soc_target,
                        soc_current=s.soc,
                        alloc_kw=s.alloc_cap_kw if s.status != "waiting" else None,
                        notice=s.notice,
                        overstay_min=overstay,
                        nudged=s.nudged_at is not None,
                    )
                )
            out.append(
                ChargerView(c.charger_id, c.rated_kw, c.connector_type, info.status, tuple(views))
            )
        return tuple(out)

    def find_block(self, session_id: int) -> tuple[ChargerView, BlockView] | None:
        for cv in self.schedule():
            for bv in cv.blocks:
                if bv.session_id == session_id:
                    return cv, bv
        return None

    def kpi(self) -> dict[str, float]:
        done = [s for s in self.sessions.values() if s.status == "done"]
        waits = [
            (s.actual_start - s.first_registered_at).total_seconds() / 60
            for s in self.sessions.values()
            if s.actual_start is not None
        ]
        mean_kw = sum(kw for _, kw in self.history) / len(self.history)
        peak = self.totals.peak_kw
        return {
            "sessions_done": float(len(done)),
            "avg_wait_min": sum(waits) / len(waits) if waits else 0.0,
            "load_factor": mean_kw / peak if peak > 0 else 0.0,  # PRD 5.3: mean load / peak load
            "peak_kw": self.totals.peak_kw,
            "over_limit_min": self.totals.over_limit_s / 60,
        }

    def is_idle(self) -> bool:
        return not any(s.status in ACTIVE or s.parked for s in self.sessions.values())
