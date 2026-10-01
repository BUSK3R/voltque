from datetime import UTC, datetime, timedelta

import pytest

from app.engine.charge_time import VehicleParams, calc_for
from app.engine.scheduler import (
    Block,
    ChargerInfo,
    QueueEntry,
    assign_charger,
    compute_blocks,
    demote_no_show,
    expected_start,
    find_no_shows,
    order_queue,
    priority_score,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CAR = VehicleParams(battery_kwh=77.4, max_kw=220)
SMALL = VehicleParams(battery_kwh=35.2, max_kw=70, taper_min_ratio=0.3)


def mins(m: float) -> datetime:
    return NOW + timedelta(minutes=m)


def entry(
    sid: int,
    registered_min: float = 0,
    vehicle: VehicleParams = CAR,
    s0: float = 20,
    s1: float = 90,
    **kw: object,
) -> QueueEntry:
    return QueueEntry(
        session_id=sid,
        registered_at=mins(registered_min),
        vehicle=vehicle,
        soc_start=s0,
        soc_target=s1,
        **kw,  # type: ignore[arg-type]
    )


def charger(cid: int, kw: float, current: Block | None = None, **kw_: object) -> ChargerInfo:
    return ChargerInfo(
        charger_id=cid,
        rated_kw=kw,
        connector_type=str(kw_.get("connector_type", "DC_COMBO")),
        status=str(kw_.get("status", "charging" if current else "idle")),
        current=current,
    )


# --- priority -----------------------------------------------------------------------


def test_score_formula_for_short_charge() -> None:
    # wait 10 + 0.5 * (30 - 20)
    assert priority_score(10, 20, target_soc=80) == pytest.approx(15)
    assert priority_score(10, 45, target_soc=80) == pytest.approx(10)  # no bonus past 30 min


def test_score_has_no_bonus_for_target_above_80() -> None:
    assert priority_score(10, 20, target_soc=90) == pytest.approx(10)


def test_fifo_is_default_order() -> None:
    q = [entry(2, 5), entry(1, 0), entry(3, 9)]
    assert [e.session_id for e in order_queue(q, mins(10), 100)] == [1, 2, 3]


def test_short_charge_jumps_ahead_of_fresh_long_charge() -> None:
    long_ = entry(1, 0)  # 20->90 takes ~37 min on 100 kW
    short = entry(2, 1, SMALL, 60, 80)  # tiny top-up, T well under 30 min
    ordered = order_queue([long_, short], mins(2), 100)
    assert [e.session_id for e in ordered] == [2, 1]


def test_aged_waiter_is_protected_from_short_charge_priority() -> None:
    aged = entry(1, 0)  # waited 31 min at now
    short = entry(2, 25, SMALL, 60, 80)
    ordered = order_queue([short, aged], mins(31), 100)
    assert [e.session_id for e in ordered] == [1, 2]


def test_called_entry_is_locked_in_front() -> None:
    called = entry(1, 8, called_at=mins(9))
    short = entry(2, 0, SMALL, 60, 80)
    ordered = order_queue([short, called], mins(10), 100)
    assert ordered[0].session_id == 1


# --- time blocks --------------------------------------------------------------------


def test_blocks_follow_prd_formula() -> None:
    cur = Block(100, "charging", mins(-10), mins(20))
    ch = charger(1, 100, cur)
    q = [entry(1), entry(2, 1)]
    blocks = compute_blocks(mins(5), ch, q, tau_min=3)
    t = calc_for(CAR, 20, 90, 100).total_min
    assert blocks[0] == cur
    assert blocks[1].start == mins(20 + 3)  # S_q1 = max(now, E_cur) + tau
    assert blocks[1].end == mins(23 + t)  # E = S + T
    assert blocks[2].start == blocks[1].end + timedelta(minutes=3)  # S_next = E + tau


def test_blocks_on_idle_charger_start_now_plus_tau() -> None:
    blocks = compute_blocks(NOW, charger(1, 100), [entry(1)], tau_min=3)
    assert blocks[0].start == mins(3)
    assert blocks[0].kind == "waiting"


def test_current_block_overrun_uses_now() -> None:
    cur = Block(100, "charging", mins(-30), mins(-1))  # expected end already passed
    blocks = compute_blocks(NOW, charger(1, 100, cur), [entry(1)], tau_min=3)
    assert blocks[1].start == mins(3)


def test_blocks_pull_forward_when_current_ends_early() -> None:
    ch_late = charger(1, 100, Block(100, "charging", mins(0), mins(30)))
    ch_early = charger(1, 100, Block(100, "charging", mins(0), mins(20)))
    late = compute_blocks(NOW, ch_late, [entry(1), entry(2)], 3)
    early = compute_blocks(NOW, ch_early, [entry(1), entry(2)], 3)
    for a, b in zip(late[1:], early[1:], strict=True):
        assert b.start == a.start - timedelta(minutes=10)


def test_blocks_respect_not_before_and_first_start() -> None:
    ch = charger(1, 100)
    delayed = compute_blocks(NOW, ch, [entry(1), entry(2)], 3, not_before=mins(40))
    assert delayed[0].start == mins(40)
    assert delayed[1].start == delayed[0].end + timedelta(minutes=3)
    fixed = compute_blocks(NOW, ch, [entry(1)], 3, first_start=mins(2))
    assert fixed[0].start == mins(2)


# --- charger assignment --------------------------------------------------------------


def test_assign_picks_earliest_expected_start() -> None:
    busy = charger(1, 350, Block(100, "charging", mins(0), mins(40)))
    free = charger(2, 50)
    assert assign_charger(NOW, entry(9), [busy, free], {1: [], 2: []}) == 2


def test_assign_counts_existing_queue() -> None:
    a = charger(1, 100, Block(100, "charging", mins(0), mins(10)))
    b = charger(2, 100, Block(101, "charging", mins(0), mins(10)))
    queues = {1: [entry(1), entry(2)], 2: []}
    assert assign_charger(NOW, entry(9), [a, b], queues) == 2


def test_tie_sends_large_charge_to_high_power_charger() -> None:
    chargers = [charger(1, 50), charger(2, 100), charger(3, 350)]
    queues: dict[int, list[QueueEntry]] = {1: [], 2: [], 3: []}
    big = entry(9)  # 20->90% of 77.4 kWh = 54 kWh
    assert assign_charger(NOW, big, chargers, queues) == 3


def test_tie_keeps_high_power_free_for_small_charge() -> None:
    chargers = [charger(1, 50), charger(2, 100), charger(3, 350)]
    queues: dict[int, list[QueueEntry]] = {1: [], 2: [], 3: []}
    small = entry(9, vehicle=SMALL, s0=60, s1=80)  # ~7 kWh
    assert assign_charger(NOW, small, chargers, queues) == 1


def test_assign_skips_fault_and_incompatible() -> None:
    chargers = [
        charger(1, 350, status="fault"),
        charger(2, 100, connector_type="AC3"),
        charger(3, 50),
    ]
    queues: dict[int, list[QueueEntry]] = {1: [], 2: [], 3: []}
    e = entry(9, connector_type="DC_COMBO")
    assert assign_charger(NOW, e, chargers, queues) == 3
    assert assign_charger(NOW, e, chargers[:2], queues) is None


def test_expected_start_for_empty_idle_charger() -> None:
    assert expected_start(NOW, charger(1, 100), [], 3) == mins(3)


# --- no-show ------------------------------------------------------------------------


def test_no_show_detected_after_five_minutes() -> None:
    e = entry(1, called_at=mins(0))
    assert find_no_shows([e], mins(4.9)) == []
    assert find_no_shows([e], mins(5)) == [1]


def test_uncalled_entries_are_never_no_show() -> None:
    assert find_no_shows([entry(1)], mins(60)) == []


def test_demote_requeues_at_the_back() -> None:
    e = demote_no_show(entry(1, 0, called_at=mins(0)), mins(5))
    assert e.called_at is None
    assert e.registered_at == mins(5)
    ordered = order_queue([e, entry(2, 3)], mins(6), 100)
    assert [x.session_id for x in ordered] == [2, 1]
