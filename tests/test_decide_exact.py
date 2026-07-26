"""Slice 1: exact-prompt reuse under hard constraints.

The cheapest and most defensible reuse is the one that needs no similarity
threshold at all: the same prompt, under the same hard constraints, asked twice.
This slice proves that path end to end before any embedding is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reprise.decide import decide
from reprise.model import LibraryEntry, Request, Verdict


def entry(**over: object) -> LibraryEntry:
    base: dict[str, object] = {
        "asset_id": "a1",
        "prompt": "a red bicycle against a white wall",
        "modality": "image",
        "sha256": "f" * 64,
        "storage_key": "assets/ff/ff/" + "f" * 64 + ".png",
        "cost_usd": 0.04,
        "provider": "openai",
        "model": "gpt-image-1",
        "run_id": "run-1",
        "created_at": datetime(2026, 7, 20, tzinfo=UTC),
        "aspect_ratio": "1:1",
        "style": "photo",
    }
    base.update(over)
    return LibraryEntry(**base)  # type: ignore[arg-type]


def test_identical_prompt_and_constraints_is_reused() -> None:
    lib = [entry()]
    req = Request(
        prompt="a red bicycle against a white wall",
        modality="image",
        aspect_ratio="1:1",
        style="photo",
    )

    d = decide(req, lib)

    assert d.verdict is Verdict.REUSE
    assert d.candidate is not None
    assert d.candidate.exact is True
    assert d.candidate.entry.asset_id == "a1"
    # The saving is the cost the library entry actually incurred, not a guess.
    assert d.saved_usd == pytest.approx(0.04)


def test_prompt_match_is_normalized_for_whitespace_and_case() -> None:
    lib = [entry()]
    req = Request(
        prompt="  A RED  Bicycle   against a White Wall ",
        modality="image",
        aspect_ratio="1:1",
        style="photo",
    )

    d = decide(req, lib)

    assert d.verdict is Verdict.REUSE
    assert d.candidate is not None and d.candidate.exact is True


def test_empty_library_generates() -> None:
    req = Request(prompt="a red bicycle", modality="image")

    d = decide(req, [])

    assert d.verdict is Verdict.GENERATE
    assert d.candidate is None
    assert d.saved_usd == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("modality", "video"),
        ("aspect_ratio", "16:9"),
        ("style", "illustration"),
    ],
)
def test_hard_constraint_mismatch_never_reuses(field: str, value: str) -> None:
    """A constraint mismatch is disqualifying regardless of prompt identity.

    This is the false-positive control for slice 1: the prompt is byte-identical,
    so only the hard filter can save us from serving a wrong-shaped asset.
    """
    lib = [entry()]
    kwargs: dict[str, object] = {
        "prompt": "a red bicycle against a white wall",
        "modality": "image",
        "aspect_ratio": "1:1",
        "style": "photo",
    }
    kwargs[field] = value
    req = Request(**kwargs)  # type: ignore[arg-type]

    d = decide(req, lib)

    assert d.verdict is Verdict.GENERATE, f"{field}={value} must not be substitutable"
    assert d.saved_usd == 0.0


def test_cheapest_exact_match_wins_when_several_qualify() -> None:
    """Reuse should not be arbitrary when the library holds duplicates.

    Ties are broken toward the entry whose recorded cost is highest, because that
    is the spend the reuse actually avoids repeating.
    """
    lib = [
        entry(asset_id="cheap", cost_usd=0.01, run_id="run-a"),
        entry(asset_id="pricey", cost_usd=0.19, run_id="run-b"),
    ]
    req = Request(
        prompt="a red bicycle against a white wall",
        modality="image",
        aspect_ratio="1:1",
        style="photo",
    )

    d = decide(req, lib)

    assert d.verdict is Verdict.REUSE
    assert d.candidate is not None
    assert d.candidate.entry.asset_id == "pricey"
    assert d.saved_usd == pytest.approx(0.19)
    # The runner-up is retained so the ledger can show what else qualified.
    assert [c.entry.asset_id for c in d.alternatives] == ["cheap"]
