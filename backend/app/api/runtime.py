"""Glue between the simulation, the database and the websocket clients.

The simulation is the live source of truth; the DB is a mirror (charge_session,
session_event, load_log) so the PRD data model stays meaningful. Simulation state is not
restored after a restart: simulation rows are cleared at startup and on /sim/reset.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import WebSocket
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api import schemas
from app.engine.charge_time import ChargeTimeResult, VehicleParams, calc_for
from app.engine.scheduler import NO_SHOW_GRACE_MIN
from app.models import (
    Charger,
    ChargeSession,
    KpiDaily,
    LoadLog,
    SessionEvent,
    Station,
    VehicleSpec,
)
from app.sim.runner import FIRST_SESSION_ID, Scenario, SimManager
from app.sim.world import BlockView, ChargerSpec, ChargerView, SimSession, VehicleInfo

SessionFactory = Callable[[], Session]
TICK_REAL_S = 0.5  # real seconds between ticker iterations (sim advances speed x this)
MAX_SERIES = 1440
MAX_EVENTS = 60  # event log rows pushed with every snapshot


class Hub:
    """Connected websocket clients of one station."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - client went away mid-send
                self._clients.discard(ws)


class StationRuntime:
    def __init__(self, factory: SessionFactory, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.factory = factory
        self.clock = now
        self.hub = Hub()
        with factory() as db:
            station = db.scalars(select(Station).order_by(Station.station_id)).first()
            if station is None:
                raise LookupError("no station in the database")
            self.station_id = station.station_id
            chargers = db.scalars(
                select(Charger).where(Charger.station_id == self.station_id).order_by(Charger.charger_id)
            ).all()
            vehicles = db.scalars(select(VehicleSpec).order_by(VehicleSpec.vehicle_id)).all()
            self.vehicle_rows = [
                schemas.VehicleOut(
                    vehicle_id=v.vehicle_id,
                    model_name=v.model_name,
                    battery_kwh=v.battery_kwh,
                    max_dc_kw=v.max_dc_kw,
                )
                for v in vehicles
            ]
            vehicle_infos = {
                v.model_name: VehicleInfo(
                    v.vehicle_id,
                    v.model_name,
                    VehicleParams(
                        v.battery_kwh, v.max_dc_kw, v.efficiency, v.taper_start_soc, v.taper_min_ratio
                    ),
                )
                for v in vehicles
            }
            specs = [
                ChargerSpec(c.charger_id, c.rated_kw, c.connector_type, c.status == "fault")
                for c in chargers
            ]
            self.station_name = station.name
            self.mgr = SimManager(
                specs, vehicle_infos, station.contract_kw, station.limit_ratio, self.clock()
            )
        self.scenario_name: str | None = None
        self._persisted: dict[int, tuple[object, ...]] = {}
        self._event_cursor = 0
        self._log_cursor = {"controlled": 0, "baseline": 0}
        self.clear_db()

    # ---- simulation control ---------------------------------------------------------

    def reset(self, scenario: Scenario | None = None) -> None:
        self.mgr.reset(self.clock(), scenario)
        self.scenario_name = scenario.name if scenario else None
        self.clear_db()
        self.flush()

    def state(self) -> schemas.SimState:
        w = self.mgr.primary
        return schemas.SimState(
            running=self.mgr.running,
            speed=self.mgr.speed,
            scenario=self.scenario_name,
            now=w.now,
            elapsed_min=self.mgr.elapsed_s / 60,
        )

    def register(self, body: schemas.SessionCreate) -> SimSession:
        return self.mgr.register(
            body.vehicle_id,
            body.anon_user_id,
            body.soc_start,
            body.soc_target,
            body.enter_delay_min,
            body.charger_id,
            body.leave_delay_min,
        )

    def estimate(self, body: schemas.EstimateIn) -> schemas.EstimateOut:
        vehicle = self.mgr.vehicles_by_id.get(body.vehicle_id)
        if vehicle is None:
            raise KeyError(body.vehicle_id)
        charger_id, start = self.mgr.primary.preview(
            vehicle, body.soc_start, body.soc_target, body.charger_id
        )
        rated = next(c.rated_kw for c in self.mgr.chargers if c.charger_id == charger_id)
        r = calc_for(vehicle.params, body.soc_start, body.soc_target, rated)
        return schemas.EstimateOut(
            charger_id=charger_id,
            calc=self._calc_out(r, rated),
            expected_start=start,
            expected_end=start + timedelta(minutes=r.total_min),
        )

    # ---- views ----------------------------------------------------------------------

    @staticmethod
    def _calc_out(r: ChargeTimeResult, charger_kw: float) -> schemas.CalcOut:
        return schemas.CalcOut(
            total_min=r.total_min,
            low_min=r.low_min,
            high_min=r.high_min,
            t1_min=r.t1_min,
            t2_min=r.t2_min,
            p_eff_kw=r.p_eff_kw,
            charger_kw=charger_kw,
            segments=[
                schemas.SegmentOut(
                    name=g.name, soc_from=g.soc_from, soc_to=g.soc_to, minutes=g.minutes
                )
                for g in r.segments
            ],
        )

    def _calc(self, s: SimSession) -> schemas.CalcOut:
        charger_kw = next(c.rated_kw for c in self.mgr.chargers if c.charger_id == s.charger_id)
        r = calc_for(s.vehicle.params, s.soc_start, s.soc_target, charger_kw)
        return self._calc_out(r, charger_kw)

    def session_out(self, session_id: int) -> schemas.SessionOut:
        w = self.mgr.primary
        s = w.sessions[session_id]
        found = w.find_block(session_id)
        queue_pos: int | None = None
        ahead = 0
        planned_start = planned_end = None
        lane: list[schemas.LaneBlock] = []
        if found is not None:
            cv, bv = found
            queue_pos = bv.queue_pos
            ids = [b.session_id for b in cv.blocks]
            ahead = ids.index(session_id)
            planned_start, planned_end = bv.start, bv.end
            lane = [
                schemas.LaneBlock(
                    session_id=b.session_id,
                    kind=b.kind,
                    status=b.status,
                    start=b.start,
                    end=b.end,
                    is_me=b.session_id == session_id,
                )
                for b in cv.blocks[: ahead + 1]
            ]
        no_show_at = (
            s.called_at + timedelta(minutes=NO_SHOW_GRACE_MIN)
            if s.status == "called" and s.called_at
            else None
        )
        return schemas.SessionOut(
            session_id=s.session_id,
            status=s.status,
            charger_id=s.charger_id,
            vehicle_id=s.vehicle.vehicle_id,
            model_name=s.vehicle.model_name,
            soc_start=s.soc_start,
            soc_target=s.soc_target,
            soc_current=s.soc,
            battery_kwh=s.vehicle.params.battery_kwh,
            charged_kwh=s.vehicle.params.battery_kwh * (s.soc - s.soc_start) / 100,
            current_kw=s.p_kw,
            queue_pos=queue_pos,
            ahead=ahead,
            planned_start=planned_start,
            planned_end=planned_end,
            alloc_kw=s.alloc_cap_kw,
            notice=s.notice,
            resume_at=s.resume_at,
            called_at=s.called_at if s.status == "called" else None,
            no_show_at=no_show_at,
            no_show_count=s.no_show_count,
            actual_start=s.actual_start,
            actual_end=s.actual_end,
            parked=s.parked,
            leave_at=s.leave_at if s.parked else None,
            nudged_at=s.nudged_at,
            lane=lane,
            calc=self._calc(s),
        )

    @staticmethod
    def _block_out(b: BlockView) -> schemas.BlockOut:
        return schemas.BlockOut(**b.__dict__)

    def schedule(self) -> schemas.ScheduleOut:
        w = self.mgr.primary
        chargers: list[schemas.ChargerOut] = []
        for cv in w.schedule():
            waiting = sum(1 for b in cv.blocks if b.kind == "waiting")
            chargers.append(
                schemas.ChargerOut(
                    charger_id=cv.charger_id,
                    rated_kw=cv.rated_kw,
                    connector_type=cv.connector_type,
                    status=cv.status,
                    queue_total=waiting,
                    free_at=cv.blocks[-1].end if cv.blocks else w.now,
                    blocks=[self._block_out(b) for b in _first_blocks(cv)],
                )
            )
        return schemas.ScheduleOut(
            station_id=self.station_id,
            station_name=self.station_name,
            now=w.now,
            running=self.mgr.running,
            speed=self.mgr.speed,
            contract_kw=self.mgr.contract_kw,
            limit_kw=w.limit_kw,
            chargers=chargers,
        )

    def load(self) -> schemas.LoadOut:
        c, b = self.mgr.worlds["controlled"], self.mgr.worlds["baseline"]
        return schemas.LoadOut(
            station_id=self.station_id,
            now=c.now,
            contract_kw=self.mgr.contract_kw,
            limit_kw=c.limit_kw,
            now_kw=c.site_kw,
            baseline_now_kw=b.site_kw,
            controlled=[schemas.LoadPoint(ts=t, kw=kw) for t, kw in c.history[-MAX_SERIES:]],
            baseline=[schemas.LoadPoint(ts=t, kw=kw) for t, kw in b.history[-MAX_SERIES:]],
        )

    def kpi(self) -> schemas.KpiOut:
        c, b = self.mgr.worlds["controlled"].kpi(), self.mgr.worlds["baseline"].kpi()
        return schemas.KpiOut(
            station_id=self.station_id,
            sessions_done=int(c["sessions_done"]),
            avg_wait_min=c["avg_wait_min"],
            load_factor=c["load_factor"],
            peak_kw=c["peak_kw"],
            baseline_peak_kw=b["peak_kw"],
            peak_reduction_kw=max(0.0, b["peak_kw"] - c["peak_kw"]),
            over_limit_min=c["over_limit_min"],
            baseline_over_limit_min=b["over_limit_min"],
        )

    def events(self, limit: int = MAX_EVENTS) -> list[schemas.EventOut]:
        """Newest first. Events come from the controlled world, the one operators act on."""
        w = self.mgr.primary
        out: list[schemas.EventOut] = []
        for e in reversed(w.events[-limit:]):
            s = w.sessions.get(e.session_id) if e.session_id is not None else None
            out.append(
                schemas.EventOut(
                    seq=e.seq,
                    ts=e.ts,
                    type=e.type,
                    session_id=e.session_id,
                    model_name=s.vehicle.model_name if s else None,
                    payload=e.payload,
                )
            )
        return out

    def kpi_history(self, days: int = 14) -> list[schemas.KpiDayOut]:
        """Previous days for the KPI cards (demo example values, see seed.py)."""
        with self.factory() as db:
            rows = db.scalars(
                select(KpiDaily)
                .where(KpiDaily.station_id == self.station_id)
                .order_by(KpiDaily.date.desc())
                .limit(days)
            ).all()
        return [
            schemas.KpiDayOut(
                date=r.date,
                sessions=r.sessions,
                avg_wait_min=r.avg_wait_min,
                load_factor=r.load_factor,
                peak_reduction_kw=r.peak_reduction_kw,
            )
            for r in reversed(rows)
        ]

    def snapshot(self, reason: str) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "reason": reason,
            "sim": self.state().model_dump(mode="json"),
            "schedule": self.schedule().model_dump(mode="json"),
            "load": self.load().model_dump(mode="json"),
            "kpi": self.kpi().model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in self.events(MAX_EVENTS)],
        }

    # ---- push + persistence -----------------------------------------------------------

    async def notify(self, reason: str) -> None:
        """Mirror to the DB and push fresh data to every websocket client."""
        self.flush()
        await self.hub.broadcast(self.snapshot(reason))

    async def run_ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK_REAL_S)
            if self.mgr.running:
                before = len(self.mgr.primary.events)
                self.mgr.advance(self.mgr.speed * TICK_REAL_S)
                changed = len(self.mgr.primary.events) > before
                await self.notify("events" if changed else "tick")

    def clear_db(self) -> None:
        with self.factory() as db:
            ids = select(ChargeSession.session_id).where(ChargeSession.session_id >= FIRST_SESSION_ID)
            db.execute(delete(SessionEvent).where(SessionEvent.session_id.in_(ids)))
            db.execute(delete(ChargeSession).where(ChargeSession.session_id >= FIRST_SESSION_ID))
            db.execute(delete(LoadLog).where(LoadLog.station_id == self.station_id))
            db.commit()
        self._persisted.clear()
        self._event_cursor = 0
        self._log_cursor = {"controlled": 0, "baseline": 0}

    def flush(self) -> None:
        w = self.mgr.primary
        views = w.schedule()
        planned = {b.session_id: b for cv in views for b in cv.blocks}
        with self.factory() as db:
            for s in w.sessions.values():
                b = planned.get(s.session_id)
                row = (
                    s.status,
                    s.charger_id,
                    round(s.soc, 1),
                    b.queue_pos if b else None,
                    b.start if b else None,
                    b.end if b else None,
                    s.actual_start,
                    s.actual_end,
                    s.alloc_cap_kw,
                )
                if self._persisted.get(s.session_id) == row:
                    continue
                self._persisted[s.session_id] = row
                calc = self._calc(s)
                db.merge(
                    ChargeSession(
                        session_id=s.session_id,
                        charger_id=s.charger_id,
                        vehicle_id=s.vehicle.vehicle_id,
                        anon_user_id=s.anon_user_id,
                        soc_start=s.soc_start,
                        soc_target=s.soc_target,
                        soc_current=round(s.soc, 1),
                        status=s.status,
                        queue_pos=b.queue_pos if b else None,
                        registered_at=s.registered_at,
                        planned_start=b.start if b else None,
                        planned_end=b.end if b else None,
                        actual_start=s.actual_start,
                        actual_end=s.actual_end,
                        alloc_kw=s.alloc_cap_kw,
                        calc_minutes=calc.total_min,
                        calc_detail=calc.model_dump(mode="json"),
                    )
                )
            db.flush()
            for e in w.events[self._event_cursor :]:
                if e.session_id is not None:
                    db.add(
                        SessionEvent(
                            session_id=e.session_id, type=e.type, payload=e.payload, created_at=e.ts
                        )
                    )
            self._event_cursor = len(w.events)
            for mode, world in self.mgr.worlds.items():
                for ts, kw in world.history[self._log_cursor[mode] :]:
                    db.add(
                        LoadLog(
                            station_id=self.station_id,
                            ts=ts,
                            total_kw=kw,
                            contract_kw=self.mgr.contract_kw,
                            mode=mode,
                        )
                    )
                self._log_cursor[mode] = len(world.history)
            for cv in views:
                charger = db.get(Charger, cv.charger_id)
                # PRD 6 allows idle/charging/fault only: a parked car still occupies the connector
                db_status = "charging" if cv.status == "occupied" else cv.status
                if charger is not None and charger.status != db_status:
                    charger.status = db_status
            db.commit()


def _first_blocks(cv: ChargerView) -> list[BlockView]:
    """Current block + the first two waiting blocks (A-01 gantt)."""
    out: list[BlockView] = []
    waiting = 0
    for b in cv.blocks:
        if b.kind == "waiting":
            waiting += 1
            if waiting > 2:
                break
        out.append(b)
    return out
