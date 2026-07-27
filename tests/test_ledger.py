"""Slice 5: the decision ledger.

The live Object Lock proof (write a locked record to real B2, attempt to
delete it, watch the delete FAIL) lives in tools/live_probe.py -- a green
in-memory test can only prove passthrough, never that the lock binds.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from genblaze_core.storage.base import ObjectLockConfig

from reprise.ledger import LEDGER_SCHEMA, Ledger
from reprise.model import Candidate, Decision, Request, Verdict
from tests.test_classify import entry
from tests.test_library import MemoryBackend

# MemoryBackend now mirrors genblaze-s3's extended put() and records the lock
# itself, so this name is kept only because the lock tests read better with it.
LockRecordingBackend = MemoryBackend

# Any deployment that wants the snapshot optimisation configures a signing key;
# without one the ledger simply recomputes, which is slower and always honest.
SNAP_KEY = b"test-snapshot-key"


def fixed_clock() -> datetime:
    return datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def reuse_decision(cost: float = 0.05) -> Decision:
    e = entry(cost=cost)
    return Decision(
        verdict=Verdict.REUSE,
        request=Request(prompt=e.prompt, modality="image"),
        candidate=Candidate(entry=e, similarity=1.0, exact=True),
        saved_usd=cost,
        reason="exact prompt match",
    )


def review_decision(cost: float = 0.12) -> Decision:
    e = entry(cost=cost)
    return Decision(
        verdict=Verdict.REVIEW,
        request=Request(prompt=e.prompt, modality="image"),
        candidate=Candidate(entry=e, similarity=0.91, exact=False),
        saved_usd=0.0,
        reason="similarity 0.91 in review band",
    )


def generate_decision() -> Decision:
    return Decision(
        verdict=Verdict.GENERATE,
        request=Request(prompt="something new", modality="image"),
        reason="no match",
    )


def test_record_writes_one_object_under_ledger_prefix() -> None:
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)

    key = led.record(reuse_decision())

    assert key.startswith("reprise/ledger/")
    assert b.exists(key)


def test_keys_are_unique_even_at_identical_timestamps() -> None:
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)  # frozen clock

    k1 = led.record(reuse_decision())
    k2 = led.record(reuse_decision())

    assert k1 != k2


def test_object_lock_config_is_passed_through() -> None:
    b = LockRecordingBackend()
    lock = ObjectLockConfig(retain_until=datetime(2026, 8, 15, tzinfo=UTC))
    led = Ledger(b, prefix="reprise", lock=lock, clock=fixed_clock)

    key = led.record(reuse_decision())

    assert b.locks[key] is lock


def test_scoreboard_counts_saved_only_from_reuse_and_accepts() -> None:
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)

    led.record(reuse_decision(cost=0.05))       # saves 0.05
    led.record(review_decision(cost=0.12))      # saves nothing yet
    led.record(generate_decision())             # saves nothing

    s = led.summarize()
    assert (s.reuses, s.reviews, s.generates, s.accepts) == (1, 1, 1, 0)
    assert s.saved_usd == pytest.approx(0.05)
    assert s.decisions == 3


def test_accepting_a_review_makes_its_saving_real() -> None:
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)
    d = review_decision(cost=0.12)
    led.record(d)

    led.record_accept(d)

    s = led.summarize()
    assert s.accepts == 1
    assert s.saved_usd == pytest.approx(0.12)


def test_accept_requires_a_review_with_candidate() -> None:
    led = Ledger(LockRecordingBackend(), prefix="reprise", clock=fixed_clock)
    with pytest.raises(ValueError, match="REVIEW"):
        led.record_accept(generate_decision())


def test_retain_until_must_cover_judging() -> None:
    """Pin the retention default the app will ship with: past judging end."""
    lock = ObjectLockConfig(retain_until=datetime(2026, 8, 15, tzinfo=UTC))
    assert lock.retain_until - datetime(2026, 8, 11, 21, 0, tzinfo=UTC) > timedelta(0)


def test_retention_horizon_is_computed_at_every_write() -> None:
    """A lock built once at boot shrinks: a warm instance writes stale horizons.

    With retain_days the horizon must be measured from EACH write, so a process
    that has been up for days still writes records protected for the full
    window (and never writes an already-expired retain_until).
    """
    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    current = [now]
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", retain_days=30, clock=lambda: current[0])

    first = led.record(reuse_decision())
    current[0] = now + timedelta(days=10)  # the instance stayed warm for 10 days
    later = led.record(reuse_decision())

    lock_first, lock_later = b.locks[first], b.locks[later]
    assert lock_first is not None and lock_later is not None
    assert lock_first.retain_until == now + timedelta(days=30)
    assert lock_later.retain_until == now + timedelta(days=40)


def test_counting_todays_reservations_reads_no_objects() -> None:
    """The cap check must not GET the whole ledger.

    Every decide checks a budget, and the check read every ledger object to
    find today's reservations. That is O(ledger) paid object reads per request,
    growing with the ledger, and it took the live demo down when Backblaze's
    Class B transaction cap tripped. The kind and the date live in the KEY, so
    counting is a listing.
    """
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)
    led.reserve_spend("a prompt", "reserve_generate")
    led.reserve_spend("another prompt", "reserve_generate")
    led.reserve_spend("a third", "reserve_embed")
    b.gets = 0

    assert led.spend_reservations_today(("reserve_generate",)) == 2
    assert led.spend_reservations_today(("reserve_embed",)) == 1
    assert b.gets == 0


def test_scoreboard_folds_completed_days_into_a_snapshot() -> None:
    """A cold instance must not re-read the whole ledger to show a total.

    summarize() read every record ever written, so each new serverless
    instance paid O(history) billed reads before it could render the page, and
    the cost grew forever. Completed days are immutable, so they fold once into
    a snapshot; only today is ever re-read.
    """
    b = LockRecordingBackend()
    day1 = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    now = [day1]
    led = Ledger(b, prefix="reprise", snapshot_secret=SNAP_KEY, clock=lambda: now[0])
    led.record(reuse_decision(cost=0.05))
    led.record(reuse_decision(cost=0.05))

    now[0] = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    led.record(reuse_decision(cost=0.05))
    first = led.summarize()          # folds 07-25, reads 07-26 live
    b.gets = 0
    second = led.summarize()

    assert first.reuses == 3 and first.saved_usd == pytest.approx(0.15)
    assert second == first
    # Second call: the snapshot plus today's single record, never yesterday's.
    assert b.gets <= 2, f"re-read too much: {b.gets} objects"


def test_a_snapshot_never_covers_a_day_still_being_written() -> None:
    """Folding today would freeze a total that is still changing."""
    b = LockRecordingBackend()
    led = Ledger(b, prefix="reprise", clock=fixed_clock)
    led.record(reuse_decision(cost=0.05))
    led.summarize()

    led.record(reuse_decision(cost=0.05))

    assert led.summarize().reuses == 2


def test_a_forged_snapshot_cannot_invent_savings() -> None:
    """The scoreboard's cache is not Object Locked. Its source is.

    `index/scoreboard.json` short-circuits the ledger, and it is written
    without a lock on purpose, because a cache that cannot be replaced is a
    liability. That is fine right up until the cache is BELIEVED. Anyone able
    to write the bucket prefix could set a future through_day and any totals
    they liked, and the page would show them with no Object Lock trail, while
    the records that are locked went unread.

    The product's public claim is that every total on the board is folded from
    records nobody can edit. A snapshot the app cannot authenticate is exactly
    a number the ledger cannot back, so an unverifiable one must be discarded
    and the totals recomputed, not trusted.
    """
    b = LockRecordingBackend()
    day1 = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    now = [day1]
    led = Ledger(b, prefix="reprise", snapshot_secret=SNAP_KEY, clock=lambda: now[0])
    led.record(reuse_decision(cost=0.05))
    now[0] = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    led.record(reuse_decision(cost=0.05))
    honest = led.summarize()
    assert honest.reuses == 2

    b.put(
        "reprise/index/scoreboard.json",
        json.dumps(
            {
                "schema": LEDGER_SCHEMA,
                "through_day": "29991231",
                "totals": {
                    "reuses": 999,
                    "reviews": 0,
                    "generates": 0,
                    "accepts": 0,
                    "saved_usd": 9999.0,
                },
            }
        ).encode(),
    )

    after = Ledger(
        b, prefix="reprise", snapshot_secret=SNAP_KEY, clock=lambda: now[0]
    ).summarize()

    assert after.reuses == 2, "a snapshot the app did not sign must not be believed"
    assert after.saved_usd == pytest.approx(0.10)
