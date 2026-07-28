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
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from genblaze_core import StorageBackend
from genblaze_core.storage.errors import StorageError, StorageErrorCode

from reprise.embed import Embedder, prompt_fingerprint
from reprise.ingest import entries_from_manifest
from reprise.model import LibraryEntry

SIDECAR_SCHEMA = 1
INDEX_SCHEMA = 1

log = logging.getLogger(__name__)

# The index round-trips LibraryEntry through JSON. Written out field by field
# rather than by reflection so that adding a field to the model cannot silently
# start emitting it into a signed public object.
_INDEX_FIELDS = (
    "asset_id",
    "prompt",
    "modality",
    "sha256",
    "storage_key",
    "cost_usd",
    "provider",
    "model",
    "run_id",
    "aspect_ratio",
    "style",
    "manifest_hash",
)


def _row_from_entry(e: LibraryEntry) -> dict[str, Any]:
    row: dict[str, Any] = {f: getattr(e, f) for f in _INDEX_FIELDS}
    row["created_at"] = e.created_at.isoformat()
    return row


def _entry_from_row(row: dict[str, Any]) -> LibraryEntry:
    return LibraryEntry(
        created_at=datetime.fromisoformat(row["created_at"]),
        **{f: row[f] for f in _INDEX_FIELDS},
    )


