"""Scenario runner and the two-world (baseline vs controlled) simulation manager.

Still free of DB and FastAPI: the API layer feeds it masters and reads results.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.engine.scheduler import TAU_MIN
from app.sim.world import TICK_S, ChargerSpec, Mode, SimSession, SimWorld, VehicleInfo

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "scenarios"
FIRST_SESSION_ID = 1001  # leaves the seeded demo sessions (ids 1..) alone
MAX_RUN_MIN = 24 * 60


@dataclass(frozen=True)
class Arrival:
    t_min: float
    vehicle: str  # vehicle_spec.model_name
    soc_start: float
    soc_target: float
    enter_delay_min: float = TAU_MIN


@dataclass(frozen=True)
class Scenario:
    name: str
    arrivals: tuple[Arrival, ...]
    contract_kw: float | None = None  # overrides the station contract for this run
    limit_ratio: float | None = None


def load_scenario(path: Path) -> Scenario:
    raw = json.loads(path.read_text(encoding="utf-8"))
    arrivals = tuple(
        Arrival(
            t_min=float(a["t_min"]),
            vehicle=str(a["vehicle"]),
            soc_start=float(a["soc_start"]),
            soc_target=float(a["soc_target"]),
            enter_delay_min=float(a.get("enter_delay_min", TAU_MIN)),
        )
        for a in raw["arrivals"]
    )
    return Scenario(
        name=str(raw.get("name", path.stem)),
        arrivals=tuple(sorted(arrivals, key=lambda a: a.t_min)),
        contract_kw=raw.get("contract_kw"),
        limit_ratio=raw.get("limit_ratio"),
    )


def find_scenario(name: str) -> Path:
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid scenario name: {name!r}")
    path = SCENARIO_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


class SimManager:
    """Runs baseline and controlled worlds in lock-step on the same arrivals."""

    def __init__(
        self,
        chargers: Sequence[ChargerSpec],
        vehicles_by_name: Mapping[str, VehicleInfo],
        contract_kw: float,
        limit_ratio: float,
        t0: datetime,
    ) -> None:
        self.chargers = tuple(chargers)
        self.vehicles_by_name = dict(vehicles_by_name)
        self.vehicles_by_id = {v.vehicle_id: v for v in vehicles_by_name.values()}
        self.default_contract_kw = contract_kw
        self.default_limit_ratio = limit_ratio
        self.running = False
        self.speed = 1
        self.scenario: Scenario | None = None
        self.reset(t0)

    def reset(
        self, t0: datetime, scenario: Scenario | None = None
    ) -> None:
        self.scenario = scenario
        self.running = False
        self.contract_kw = (
            scenario.contract_kw if scenario and scenario.contract_kw else self.default_contract_kw
        )
        self.limit_ratio = (
            scenario.limit_ratio if scenario and scenario.limit_ratio else self.default_limit_ratio
        )
        self.worlds: dict[Mode, SimWorld] = {
            m: SimWorld(self.chargers, self.contract_kw, self.limit_ratio, t0, m)
            for m in ("controlled", "baseline")
        }
        self._pending = list(scenario.arrivals) if scenario else []
        self._elapsed_s = 0.0
        self._carry_s = 0.0
        self._next_id = FIRST_SESSION_ID

    @property
    def elapsed_s(self) -> float:
        return self._elapsed_s

    @property
    def primary(self) -> SimWorld:
        return self.worlds["controlled"]

    def register(
        self,
        vehicle_id: int,
        anon_user_id: str | None,
        soc_start: float,
        soc_target: float,
        enter_delay_min: float = TAU_MIN,
        charger_id: int | None = None,
    ) -> SimSession:
        """Register in both worlds under the same session id; returns the controlled one."""
        vehicle = self.vehicles_by_id.get(vehicle_id)
        if vehicle is None:
            raise KeyError(vehicle_id)
        sid = self._next_id
        anon = anon_user_id or f"sim-anon-{sid}"
        # validate on the primary first so a rejected request leaves nothing behind
        session = self.worlds["controlled"].register(
            sid, vehicle, anon, soc_start, soc_target, enter_delay_min, charger_id
        )
        self.worlds["baseline"].register(
            sid, vehicle, anon, soc_start, soc_target, enter_delay_min, charger_id
        )
        self._next_id += 1
        return session

    def cancel(self, session_id: int) -> SimSession:
        session = self.worlds["controlled"].cancel(session_id)
        baseline = self.worlds["baseline"].sessions.get(session_id)
        if baseline is not None and baseline.status in ("waiting", "called", "charging"):
            self.worlds["baseline"].cancel(session_id)
        return session

    def _inject_due(self) -> None:
        while self._pending and self._pending[0].t_min * 60 <= self._elapsed_s + 1e-9:
            a = self._pending.pop(0)
            vehicle = self.vehicles_by_name[a.vehicle]
            self.register(vehicle.vehicle_id, None, a.soc_start, a.soc_target, a.enter_delay_min)

    def advance(self, seconds: float) -> None:
        """Advance both worlds; arrivals are injected at their scenario time."""
        total = self._carry_s + seconds
        while total >= TICK_S - 1e-9:
            self._inject_due()
            for w in self.worlds.values():
                w.step()
            self._elapsed_s += TICK_S
            total -= TICK_S
        self._carry_s = max(total, 0.0)

    def finished(self) -> bool:
        return not self._pending and all(w.is_idle() for w in self.worlds.values())


def run_scenario(
    scenario: Scenario,
    chargers: Sequence[ChargerSpec],
    vehicles_by_name: Mapping[str, VehicleInfo],
    contract_kw: float,
    limit_ratio: float,
    t0: datetime,
    speed: int = 1,
) -> SimManager:
    """Run a scenario to completion, in the same chunks the live ticker uses at `speed`."""
    mgr = SimManager(chargers, vehicles_by_name, contract_kw, limit_ratio, t0)
    mgr.reset(t0, scenario)
    chunk = speed * 0.5  # one live ticker iteration is 0.5 s of real time
    while not mgr.finished() and mgr.elapsed_s < MAX_RUN_MIN * 60:
        mgr.advance(chunk)
    return mgr
