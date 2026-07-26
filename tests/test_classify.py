"""Slice 2.5: the acceptance policy (operator-chosen: bolder auto-reuse).

Policy, as decided 2026-07-26:

    exact match          -> REUSE   (short-circuits thresholds)
    similarity >= 0.97   -> REUSE   (automatic)
    0.85 <= sim < 0.97   -> REVIEW  (human accepts; saves nothing until then)
    similarity < 0.85    -> GENERATE

The known cost of the bolder line: attribute swaps ("red" vs "blue") can score
above 0.97 and auto-serve the wrong asset. That defect class is measured by the
eval set and disclosed, not hidden -- these tests pin the policy, the eval
reports its consequences.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reprise.model import Candidate, LibraryEntry, Request, Verdict
from reprise.nearmatch import AUTO_REUSE_THRESHOLD, REVIEW_THRESHOLD, classify


def entry(asset_id: str = "a1", cost: float = 0.05) -> LibraryEntry:
    return LibraryEntry(
        asset_id=asset_id,
        prompt="a red bicycle against a white wall",
        modality="image",
        sha256="f" * 64,
        storage_key="reprise/assets/ff/ff/" + "f" * 64 + ".png",
        cost_usd=cost,
        provider="openai",
        model="gpt-image-1",
        run_id="run-1",
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        aspect_ratio="1:1",
        style="photo",
    )


REQ = Request(prompt="a red bicycle against a white wall", modality="image")


def cand(sim: float, exact: bool = False, **over: object) -> Candidate:
    return Candidate(entry=entry(**over), similarity=sim, exact=exact)  # type: ignore[arg-type]


def test_no_candidates_generates() -> None:
    d = classify(REQ, [])
    assert d.verdict is Verdict.GENERATE
    assert d.candidate is None
    assert d.saved_usd == 0.0


def test_exact_match_reuses_and_saves_entry_cost() -> None:
    d = classify(REQ, [cand(1.0, exact=True, cost=0.19)])
    assert d.verdict is Verdict.REUSE
    assert d.saved_usd == pytest.approx(0.19)
    assert "exact" in d.reason


def test_above_auto_threshold_reuses_automatically() -> None:
    d = classify(REQ, [cand(0.98, cost=0.07)])
    assert d.verdict is Verdict.REUSE
    assert d.saved_usd == pytest.approx(0.07)


def test_at_auto_threshold_boundary_reuses() -> None:
    d = classify(REQ, [cand(AUTO_REUSE_THRESHOLD)])
    assert d.verdict is Verdict.REUSE


def test_review_band_reviews_and_saves_nothing_yet() -> None:
    """A review has not saved anything: only an accepted reuse counts.

    This keeps the savings headline honest -- the scoreboard number must never
    include money a human has not yet agreed was saved.
    """
    d = classify(REQ, [cand(0.90, cost=0.12)])
    assert d.verdict is Verdict.REVIEW
    assert d.candidate is not None
    assert d.saved_usd == 0.0


def test_at_review_threshold_boundary_reviews() -> None:
    d = classify(REQ, [cand(REVIEW_THRESHOLD)])
    assert d.verdict is Verdict.REVIEW


def test_below_review_band_generates() -> None:
    d = classify(REQ, [cand(0.84)])
    assert d.verdict is Verdict.GENERATE
    assert d.candidate is None


def test_runners_up_are_kept_as_alternatives_for_review() -> None:
    ranked = [cand(0.92, asset_id="best"), cand(0.88, asset_id="second")]
    d = classify(REQ, ranked)
    assert d.verdict is Verdict.REVIEW
    assert d.candidate is not None and d.candidate.entry.asset_id == "best"
    assert [c.entry.asset_id for c in d.alternatives] == ["second"]


def test_reason_carries_similarity_for_the_ledger() -> None:
    d = classify(REQ, [cand(0.91)])
    assert "0.91" in d.reason
