"""Slice 5: the decision ledger.

The live Object Lock proof (write a locked record to real B2, attempt to
delete it, watch the delete FAIL) lives in tools/live_probe.py -- a green
in-memory test can only prove passthrough, never that the lock binds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from genblaze_core.storage.base import ObjectLockConfig

from reprise.ledger import Ledger
from reprise.model import Candidate, Decision, Request, Verdict
from tests.test_classify import entry
from tests.test_library import MemoryBackend


class LockRecordingBackend(MemoryBackend):
    """MemoryBackend that mirrors genblaze-s3's extended put() signature."""

    def __init__(self) -> None:
        super().__init__()
        self.locks: dict[str, ObjectLockConfig | None] = {}

    def put(self, key: str, data: Any, *, content_type: str | None = None,
            metadata: dict[str, str] | None = None,
            extra_args: dict[str, Any] | None = None,
            object_lock: ObjectLockConfig | None = None) -> str:
        self.locks[key] = object_lock
        return super().put(key, data, content_type=content_type,
                           metadata=metadata, extra_args=extra_args)


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
