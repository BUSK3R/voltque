"""Queue priority, charger assignment and timeline blocks (PRD 3.4). Pure functions.

No DB, FastAPI or clock access: `now` is always an argument.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from app.engine.charge_time import VehicleParams, calc_for

TAU_MIN = 3.0  # vehicle changeover buffer
NO_SHOW_GRACE_MIN = 5.0
AGING_MIN = 30.0  # waiters beyond this are protected from short-charge priority
BETA = 0.5
SHORT_TARGET_SOC = 80.0
SHORT_T_MIN = 30.0
LARGE_ENERGY_KWH = 40.0  # "needs a large charge" threshold for the tie-break


@dataclass(frozen=True)
class QueueEntry:
    session_id: int
    registered_at: datetime
    vehicle: VehicleParams
    soc_start: float
    soc_target: float
    called_at: datetime | None = None
    connector_type: str | None = None  # None = compatible with every charger


@dataclass(frozen=True)
class Block:
    session_id: int
    kind: Literal["charging", "waiting"]
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ChargerInfo:
    charger_id: int
    rated_kw: float
    connector_type: str
    status: str  # idle | charging | fault
    current: Block | None = None  # in-progress session; its end is E_cur


def duration_min(entry: QueueEntry, charger_kw: float) -> float:
    return calc_for(entry.vehicle, entry.soc_start, entry.soc_target, charger_kw).total_min


def wait_minutes(entry: QueueEntry, now: datetime) -> float:
    return max(0.0, (now - entry.registered_at).total_seconds() / 60)


def priority_score(
    wait_min: float, t_min: float, target_soc: float, beta: float = BETA
) -> float:
    """score = wait + beta * max(0, 30 - T); the bonus applies to targets <= 80% only."""
    bonus = beta * max(0.0, SHORT_T_MIN - t_min) if target_soc <= SHORT_TARGET_SOC else 0.0
    return wait_min + bonus


def order_queue(entries: Sequence[QueueEntry], now: datetime, charger_kw: float) -> list[QueueEntry]:
    """Called entries first (locked), then aged waiters FIFO, then everyone else by score."""
    called = sorted(
        (e for e in entries if e.called_at is not None),
        key=lambda e: (e.called_at or now, e.session_id),
    )
    rest = [e for e in entries if e.called_at is None]
    aged = sorted(
        (e for e in rest if wait_minutes(e, now) > AGING_MIN),
        key=lambda e: (e.registered_at, e.session_id),
    )
    normal = sorted(
        (e for e in rest if wait_minutes(e, now) <= AGING_MIN),
        key=lambda e: (
            -priority_score(
                wait_minutes(e, now), duration_min(e, charger_kw), e.soc_target
            ),
            e.registered_at,
            e.session_id,
        ),
    )
    return [*called, *aged, *normal]


def compute_blocks(
    now: datetime,
    charger: ChargerInfo,
    queue: Sequence[QueueEntry],
    tau_min: float = TAU_MIN,
    not_before: datetime | None = None,
    first_start: datetime | None = None,
) -> tuple[Block, ...]:
    """Current block + one waiting block per queued entry (queue must already be ordered).

    S_q1 = max(now, E_cur) + tau, E = S + T, S_next = E + tau.
    `not_before` postpones the first waiting block (load-control delay);
    `first_start` pins it (a called vehicle whose arrival time is known).
    """
    tau = timedelta(minutes=tau_min)
    blocks: list[Block] = []
    base = now
    if charger.current is not None:
        blocks.append(charger.current)
        base = max(now, charger.current.end)
    for i, e in enumerate(queue):
        start = base + tau
        if i == 0:
            if not_before is not None:
                start = max(start, not_before)
            if first_start is not None:
                start = first_start
        end = start + timedelta(minutes=duration_min(e, charger.rated_kw))
        blocks.append(Block(e.session_id, "waiting", start, end))
        base = end
    return tuple(blocks)


def expected_start(
    now: datetime,
    charger: ChargerInfo,
    queue: Sequence[QueueEntry],
    tau_min: float = TAU_MIN,
    not_before: datetime | None = None,
) -> datetime:
    """Start time a newcomer appended to this charger's queue would get."""
    blocks = compute_blocks(now, charger, queue, tau_min, not_before)
    base = max(now, blocks[-1].end) if blocks else now
    return base + timedelta(minutes=tau_min)


def _compatible(entry: QueueEntry, charger: ChargerInfo) -> bool:
    return entry.connector_type is None or entry.connector_type == charger.connector_type


def assign_charger(
    now: datetime,
    entry: QueueEntry,
    chargers: Sequence[ChargerInfo],
    queues: Mapping[int, Sequence[QueueEntry]],
    tau_min: float = TAU_MIN,
) -> int | None:
    """Compatible, non-faulty charger with the earliest expected start.

    Ties: a large charge goes to the higher-power charger, a small one to the lower.
    """
    energy_kwh = entry.vehicle.battery_kwh * (entry.soc_target - entry.soc_start) / 100
    large = energy_kwh >= LARGE_ENERGY_KWH
    best: tuple[datetime, float, int] | None = None
    for ch in chargers:
        if ch.status == "fault" or not _compatible(entry, ch):
            continue
        queue = order_queue(queues.get(ch.charger_id, ()), now, ch.rated_kw)
        start = expected_start(now, ch, queue, tau_min)
        key = (start, -ch.rated_kw if large else ch.rated_kw, ch.charger_id)
        if best is None or key < best:
            best = key
    return None if best is None else best[2]


def find_no_shows(
    entries: Sequence[QueueEntry], now: datetime, grace_min: float = NO_SHOW_GRACE_MIN
) -> list[int]:
    """Called entries that did not enter within the grace period."""
    limit = timedelta(minutes=grace_min)
    return [
        e.session_id
        for e in entries
        if e.called_at is not None and now - e.called_at >= limit
    ]


def demote_no_show(entry: QueueEntry, now: datetime) -> QueueEntry:
    """Re-register at the back of the line."""
    return replace(entry, called_at=None, registered_at=now)
