#!/usr/bin/env python3
"""What verdict does a prompt get? Preview only: nothing is generated.

Written as a pre-render gate for the demo video. The generate shot types a
near-duplicate, expects a REVIEW card, and clicks "generate fresh instead", so
that prompt MUST land in [0.85, 0.97). It does not STAY there: the render
generates the asset and files it under that prompt, so the same text is an
exact match on the next run and the shot silently becomes a reuse. Pick a fresh
prompt and check it here before every render.

Two modes:

  --live (default) drives the real library through the production Gateway.
  --offline scores against a single known stored prompt, for when B2 reads are
  unavailable. That is a LOWER bound, since the real verdict takes the max over
  every substitutable entry: it can never wrongly promise a review that is
  really a generate, but it can miss a reuse.

Either way the thresholds come from the production `classify`, never from a
copy of the numbers here.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, "src")

from genblaze_core.storage.base import ObjectLockConfig
from genblaze_s3 import S3StorageBackend

from reprise.embed import GeminiEmbedder
from reprise.gateway import Gateway
from reprise.ledger import Ledger
from reprise.model import LibraryEntry, Request
from reprise.nearmatch import classify, score_candidates

# The image prompt tools/live_generate.py seeded the library with. Used only by
# --offline, where there is no way to read what the library actually holds.
SEEDED = "a red bicycle leaning against a white brick wall, product photo"

DEFAULT_PROMPTS = [
    "a red bicycle leaning against a white brick wall, product photo",
    "a crimson bicycle propped against a white brick wall, product shot",
    "a lighthouse on a cliff in a thunderstorm, oil painting",
]


def probe_live(prompts: list[str]) -> None:
    backend = S3StorageBackend.for_backblaze()
    ledger = Ledger(
        backend,
        prefix="reprise",
        lock=ObjectLockConfig(retain_until=datetime.now(UTC) + timedelta(days=30)),
    )
    # No providers configured: preview() never generates, and an empty map makes
    # that structural rather than a promise in a comment.
    gw = Gateway(backend, GeminiEmbedder(), ledger, {}, prefix="reprise")
    for prompt in prompts:
        d = gw.preview(Request(prompt=prompt, modality="image"))
        sim = f"{d.candidate.similarity:.4f}" if d.candidate else "n/a"
        print(f"{d.verdict.value:8s} sim={sim}  {prompt}")
        print(f"{'':8s}          {d.reason}")


def probe_offline(prompts: list[str]) -> None:
    emb = GeminiEmbedder()
    entry = LibraryEntry(
        asset_id="seeded",
        prompt=SEEDED,
        modality="image",
        sha256="0" * 64,
        storage_key="reprise/assets/seeded.png",
        cost_usd=0.04,
        provider="gemini",
        model="gemini-2.5-flash-image",
        run_id="run-seeded",
        created_at=datetime(2026, 7, 26, tzinfo=UTC),
        embedding=emb.embed(SEEDED),
    )
    print(f"offline mode: scoring against one known entry ({SEEDED!r})\n")
    for prompt in prompts:
        req = Request(prompt=prompt, modality="image")
        d = classify(req, score_candidates(req, emb.embed(prompt), [entry]))
        sim = f"{d.candidate.similarity:.4f}" if d.candidate else "n/a"
        print(f"{d.verdict.value:8s} sim={sim}  {prompt}")


def main() -> None:
    args = sys.argv[1:]
    prompts = [a for a in args if not a.startswith("--")] or DEFAULT_PROMPTS
    if "--offline" in args:
        probe_offline(prompts)
    else:
        probe_live(prompts)


if __name__ == "__main__":
    main()
