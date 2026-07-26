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
from genblaze_core.storage.base import StorageBackend
from genblaze_core.storage.types import FileEntry, ListPage

from reprise.embed import HashEmbedder, prompt_fingerprint
from reprise.library import B2Library
from tests.test_ingest import manifest_dict, rehash


class MemoryBackend(StorageBackend):
    """Minimal in-memory StorageBackend for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: Any, *, content_type: str | None = None,
            metadata: dict[str, str] | None = None,
            extra_args: dict[str, Any] | None = None) -> str:
        self.objects[key] = data if isinstance(data, bytes) else data.read()
        return key

    def get(self, key: str) -> bytes:
        return self.objects[key]

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
