from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.api import schemas
from app.api.runtime import StationRuntime
from app.sim.runner import find_scenario, load_scenario
from app.sim.world import NoChargerError

router = APIRouter()


def runtime(request: Request) -> StationRuntime:
    rt: StationRuntime | None = request.app.state.runtime
    if rt is None:
        rt = request.app.state.build_runtime()
    if rt is None:
        raise HTTPException(503, "충전소 데이터가 없습니다. 먼저 `make seed`를 실행하세요.")
    return rt


def station(rt: StationRuntime, station_id: int) -> StationRuntime:
    if station_id != rt.station_id:
        raise HTTPException(404, f"station {station_id} not found")
    return rt


@router.get("/vehicles", response_model=list[schemas.VehicleOut])
async def vehicles(request: Request) -> list[schemas.VehicleOut]:
    return runtime(request).vehicle_rows


@router.post("/estimate", response_model=schemas.EstimateOut)
async def estimate(body: schemas.EstimateIn, request: Request) -> schemas.EstimateOut:
    """Stateless preview for the input screen: nothing is registered."""
    rt = runtime(request)
    try:
        return rt.estimate(body)
    except KeyError:
        raise HTTPException(404, f"vehicle {body.vehicle_id} not found") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except NoChargerError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/sessions", response_model=schemas.SessionOut, status_code=201)
async def create_session(body: schemas.SessionCreate, request: Request) -> schemas.SessionOut:
    rt = runtime(request)
    try:
        session = rt.register(body)
    except KeyError:
        raise HTTPException(404, f"vehicle {body.vehicle_id} not found") from None
    except ValueError as e:  # PRD 3.6: invalid SoC -> validation message, no calculation
        raise HTTPException(422, str(e)) from None
    except NoChargerError as e:
        raise HTTPException(409, str(e)) from None
    await rt.notify("registered")
    return rt.session_out(session.session_id)


@router.get("/sessions/{session_id}", response_model=schemas.SessionOut)
async def get_session(session_id: int, request: Request) -> schemas.SessionOut:
    rt = runtime(request)
    if session_id not in rt.mgr.primary.sessions:
        raise HTTPException(404, f"session {session_id} not found")
    return rt.session_out(session_id)


@router.post("/sessions/{session_id}/cancel", response_model=schemas.SessionOut)
async def cancel_session(session_id: int, request: Request) -> schemas.SessionOut:
    rt = runtime(request)
    try:
        rt.mgr.cancel(session_id)
    except KeyError:
        raise HTTPException(404, f"session {session_id} not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    await rt.notify("cancelled")
    return rt.session_out(session_id)


@router.post("/sessions/{session_id}/nudge", response_model=schemas.SessionOut)
async def nudge_session(session_id: int, request: Request) -> schemas.SessionOut:
    """Operator reminder to a driver who left a finished car plugged in (A-05)."""
    rt = runtime(request)
    try:
        rt.mgr.nudge(session_id)
    except KeyError:
        raise HTTPException(404, f"session {session_id} not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    await rt.notify("nudged")
    return rt.session_out(session_id)


@router.get("/stations/{station_id}/schedule", response_model=schemas.ScheduleOut)
async def schedule(station_id: int, request: Request) -> schemas.ScheduleOut:
    return station(runtime(request), station_id).schedule()


@router.get("/stations/{station_id}/load", response_model=schemas.LoadOut)
async def load(station_id: int, request: Request) -> schemas.LoadOut:
    return station(runtime(request), station_id).load()


@router.get("/stations/{station_id}/kpi", response_model=schemas.KpiOut)
async def kpi(station_id: int, request: Request) -> schemas.KpiOut:
    return station(runtime(request), station_id).kpi()


@router.get("/stations/{station_id}/events", response_model=list[schemas.EventOut])
async def events(station_id: int, request: Request, limit: int = 60) -> list[schemas.EventOut]:
    return station(runtime(request), station_id).events(max(1, min(limit, 500)))


@router.get("/stations/{station_id}/kpi/history", response_model=list[schemas.KpiDayOut])
async def kpi_history(station_id: int, request: Request) -> list[schemas.KpiDayOut]:
    return station(runtime(request), station_id).kpi_history()


@router.get("/sim/state", response_model=schemas.SimState)
async def sim_state(request: Request) -> schemas.SimState:
    return runtime(request).state()


@router.post("/sim/start", response_model=schemas.SimState)
async def sim_start(body: schemas.SimStart, request: Request) -> schemas.SimState:
    rt = runtime(request)
    if body.scenario is not None:
        try:
            scenario = load_scenario(find_scenario(body.scenario))
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, f"scenario {body.scenario!r} not found") from None
        rt.reset(scenario)
    rt.mgr.speed = body.speed
    rt.mgr.running = body.autostart
    await rt.notify("sim_started" if body.autostart else "sim_loaded")
    return rt.state()


@router.post("/sim/pause", response_model=schemas.SimState)
async def sim_pause(request: Request) -> schemas.SimState:
    rt = runtime(request)
    rt.mgr.running = False
    await rt.notify("sim_paused")
    return rt.state()


@router.post("/sim/speed", response_model=schemas.SimState)
async def sim_speed(body: schemas.SimSpeed, request: Request) -> schemas.SimState:
    rt = runtime(request)
    rt.mgr.speed = body.speed
    await rt.notify("sim_speed")
    return rt.state()


@router.post("/sim/reset", response_model=schemas.SimState)
async def sim_reset(request: Request) -> schemas.SimState:
    rt = runtime(request)
    rt.reset()
    await rt.notify("sim_reset")
    return rt.state()


@router.websocket("/ws/stations/{station_id}")
async def ws_station(websocket: WebSocket, station_id: int) -> None:
    rt: StationRuntime | None = websocket.app.state.runtime
    if rt is None:
        rt = websocket.app.state.build_runtime()
    if rt is None or station_id != rt.station_id:
        await websocket.close(code=1008)
        return
    await rt.hub.connect(websocket)
    try:
        await websocket.send_json(rt.snapshot("connected"))
        while True:
            await websocket.receive_text()  # clients only listen; this detects disconnects
    except WebSocketDisconnect:
        pass
    finally:
        rt.hub.disconnect(websocket)
