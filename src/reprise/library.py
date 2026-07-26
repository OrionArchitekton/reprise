"""The B2-backed asset library.

A `B2Library` is a *view*, not a database: it projects the provenance manifests
that Genblaze's ObjectStorageSink already writes under ``{prefix}/manifests/``
into `LibraryEntry` rows (via `ingest`), and attaches prompt embeddings cached
as sidecar objects under ``{prefix}/embeddings/{fingerprint}.json``.

Sidecars are keyed by the sha256 of the NORMALIZED prompt, so:

* embedding is idempotent -- rescanning never re-embeds a known prompt;
* identical prompts across runs share one vector (and one API call, ever);
* the cache is provider-agnostic -- the sidecar records which embedder wrote
  it, and mixing embedders is refused at read time rather than silently
  comparing vectors from different spaces.

Corrupt manifests are skipped, not fatal: a shared bucket will accumulate
objects Reprise did not write. Skips are recorded on `last_scan_skipped` so
the UI can surface them instead of pretending the bucket was clean.
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable, Sequence

from genblaze_core import StorageBackend

from reprise.embed import Embedder, prompt_fingerprint
from reprise.ingest import entries_from_manifest
from reprise.model import LibraryEntry

SIDECAR_SCHEMA = 1


class B2Library:
    """Scan manifests and manage embedding sidecars in one bucket prefix."""

    def __init__(
        self,
        backend: StorageBackend,
        *,
        prefix: str = "reprise",
        scan_cache_sec: float = 120.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backend = backend
        self._prefix = prefix.rstrip("/")
        self.last_scan_skipped: list[str] = []
        self.last_scan_unreadable: list[str] = []
        self._scan_cache_sec = scan_cache_sec
        self._clock = clock or time.monotonic
        self._cached: tuple[float, list[LibraryEntry]] | None = None

    # -- scanning ----------------------------------------------------------

    def invalidate(self) -> None:
        """Drop the cached projection: something was added to the bucket."""
        self._cached = None

    def scan(self) -> list[LibraryEntry]:
        """Project every readable manifest in the bucket into entries.

        Cached for `scan_cache_sec`. Reading every manifest object on every
        request is O(library) BILLED transactions per request: it grows with
        the library and tripped the account's Class B cap in production
        (2026-07-26), after which every path that touched storage failed. The
        cache is per process, so a cold instance still pays a full scan, and a
        write invalidates it so a new asset is never invisible to the next
        request. A persisted index is the real fix at scale; ParquetSink is the
        natural seed.
        """
        if self._cached is not None:
            stamped, cached = self._cached
            if self._clock() - stamped < self._scan_cache_sec:
                return cached
        self.last_scan_skipped = []
        self.last_scan_unreadable = []
        entries: list[LibraryEntry] = []
        token: str | None = None
        while True:
            page = self._backend.list(
                f"{self._prefix}/manifests/", continuation_token=token
            )
            for fe in page.entries:
                try:
                    raw = self._backend.get(fe.key)
                except Exception:
                    # Storage could not serve the object. That is a property of
                    # the STORE, not of this object, so it is tracked
                    # separately: a caller deciding whether to spend money must
                    # know the projection is incomplete.
                    self.last_scan_unreadable.append(fe.key)
                    continue
                try:
                    entries.extend(entries_from_manifest(json.loads(raw)))
                except Exception:
                    # A corrupt or foreign object must not take down the scan;
                    # it is recorded and surfaced, never silently dropped. The
                    # object was READ fine, so the projection is still complete
                    # with respect to everything this bucket actually holds.
                    self.last_scan_skipped.append(fe.key)
            token = page.next_token
            if token is None:
                break
        self._cached = (self._clock(), entries)
        return entries

    # -- embeddings --------------------------------------------------------

    def ensure_embeddings(
        self, entries: Sequence[LibraryEntry], embedder: Embedder
    ) -> list[LibraryEntry]:
        """Attach a vector to every entry, embedding only cache misses.

        Returns new LibraryEntry objects (entries are frozen). One sidecar per
        distinct normalized prompt: N copies of a prompt cost one API call.
        """
        embedder_name = type(embedder).__name__
        vectors: dict[str, tuple[float, ...]] = {}
        out: list[LibraryEntry] = []
        for entry in entries:
            fp = prompt_fingerprint(entry.prompt)
            if fp not in vectors:
                vectors[fp] = self._load_or_create_sidecar(
                    fp, entry.prompt, embedder, embedder_name
                )
            out.append(dataclasses.replace(entry, embedding=vectors[fp]))
        return out

    def _load_or_create_sidecar(
        self, fp: str, prompt: str, embedder: Embedder, embedder_name: str
    ) -> tuple[float, ...]:
        key = f"{self._prefix}/embeddings/{fp}.json"
        if self._backend.exists(key):
            doc = json.loads(self._backend.get(key))
            if doc.get("embedder") != embedder_name:
                # Vectors from different embedders live in different spaces;
                # comparing them yields garbage similarities. Fail loudly.
                raise ValueError(
                    f"sidecar {key} was written by {doc.get('embedder')!r}, "
                    f"current embedder is {embedder_name!r}; re-embed the "
                    "library rather than mixing vector spaces"
                )
            return tuple(float(x) for x in doc["vector"])
        vector = embedder.embed(prompt)
        self._backend.put(
            key,
            json.dumps(
                {
                    "schema": SIDECAR_SCHEMA,
                    "embedder": embedder_name,
                    "fingerprint": fp,
                    "vector": list(vector),
                }
            ).encode(),
            content_type="application/json",
        )
        return vector
