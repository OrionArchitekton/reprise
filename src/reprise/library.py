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
from genblaze_core.storage.errors import StorageError, StorageErrorCode

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
        vector_cache_max: int = 2048,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backend = backend
        self._prefix = prefix.rstrip("/")
        self.last_scan_skipped: list[str] = []
        self.last_scan_unreadable: list[str] = []
        self._scan_cache_sec = scan_cache_sec
        self._clock = clock or time.monotonic
        self._cached: tuple[float, list[LibraryEntry]] | None = None
        # (embedder, fingerprint) -> vector. A sidecar is content-addressed by
        # the fingerprint of the normalized prompt and written once, so it can
        # be remembered for the life of the process without a staleness window
        # (unlike the scan cache, which projects a bucket that grows). Bounded
        # so a long-lived instance serving many distinct prompts cannot grow
        # this without limit.
        self._vectors: dict[tuple[str, str], tuple[float, ...]] = {}
        self._vector_cache_max = vector_cache_max

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
        if not self.last_scan_unreadable:
            # Only a COMPLETE projection is worth remembering. Caching one built
            # while objects were unreadable makes the next request reuse that
            # incompleteness instead of retrying, and because the cache-hit path
            # returns before `last_scan_unreadable` is reset, readiness keeps
            # reporting degraded and the gateway keeps refusing for the whole
            # window AFTER storage recovers. Observed in production 2026-07-27:
            # the B2 cap was raised, reads worked, and /readyz stayed 503.
            # Refusing while the read is failing is correct; staying refused
            # once it works is an outage of our own making.
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
                memo = self._vectors.get((embedder_name, fp))
                if memo is None:
                    memo = self._load_or_create_sidecar(
                        fp, entry.prompt, embedder, embedder_name
                    )
                    self._remember(embedder_name, fp, memo)
                vectors[fp] = memo
            out.append(dataclasses.replace(entry, embedding=vectors[fp]))
        return out

    def _read_sidecar(self, key: str) -> bytes | None:
        """The stored vector bytes, or None when storage is SURE there is none.

        Asking `exists()` first cost a second billed transaction AND could not
        answer the question: genblaze-s3 reports 403/AccessDenied as "does not
        exist" (least-privilege keys get 403 for HEAD on absent keys), and a B2
        transaction cap denies reads with exactly that. So a capped bucket read
        as an empty cache, and the caller's response to an empty cache is to
        pay for a new embedding and write it -- per prompt, per request, with
        nothing in the response saying anything was wrong. Only a typed
        NOT_FOUND is absence; every other failure is refused upward, because a
        storage failure is never a fact about the business.
        """
        try:
            # Annotated: the package's lazy export surface types backend
            # methods as Any (genblaze #55), and Any would silently propagate.
            raw: bytes = self._backend.get(key)
            return raw
        except StorageError as e:
            if e.error_code == StorageErrorCode.NOT_FOUND:
                return None
            raise

    def _remember(self, embedder_name: str, fp: str, vector: tuple[float, ...]) -> None:
        if self._vector_cache_max <= 0:
            return  # 0 disables the memo, so a test can price the uncached path
        while len(self._vectors) >= self._vector_cache_max:
            # Insertion-ordered: drop the oldest. Eviction only costs a re-read,
            # never correctness, so the simplest policy is the right one here.
            self._vectors.pop(next(iter(self._vectors)))
        self._vectors[(embedder_name, fp)] = vector

    def _load_or_create_sidecar(
        self, fp: str, prompt: str, embedder: Embedder, embedder_name: str
    ) -> tuple[float, ...]:
        key = f"{self._prefix}/embeddings/{fp}.json"
        raw = self._read_sidecar(key)
        if raw is not None:
            doc = json.loads(raw)
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