class B2Library:
    """Scan manifests and manage embedding sidecars in one bucket prefix."""

    def __init__(
        self,
        backend: StorageBackend,
        *,
        prefix: str = "reprise",
        scan_cache_sec: float = 120.0,
        vector_cache_max: int = 2048,
        index_secret: bytes = b"",
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
        # Signs the persisted projection. Empty means the index is neither
        # written nor trusted and every instance scans, which is exactly the
        # behaviour before the index existed: slower, never wrong.
        self._index_secret = index_secret
        self._index_key = f"{self._prefix}/index/library.json"
        self._cached_stamp: str | None = None
        # Which embedder last populated the vector memo, so a published index
        # names the vector space it carries rather than guessing one.
        self._last_embedder_name = ""

    # -- scanning ----------------------------------------------------------

    def invalidate(self) -> None:
        """Drop the cached projection: something was added to the bucket."""
        self._cached = None

    def scan(self) -> list[LibraryEntry]:
        """The current projection, at the lowest read cost that is still correct.

        Three tiers, cheapest first:

        1. One LISTING of the index key. B2 bills listings as Class C, the
           cheap class. If the stamp matches what this process last saw, the
           local projection is current and nothing is read at all. This is also
           what makes the cache safe ACROSS instances: a peer that publishes an
           index changes the stamp, so nobody keeps answering from a library
           that no longer reflects the bucket.
        2. One GET of the signed index. A cold instance pays two round trips
           instead of one per manifest plus one per sidecar. That difference
           was measured at 15.3 seconds against 2 milliseconds on a warm
           process, which is what a first visitor was waiting through.
        3. The manifests themselves, when there is no index or it cannot be
           trusted, and the result is then published for everyone else.

        Every tier falls through to the next, so a missing, stale, corrupt or
        unsigned index costs reads and never correctness. The manifests remain
        the authority; the index is only ever a cache of them.
        """
        try:
            stamp = self._index_stamp()
        except Exception:
            stamp = None  # listing failed; fall through and read for real
        if self._cached is not None:
            stamped, cached = self._cached
            # An UNCHANGED stamp keeps the cache; a changed one drops it. Both
            # being None is the index-disabled case, where this degrades to the
            # plain time cache rather than to a full scan per request.
            if stamp == self._cached_stamp and self._clock() - stamped < self._scan_cache_sec:
                return cached

        self.last_scan_skipped = []
        self.last_scan_unreadable = []
        entries = self._load_index()
        if entries is None:
            entries = self._full_scan()
            if not self.last_scan_unreadable:
                self._write_index(entries, self._last_embedder_name)
                try:
                    stamp = self._index_stamp()
                except Exception:
                    stamp = None
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
            self._cached_stamp = stamp
        return entries

    def _full_scan(self) -> list[LibraryEntry]:
        """Read every manifest. The authority, and the expensive path."""
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
        return entries

    # -- the persisted index ------------------------------------------------

    def _index_signature(self, doc: dict[str, Any]) -> str:
        """HMAC over the index payload, order-independent of JSON formatting."""
        body = json.dumps(
            {k: doc[k] for k in ("schema", "embedder", "entries", "vectors")},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hmac.new(self._index_secret, body.encode(), hashlib.sha256).hexdigest()

    def _index_stamp(self) -> str | None:
        """A cheap token that changes when the index does, or None if absent.

        This is a LISTING, which B2 bills as Class C, the cheap class, and it is
        what lets one instance notice that another wrote the index. Without it
        the projection cache is per process: an instance that generates an asset
        tells nobody, and a peer keeps answering from a library that does not
        contain it yet, paying to generate the same prompt again.
        """
        if not self._index_secret:
            return None  # index disabled: do not pay for a listing to learn that
        page = self._backend.list(self._index_key, max_keys=1)
        for fe in page.entries:
            if fe.key == self._index_key:
                return f"{fe.etag}:{fe.size}"
        return None

    def _load_index(self) -> list[LibraryEntry] | None:
        """The persisted projection, or None if it cannot be trusted.

        None always means "fall back to reading the manifests", so a missing,
        corrupt, foreign or unsigned index costs reads and never correctness.
        The index is a cache of objects that remain the authority; it is signed
        for the same reason the scoreboard snapshot is, because a shared bucket
        accumulates objects this app did not write.
        """
        if not self._index_secret:
            return None
        try:
            doc = json.loads(self._backend.get(self._index_key))
        except Exception:
            return None
        try:
            if int(doc.get("schema", 0)) != INDEX_SCHEMA:
                return None
            if not hmac.compare_digest(
                str(doc.get("sig", "")), self._index_signature(doc)
            ):
                return None
            entries = [_entry_from_row(r) for r in doc["entries"]]
        except Exception:
            return None
        embedder_name = str(doc.get("embedder", ""))
        for fp, vec in doc.get("vectors", {}).items():
            self._remember(embedder_name, fp, tuple(float(x) for x in vec))
        return entries

    def _write_index(self, entries: list[LibraryEntry], embedder_name: str) -> None:
        """Publish the projection so no other instance has to rebuild it.

        Carries the vectors too. Leaving them out would still make a cold
        instance read one sidecar per distinct prompt, which is the same
        O(library) round trip the index exists to remove.
        """
        if not self._index_secret:
            return
        vectors = {
            fp: list(vec)
            for (name, fp), vec in self._vectors.items()
            if name == embedder_name
        }
        doc: dict[str, Any] = {
            "schema": INDEX_SCHEMA,
            "embedder": embedder_name,
            "entries": [_row_from_entry(e) for e in entries],
            "vectors": vectors,
        }
        doc["sig"] = self._index_signature(doc)
        try:
            self._backend.put(
                self._index_key,
                json.dumps(doc).encode(),
                content_type="application/json",
            )
        except Exception as e:  # an index write must never fail a request
            log.warning("library index write failed: %s", e)

    def refresh_index(self, embedder: Embedder) -> None:
        """Re-read the manifests and republish the index.

        Called after this instance changes the bucket. A generate makes the
        published index stale, and the stamp only tells a peer that something
        changed, so the instance that did the writing owes everyone a rebuild.
        """
        self.invalidate()
        entries = self._full_scan()
        if self.last_scan_unreadable:
            return  # never publish a projection known to be incomplete
        entries = self.ensure_embeddings(entries, embedder)
        self._write_index(entries, type(embedder).__name__)

    def probe(self) -> None:
        """One listing and one real object read. Never cached, constant cost.

        Readiness used to call `scan()`, which answers from the per-process
        cache, so once that cache was warm the probe reported ready for the
        whole window regardless of what storage was doing. That is precisely
        the shape of the Class B outage the probe exists to catch: listings
        kept working, object reads did not, and readiness stayed green.

        Cost does not grow with the library either, where a cold `scan()` reads
        every manifest. Raises whatever the backend raises; the caller decides
        what a failure means.
        """
        page = self._backend.list(f"{self._prefix}/manifests/", max_keys=1)
        if not page.entries:
            return  # an empty library is readable, it is just empty
        self._backend.get(page.entries[0].key)

    # -- embeddings --------------------------------------------------------

    def ensure_embeddings(
        self, entries: Sequence[LibraryEntry], embedder: Embedder
    ) -> list[LibraryEntry]:
        """Attach a vector to every entry, embedding only cache misses.

        Returns new LibraryEntry objects (entries are frozen). One sidecar per
        distinct normalized prompt: N copies of a prompt cost one API call.
        """
        embedder_name = type(embedder).__name__
        self._last_embedder_name = embedder_name
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
