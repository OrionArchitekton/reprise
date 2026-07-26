"""Slice 3: embeddings.

Unit tests run entirely on the deterministic HashEmbedder. The OpenAI path is
integration-proven by `tools/live_probe.py` (a real call, output pasted into
docs/run-evidence.md) rather than mocked here -- a mocked HTTP round-trip would
pin our guess of the response shape, not the provider's actual shape.
"""

from __future__ import annotations

import pytest

from reprise.embed import EmbedError, HashEmbedder, OpenAIEmbedder, prompt_fingerprint
from reprise.nearmatch import cosine


def test_fingerprint_is_normalization_stable() -> None:
    assert prompt_fingerprint("A Red  Bicycle ") == prompt_fingerprint("a red bicycle")


def test_fingerprint_differs_for_different_prompts() -> None:
    assert prompt_fingerprint("a red bicycle") != prompt_fingerprint("a blue bicycle")


def test_hash_embedder_is_deterministic_and_normalization_stable() -> None:
    e = HashEmbedder()
    assert e.embed("A Red  Bicycle") == e.embed("a red bicycle")


def test_hash_embedder_identical_text_scores_one() -> None:
    e = HashEmbedder()
    assert cosine(e.embed("a red bicycle"), e.embed("a red bicycle")) == pytest.approx(1.0)


def test_hash_embedder_small_edit_scores_high_but_below_one() -> None:
    e = HashEmbedder()
    sim = cosine(e.embed("a red bicycle against a white wall"),
                 e.embed("a blue bicycle against a white wall"))
    assert 0.5 < sim < 1.0


def test_hash_embedder_unrelated_text_scores_low() -> None:
    e = HashEmbedder()
    sim = cosine(e.embed("a red bicycle against a white wall"),
                 e.embed("quarterly revenue forecast spreadsheet"))
    assert sim < 0.35


def test_hash_embedder_unit_norm() -> None:
    v = HashEmbedder().embed("a red bicycle")
    assert sum(x * x for x in v) == pytest.approx(1.0)


def test_openai_embedder_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env fallback removed so the test holds even when run under `doppler run`.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbedError, match="OPENAI_API_KEY"):
        OpenAIEmbedder(api_key="", model="text-embedding-3-small")
