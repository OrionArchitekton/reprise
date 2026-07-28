"""Slice 6: the gateway, exercised through a REAL genblaze Pipeline.

The GENERATE path in these tests is not a stub of the pipeline -- it runs
`Pipeline().step(MockProvider...).run(sink=ObjectStorageSink(...))` against the
in-memory backend, with a real file:// asset the sink fetches and hashes. What
is mocked is the PROVIDER (no network, no spend); the orchestration, transfer,
hashing, manifest sealing and ingest are all the real SDK code paths.
"""

from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from genblaze_core import Asset, MockProvider

from reprise.embed import HashEmbedder
from reprise.gateway import Gateway, LibraryUnavailable
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
        index_secret=b"test-index-key",
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
    # The candidate MUST be served: a review asks a human to judge whether this
    # asset substitutes for what they asked for, and that judgement is not
    # possible from a prompt string and a similarity score alone. Serving costs
    # nothing (the bytes are already paid for) and no saving is booked until the
    # human accepts.
    assert r.serve_url is not None


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


def test_an_unreadable_library_never_becomes_a_reason_to_spend() -> None:
    """A storage failure must not read as "you do not own this".

    When B2's transaction cap tripped, every manifest read failed, scan()
    returned an empty projection, and the gateway concluded the library held
    nothing and generated: the product paid twice for an asset it already
    owned, which is the one outcome it exists to prevent. An incomplete
    projection is not evidence of absence, so it cannot authorise spend.
    """
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    assets_before = sum(1 for k in backend.objects if k.startswith("reprise/assets/"))

    # Every read of the library now fails, exactly as it did under the cap. The
    # index is refused alongside the manifests on purpose: it is a cache OF the
    # manifests, so a cap that hides them hides it too, and "cannot see the
    # library at all" is the condition this refusal exists for. When the index
    # IS readable the gateway rightly serves from it, which is a separate test.
    def refuse(key: str) -> bytes:
        if "/manifests/" in key or "/index/" in key:
            raise RuntimeError("Class B transaction cap exceeded")
        return MemoryBackend.get(backend, key)

    backend.get = refuse  # type: ignore[method-assign]
    gw.library.invalidate()

    with pytest.raises(LibraryUnavailable):
        gw.handle(Request(prompt="something entirely new", modality="image"))

    assert sum(1 for k in backend.objects if k.startswith("reprise/assets/")) == assets_before


def test_a_generate_record_names_what_it_produced() -> None:
    """An audit trail that says "we generated" without saying WHAT is thin.

    The reuse records carry the asset they served; the generate records carried
    only the prompt and the cost, so nothing tied the money spent to the object
    it bought. The ledger now names the run, the digest and the key.
    """
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())

    r = gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))

    (rec,) = [
        json.loads(backend.objects[k])
        for k in backend.objects
        if "/ledger/" in k and "/decision/" in k
    ]
    assert rec["verdict"] == "generate"
    assert r.new_entry is not None
    assert rec["produced"]["run_id"] == r.new_entry.run_id
    assert rec["produced"]["sha256"] == r.new_entry.sha256
    assert rec["produced"]["storage_key"] == r.new_entry.storage_key


def test_the_manifest_behind_a_result_can_be_opened() -> None:
    """Provenance a judge cannot open is provenance they have to take on faith.

    The receipt quotes a manifest key and its canonical hash, but the bucket is
    private, so nobody outside could fetch the manifest and recompute the hash.
    A short-lived link makes the claim checkable by the person reading it.
    """
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    r = gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    assert r.new_entry is not None

    url = gw.manifest_url(r.new_entry.run_id)

    assert f"reprise/manifests/{r.new_entry.run_id}.json" in url
    with pytest.raises(ValueError, match="refusing"):
        gw.manifest_url("../ledger/secret")


def test_a_warm_gateway_answers_a_near_dupe_without_billed_reads() -> None:
    """The whole outage in one assertion: what does a repeat request cost?

    Reads are what B2 bills as Class B, and exhausting that cap is what took
    the demo down. The two caches sit in different objects (the projection in
    the scan cache, the vectors in the sidecar memo), so only a request driven
    through the real entry point proves they compose into zero. A regression in
    either one shows up here as a number greater than zero, long before it
    shows up as an outage.
    """
    backend = MemoryBackend()
    gw = make_gateway(backend, CountingEmbedder())
    gw.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    gw.preview(Request(prompt="a blue bicycle against a white wall", modality="image"))

    reads_before = backend.gets
    d = gw.preview(Request(prompt="a green bicycle against a white wall", modality="image"))

    assert d.verdict is Verdict.REVIEW
    assert backend.gets == reads_before, "a warm request must read no objects"


def test_a_peer_instance_does_not_pay_to_regenerate_what_this_one_just_made() -> None:
    """The one outcome the product exists to prevent, across two instances.

    The projection cache is per process and `invalidate()` clears only the
    local one, so an instance that generates an asset tells nobody. A second
    instance serving the very next request answers from a library that does
    not contain it yet, and pays to make it again. Both external reviewers
    reproduced this; it is a reuse product paying twice.

    Two gateways over ONE backend is the whole point: that is two serverless
    instances sharing a bucket.
    """
    backend = MemoryBackend()
    first = make_gateway(backend, CountingEmbedder())
    second = make_gateway(backend, CountingEmbedder())
    prompt = "a red bicycle against a white wall"

    # Both are warm and both have seen the empty library.
    first.preview(Request(prompt="something else entirely", modality="image"))
    second.preview(Request(prompt="another unrelated thing", modality="image"))

    first.handle(Request(prompt=prompt, modality="image"))
    assets_after_first = sum(
        1 for k in backend.objects if k.startswith("reprise/assets/")
    )

    result = second.handle(Request(prompt=prompt, modality="image"))

    assert result.decision.verdict is Verdict.REUSE, (
        "the peer must see what the other instance just filed, not pay again"
    )
    assert (
        sum(1 for k in backend.objects if k.startswith("reprise/assets/"))
        == assets_after_first
    ), "a second asset was generated for a prompt already in the library"


def test_an_index_keeps_the_library_answerable_when_manifests_are_capped() -> None:
    """The outage that took the demo down twice, survived rather than refused.

    Under the Class B cap every manifest read failed, the projection came back
    empty, and the app refused to decide. Refusing was the right answer to a
    library it could not see. But the library is one signed object now, so a
    cap that hides the manifests no longer hides the library: one read still
    answers, and a reuse is served instead of a 503.

    This is not the fail-closed test relaxing. When the index is unreadable too,
    the gateway still refuses; that is asserted separately.
    """
    backend = MemoryBackend()
    writer = make_gateway(backend, CountingEmbedder())
    writer.handle(Request(prompt="a red bicycle against a white wall", modality="image"))
    assets_before = sum(1 for k in backend.objects if k.startswith("reprise/assets/"))

    def refuse_manifests(key: str) -> bytes:
        if "/manifests/" in key:
            raise RuntimeError("Class B transaction cap exceeded")
        return MemoryBackend.get(backend, key)

    backend.get = refuse_manifests  # type: ignore[method-assign]
    cold = make_gateway(backend, CountingEmbedder())

    result = cold.handle(
        Request(prompt="a red bicycle against a white wall", modality="image")
    )

    assert result.decision.verdict is Verdict.REUSE
    assert (
        sum(1 for k in backend.objects if k.startswith("reprise/assets/"))
        == assets_before
    ), "nothing may be generated while the manifests are unreadable"
