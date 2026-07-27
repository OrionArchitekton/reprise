"""Slice 4: the B2-backed library.

The library is a projection over the manifests Genblaze writes to the bucket,
plus embedding sidecars keyed by prompt fingerprint. Tests run against a ~25
line in-memory StorageBackend (the same pattern Cinemory's team reported using
against this SDK); the live path is proven by tools/live_probe.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

# Deep imports: the package's lazy __getattr__ export surface types as Any
# (genblaze issue #55), and mypy strict refuses to subclass Any. The defining
# modules carry real types.
import pytest
from genblaze_core.storage.base import StorageBackend
from genblaze_core.storage.errors import StorageError, StorageErrorCode
from genblaze_core.storage.types import FileEntry, ListPage

from reprise.embed import HashEmbedder, prompt_fingerprint
from reprise.library import B2Library
from reprise.model import LibraryEntry
from tests.test_ingest import manifest_dict, rehash


def library_entry(prompt: str) -> LibraryEntry:
    return LibraryEntry(
        asset_id="a1",
        prompt=prompt,
        modality="image",
        sha256="0" * 64,
        storage_key="reprise/assets/a1.png",
        cost_usd=0.04,
        provider="gemini",
        model="gemini-2.5-flash-image",
        run_id="run-1",
        created_at=datetime(2026, 7, 26, tzinfo=UTC),
    )


class MemoryBackend(StorageBackend):
    """Minimal in-memory StorageBackend for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.locks: dict[str, Any] = {}
        self.gets = 0

    def put(self, key: str, data: Any, *, content_type: str | None = None,
            metadata: dict[str, str] | None = None,
            extra_args: dict[str, Any] | None = None,
            object_lock: Any = None) -> str:
        # Mirrors genblaze-s3's extended signature. A double that rejects
        # object_lock makes every locked write look like a backend failure,
        # which is exactly the fail-closed path, so the app under test would
        # 503 for a reason production never has.
        self.objects[key] = data if isinstance(data, bytes) else data.read()
        self.locks[key] = object_lock
        return key

    def get(self, key: str) -> bytes:
        # Counted: B2 charges per object read (Class B), and the whole point of
        # the index work is that a steady-state request performs almost none.
        self.gets += 1
        try:
            return self.objects[key]
        except KeyError:
            # Typed like the real backend. A double that raised KeyError let
            # callers "handle absence" with a bare except, which is what made a
            # capped bucket indistinguishable from an empty cache in production.
            raise StorageError(
                f"no such key: {key}",
                error_code=StorageErrorCode.NOT_FOUND,
                status_code=404,
                operation="get",
            ) from None

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    # Path-style, bucket-in-path, exactly like the real S3/B2 URLs the sink
    # writes into manifests. A shorter fake shape made ingest's bucket-segment
    # strip mangle every storage_key in tests while looking green.
    def get_url(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://memory-host/bucket/{key}?exp={expires_in}"

    def get_durable_url(self, key: str) -> str:
        return f"memory://memory-host/bucket/{key}"

    def list(self, prefix: str = "", *, max_keys: int = 1000,
             continuation_token: str | None = None) -> ListPage:
        entries = tuple(
            FileEntry(
                key=k,
                size=len(v),
                last_modified=datetime(2026, 7, 26, tzinfo=UTC),
                etag=f"etag-{k}",
            )
            for k, v in sorted(self.objects.items())
            if k.startswith(prefix)
        )
        return ListPage(entries=entries, next_token=None)


def seeded_backend() -> MemoryBackend:
    b = MemoryBackend()
    m = manifest_dict()
    b.put("reprise/manifests/f262d532-c38c-40f9-8b94-c0b8dd14740e.json",
          json.dumps(m).encode())
    return b


def test_scan_projects_manifests_into_entries() -> None:
    lib = B2Library(seeded_backend(), prefix="reprise")

    entries = lib.scan()

    assert len(entries) == 1
    assert entries[0].prompt == "a red bicycle against a white wall"
    assert entries[0].embedding is None  # no sidecar yet


def test_ensure_embeddings_writes_sidecars_and_attaches_vectors() -> None:
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise")
    embedder = HashEmbedder(dims=16)

    entries = lib.scan()
    entries = lib.ensure_embeddings(entries, embedder)

    (e,) = entries
    assert e.embedding is not None and len(e.embedding) == 16
    fp = prompt_fingerprint(e.prompt)
    assert backend.exists(f"reprise/embeddings/{fp}.json")


def test_ensure_embeddings_is_idempotent_and_reads_cache() -> None:
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise")

    first = lib.ensure_embeddings(lib.scan(), HashEmbedder(dims=16))

    # Same type NAME as the cache writer (the sidecar guard matches on it),
    # but embed() explodes -- so a green pass proves the vector came from the
    # sidecar, not from a recompute.
    class CountingHash(HashEmbedder):
        def embed(self, prompt: str) -> tuple[float, ...]:
            raise AssertionError("cache hit expected; embedder must not be called")

    CountingHash.__name__ = "HashEmbedder"
    CountingHash.__qualname__ = "HashEmbedder"

    second = lib.ensure_embeddings(lib.scan(), CountingHash(dims=16))
    assert second[0].embedding == first[0].embedding


def test_mixing_embedders_is_refused() -> None:
    """Vectors from different embedders are different spaces; comparing them
    silently would corrupt every similarity score in the library."""
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise")
    lib.ensure_embeddings(lib.scan(), HashEmbedder(dims=16))

    class OtherEmbedder:
        def embed(self, prompt: str) -> tuple[float, ...]:
            return (1.0,)

    import pytest as _pytest

    with _pytest.raises(ValueError, match="mixing vector spaces"):
        lib.ensure_embeddings(lib.scan(), OtherEmbedder())


def test_scan_skips_corrupt_manifests_but_keeps_good_ones() -> None:
    backend = seeded_backend()
    backend.put("reprise/manifests/corrupt.json", b"{not json")
    lib = B2Library(backend, prefix="reprise")

    entries = lib.scan()

    assert len(entries) == 1  # corrupt one skipped, real one survives
    assert lib.last_scan_skipped == ["reprise/manifests/corrupt.json"]


def test_identical_prompts_share_one_sidecar() -> None:
    backend = seeded_backend()
    m2 = manifest_dict()
    m2["run"]["run_id"] = "run-2"
    sha2 = "d" * 64
    m2["run"]["steps"][0]["assets"][0]["asset_id"] = "asset-2"
    m2["run"]["steps"][0]["assets"][0]["sha256"] = sha2
    backend.put("reprise/manifests/run-2.json", json.dumps(rehash(m2)).encode())
    lib = B2Library(backend, prefix="reprise")

    entries = lib.ensure_embeddings(lib.scan(), HashEmbedder(dims=16))

    assert len(entries) == 2
    sidecars = [k for k in backend.objects if k.startswith("reprise/embeddings/")]
    assert len(sidecars) == 1  # same normalized prompt -> one shared vector


def test_scan_is_cached_so_repeat_requests_do_not_re_read_every_manifest() -> None:
    """Each request re-read every manifest object, and B2 bills per read.

    That is O(library) paid transactions per request, and it is what tripped
    the account's Class B cap in production. Within the cache window the
    projection is reused; a write invalidates it, so a freshly generated asset
    is never invisible to the next request.
    """
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise", scan_cache_sec=300, clock=lambda: 1000.0)

    lib.scan()
    gets_after_first = backend.gets
    lib.scan()

    assert gets_after_first > 0
    assert backend.gets == gets_after_first  # second scan read nothing

    lib.invalidate()
    lib.scan()
    assert backend.gets > gets_after_first


def test_a_cached_scan_expires() -> None:
    backend = seeded_backend()
    now = [1000.0]
    lib = B2Library(backend, prefix="reprise", scan_cache_sec=60, clock=lambda: now[0])
    lib.scan()
    gets = backend.gets

    now[0] += 61
    lib.scan()

    assert backend.gets > gets


def test_sidecar_vectors_are_not_re_read_on_every_request() -> None:
    """The scan cache covered manifests and left the sidecars uncapped.

    `scan()` caches the projection, but the vectors are attached afterwards, so
    every non-exact request still paid one HEAD plus one GET per distinct
    prompt in the library -- the same O(library) billed read the cap outage was
    caused by, on the same hot path, just one call further down. A sidecar is
    content-addressed by prompt fingerprint and never rewritten, so within a
    process it can be read once and remembered.
    """
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise", clock=lambda: 1000.0)
    embedder = HashEmbedder()
    entries = lib.scan()
    lib.ensure_embeddings(entries, embedder)

    gets_after_first = backend.gets
    second = lib.ensure_embeddings(entries, embedder)

    assert backend.gets == gets_after_first  # a warm process re-reads nothing
    assert all(e.embedding for e in second)


class CappedBackend(MemoryBackend):
    """B2 with its transaction cap exhausted, as the S3 layer surfaces it.

    Reads fail with 403/AccessDenied, and genblaze-s3's `exists()` deliberately
    reports 403 as "does not exist" (least-privilege keys get 403 for HEAD on
    absent keys). So an outage is indistinguishable from an empty cache to any
    caller that asks `exists()` first -- which is how a storage failure turns
    into a bill.
    """

    def exists(self, key: str) -> bool:
        return False

    def get(self, key: str) -> bytes:
        self.gets += 1
        raise StorageError(
            "Cannot download file, download bandwidth or transaction (Class B) "
            "cap exceeded",
            error_code=StorageErrorCode.ACCESS_DENIED,
            status_code=403,
            operation="get",
        )


class CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed(self, prompt: str) -> tuple[float, ...]:
        self.calls += 1
        return super().embed(prompt)


def test_an_unreadable_sidecar_is_not_treated_as_a_missing_one() -> None:
    """A storage failure must never be read as "this vector was never made".

    Absence means embed it and store it; that is a paid API call. If the read
    failed because the bucket is capped or the key is denied, embedding again
    spends money to recompute a vector that already exists, on every request,
    invisibly. Only a typed not-found may authorise that spend.
    """
    backend = CappedBackend()
    lib = B2Library(backend, prefix="reprise", clock=lambda: 1000.0)
    embedder = CountingEmbedder()
    entry = library_entry("a red bicycle against a white wall")

    with pytest.raises(StorageError):
        lib.ensure_embeddings([entry], embedder)

    assert embedder.calls == 0  # nothing was re-embedded on a blind read
    assert not [k for k in backend.objects if "/embeddings/" in k]


def test_the_memo_is_what_makes_a_warm_read_free() -> None:
    """Prove the control binds: turn it off and the reads come back.

    A cache test that passes both with and without the cache is measuring
    nothing. `vector_cache_max=0` disables the memo, which is the state the
    code was in when a request cost one read per library prompt.
    """
    backend = seeded_backend()
    embedder = HashEmbedder()
    entries = B2Library(backend, prefix="reprise").scan()

    off = B2Library(backend, prefix="reprise", vector_cache_max=0)
    off.ensure_embeddings(entries, embedder)
    baseline = backend.gets
    off.ensure_embeddings(entries, embedder)
    uncached_cost = backend.gets - baseline

    on = B2Library(backend, prefix="reprise")
    on.ensure_embeddings(entries, embedder)
    baseline = backend.gets
    on.ensure_embeddings(entries, embedder)

    assert uncached_cost > 0  # this is what every request used to pay
    assert backend.gets == baseline


def test_a_failed_scan_is_not_cached_so_recovery_is_immediate() -> None:
    """Storage recovered, but the app kept serving the failure for 120s.

    A projection built while objects were unreadable is known-incomplete, and
    caching it means the next request reuses that incompleteness instead of
    retrying. Worse, the cache-hit path returns before `last_scan_unreadable`
    is reset, so the readiness probe keeps reporting degraded and the gateway
    keeps refusing to decide, for the whole cache window AFTER B2 is fine
    again. Observed in production 2026-07-27: reads recovered and the live
    /readyz stayed 503.

    Fail-closed is right while the read is failing. Staying closed after it
    starts working is just an outage we are causing ourselves.
    """
    backend = seeded_backend()
    lib = B2Library(backend, prefix="reprise", scan_cache_sec=300, clock=lambda: 1000.0)

    real_get = backend.get
    backend.get = lambda key: (_ for _ in ()).throw(  # type: ignore[method-assign]
        StorageError("cap exceeded", error_code=StorageErrorCode.ACCESS_DENIED)
    )
    assert lib.scan() == []
    assert lib.last_scan_unreadable  # the failure was recorded

    backend.get = real_get  # type: ignore[method-assign]
    entries = lib.scan()

    assert entries, "a recovered backend must be re-read, not served from a failed cache"
    assert not lib.last_scan_unreadable, "readiness must clear as soon as reads work"
