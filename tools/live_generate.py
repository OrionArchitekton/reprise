#!/usr/bin/env python3
"""Live end-to-end generation proof -- SPENDS REAL MONEY (cents), run manually.

    doppler run -p genblaze-hackathon -c prd -- .venv/bin/python tools/live_generate.py

Drives the REAL spine of the product against the real bucket:

1. novel image request  -> GENERATE via Genblaze ImagenProvider (Gemini API
   key), persisted to B2 by ObjectStorageSink with a verified manifest;
2. the same request again -> REUSE from the library, zero spend, saving booked;
3. novel audio request  -> GENERATE via ElevenLabsTTSProvider, same pipeline.

Output is pasted into docs/run-evidence.md. Any failure prints the provider's
verbatim error and exits nonzero.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

sys.path.insert(0, "src")

from genblaze_core.storage.base import ObjectLockConfig
from genblaze_elevenlabs import ElevenLabsTTSProvider
from genblaze_s3 import S3StorageBackend

from reprise.embed import GeminiEmbedder
from reprise.gateway import Gateway
from reprise.gemini_image import GeminiImageProvider
from reprise.ledger import Ledger
from reprise.model import Request, Verdict

IMAGE_PROMPT = "a red bicycle leaning against a white brick wall, product photo"
AUDIO_PROMPT = "Welcome to Reprise. Before you generate, check what you already own."


def main() -> None:
    backend = S3StorageBackend.for_backblaze()
    lock = ObjectLockConfig(retain_until=datetime(2026, 8, 15, tzinfo=UTC))
    ledger = Ledger(backend, prefix="reprise", lock=lock)
    gw = Gateway(
        backend,
        GeminiEmbedder(),
        ledger,
        {
            # Every imagen-* tier 404s "no longer available to new users" on
            # fresh Gemini keys (probed live 2026-07-26); gemini-2.5-flash-image
            # works, via our custom SyncProvider (see gemini_image.py).
            "image": (GeminiImageProvider, "gemini-2.5-flash-image"),
            "audio": (ElevenLabsTTSProvider, "eleven_flash_v2_5"),
        },
        prefix="reprise",
    )

    print("== 1. novel image request (expects GENERATE, real Imagen spend) ==")
    r1 = gw.handle(Request(prompt=IMAGE_PROMPT, modality="image"))
    assert r1.decision.verdict is Verdict.GENERATE, r1.decision
    assert r1.new_entry is not None
    print(f"  generated: {r1.new_entry.storage_key}")
    print(f"  sha256={r1.new_entry.sha256[:16]}... provider={r1.new_entry.provider} "
          f"model={r1.new_entry.model} cost_usd={r1.new_entry.cost_usd}")

    print("== 2. exact repeat (expects REUSE, zero spend) ==")
    r2 = gw.handle(Request(prompt=IMAGE_PROMPT.upper(), modality="image"))
    assert r2.decision.verdict is Verdict.REUSE, r2.decision
    assert r2.decision.candidate is not None
    assert r2.decision.candidate.entry.sha256 == r1.new_entry.sha256
    print(f"  reused {r2.decision.candidate.entry.asset_id}, "
          f"saved_usd={r2.decision.saved_usd}")
    assert r2.serve_url and r2.serve_url.startswith("https://")

    print("== 3. novel audio request (expects GENERATE via ElevenLabs) ==")
    r3 = gw.handle(Request(prompt=AUDIO_PROMPT, modality="audio"))
    assert r3.decision.verdict is Verdict.GENERATE, r3.decision
    assert r3.new_entry is not None
    print(f"  generated: {r3.new_entry.storage_key}")
    print(f"  provider={r3.new_entry.provider} model={r3.new_entry.model}")

    s = ledger.summarize()
    print(f"== ledger scoreboard: {s.decisions} decisions, {s.reuses} reuse, "
          f"saved_usd={s.saved_usd} ==")
    print("LIVE GENERATION PROOF PASSED")


if __name__ == "__main__":
    main()
