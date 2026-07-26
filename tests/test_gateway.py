"""Slice 6: the gateway, exercised through a REAL genblaze Pipeline.

The GENERATE path in these tests is not a stub of the pipeline -- it runs
`Pipeline().step(MockProvider...).run(sink=ObjectStorageSink(...))` against the
in-memory backend, with a real file:// asset the sink fetches and hashes. What
is mocked is the PROVIDER (no network, no spend); the orchestration, transfer,
hashing, manifest sealing and ingest are all the real SDK code paths.
"""

from __future__ import annotations

import hashlib
import struct
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from genblaze_core import Asset, MockProvider

from reprise.embed import HashEmbedder
from reprise.gateway import Gateway
from reprise.ledger import Ledger
from reprise.model import Request, Verdict
from tests.test_library import MemoryBackend


def png_bytes(rgb: tuple[int, int, int]) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + chunk(b"IEND", b"")


def mock_image_provider() -> MockProvider:
    """A provider whose asset is a real local PNG the sink can fetch."""
    data = png_bytes((255, 0, 0))
    p = Path(tempfile.mkdtemp()) / "out.png"
    p.write_bytes(data)
    return MockProvider(
        assets=[
            Asset(
                asset_id="gen-1",
                url=f"file://{p}",
                media_type="image/png",
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            )
        ],
        cost_usd=0.05,
    )


class CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__(dims=32)
        self.calls = 0

    def embed(self, prompt: str) -> tuple[float, ...]:
        self.calls += 1
        return super().embed(prompt)


# Keep the sidecar guard consistent across gateway rescans in one test.
CountingEmbedder.__name__ = "HashEmbedder"
CountingEmbedder.__qualname__ = "HashEmbedder"


def fixed_clock() -> datetime:
    return datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def make_gateway(backend: MemoryBackend, embedder: CountingEmbedder) -> Gateway:
    return Gateway(
        backend,
        embedder,
        Ledger(backend, prefix="reprise", clock=fixed_clock),
        {"image": (mock_image_provider, "mock-image-v1")},
        prefix="reprise",
    )


def test_novel_prompt_generates_persists_and_ledgers() -> None:
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())

    r = gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))

    assert r.decision.verdict is Verdict.GENERATE
    assert r.new_entry is not None
    assert r.new_entry.cost_usd == 0.05
    # The sink really persisted asset + manifest into the backend.
    keys = list(backend.objects)
    assert any(k.startswith("reprise/assets/") for k in keys)
    assert any(k.startswith("reprise/manifests/") for k in keys)
    assert any(k.startswith("reprise/ledger/") for k in keys)
    assert r.serve_url is not None


def test_exact_repeat_reuses_without_embedding_or_generating() -> None:
    backend = MemoryBackend()
    embedder = CountingEmbedder()
    gw = make_gateway(backend, embedder)
    gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    embedder.calls = 0
    assets_before = sum(1 for k in backend.objects if k.startswith("reprise/assets/"))

    r = gw.handle(Request(prompt="A RED bicycle against a white wall ", modality="image"))

    assert r.decision.verdict is Verdict.REUSE
    assert r.decision.candidate is not None and r.decision.candidate.exact
    assert r.decision.saved_usd == pytest.approx(0.05)
    assert embedder.calls == 0, "exact path must not spend an embedding call"
    assets_after = sum(1 for k in backend.objects if k.startswith("reprise/assets/"))
    assert assets_after == assets_before, "no new asset may be generated"
    assert r.serve_url is not None


def test_near_dupe_goes_to_review_not_generation() -> None:
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    assets_before = sum(1 for k in backend.objects if k.startswith("reprise/assets/"))

    # HashEmbedder trigram space at dims=32: this one-word swap measures
    # sim=0.9517 (probed 2026-07-26) -- inside the [0.85, 0.97) review band.
    r = gw.handle(Request(prompt="a blue bicycle against a white wall", modality="image"))

    assert r.decision.verdict is Verdict.REVIEW
    assert sum(1 for k in backend.objects if k.startswith("reprise/assets/")) == assets_before
    assert r.serve_url is None


def test_accept_review_books_the_saving() -> None:
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    ledger = Ledger(backend, prefix="reprise", clock=fixed_clock)
    gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))

    r = gw.handle(Request(prompt="a blue bicycle against a white wall", modality="image"))
    assert r.decision.verdict is Verdict.REVIEW

    accepted = gw.accept_review(r.decision)

    assert accepted.serve_url is not None
    assert ledger.summarize().saved_usd == pytest.approx(0.05)


def test_unconfigured_modality_is_a_clear_error() -> None:
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    with pytest.raises(ValueError, match="no provider configured for modality 'video'"):
        gw.handle(Request(prompt="a drone shot over a coastal city", modality="video"))
