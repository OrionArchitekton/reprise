"""The decision ledger: every REUSE / REVIEW / GENERATE, written to B2.

Reprise's savings claim is only as credible as its audit trail. Each decision
is one immutable JSON object under ``{prefix}/ledger/``; when the backend
supports Object Lock (the bucket was created with it enabled), each record is
written with GOVERNANCE retention so it cannot be deleted or overwritten for
the retention window -- the scoreboard can then be recomputed by anyone from
objects nobody could have quietly edited.

Design notes:

* One object per decision, never appended in place: S3-style stores have no
  atomic append, and object-locking an ever-rewritten JSONL would be
  meaningless. Keys are ``{utc timestamp}-{seq}-{prompt fingerprint[:8]}``,
  so listings sort chronologically for free.
* The scoreboard (`summarize`) is DERIVED state: recomputed from the ledger
  objects on read, cheap at demo scale. Nothing caches a number that the
  ledger cannot back.
* ``saved_usd`` sums only what decisions actually saved (exact/auto REUSE, or
  a REVIEW a human later accepted -- acceptance writes a new ledger record
  rather than mutating the original decision).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from genblaze_core.storage.base import ObjectLockConfig, StorageBackend

from reprise.embed import prompt_fingerprint
from reprise.model import Decision, Verdict

LEDGER_SCHEMA = 1
log = logging.getLogger("reprise.ledger")


@dataclass(frozen=True, slots=True)
class Scoreboard:
    """Totals recomputed from the ledger; nothing here is cached state."""

    reuses: int = 0
    reviews: int = 0
    generates: int = 0
    accepts: int = 0
    saved_usd: float = 0.0

    @property
    def decisions(self) -> int:
        return self.reuses + self.reviews + self.generates


def _fold(base: Scoreboard, docs: list[dict[str, Any]]) -> Scoreboard:
    """Add records to a running total. The one place a record is scored."""
    reuses, reviews = base.reuses, base.reviews
    generates, accepts = base.generates, base.accepts
    saved = base.saved_usd
    for doc in docs:
        kind = doc.get("kind")
        if kind in ("reserve_generate", "reserve_embed"):
            continue  # intents, not outcomes: never scored
        if kind == "accept":
            accepts += 1
            saved += float(doc.get("saved_usd", 0.0))
            continue
        v = doc.get("verdict")
        if v == Verdict.REUSE.value:
            reuses += 1
            saved += float(doc.get("saved_usd", 0.0))
        elif v == Verdict.REVIEW.value:
            reviews += 1
        elif v == Verdict.GENERATE.value:
            generates += 1
    return Scoreboard(
        reuses=reuses, reviews=reviews, generates=generates,
        accepts=accepts, saved_usd=round(saved, 6),
    )


class Ledger:
    def __init__(
        self,
        backend: StorageBackend,
        *,
        prefix: str = "reprise",
        lock: ObjectLockConfig | None = None,
        retain_days: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._backend = backend
        self._prefix = prefix.rstrip("/")
        self._lock = lock
        self._retain_days = retain_days
        self._clock = clock or (lambda: datetime.now(UTC))
        self._seq = 0
        self._snapshot_key = f"{self._prefix}/index/scoreboard.json"

    @property
    def retention(self) -> tuple[str, int | None]:
        """(mode, days) actually in force for new writes.

        Read from the same state `_lock_for_write` uses, so the UI cannot
        advertise an object-locked ledger that this instance is not writing.
        """
        if self._retain_days is not None:
            return ("GOVERNANCE", self._retain_days)
        if self._lock is not None:
            return ("GOVERNANCE", None)
        return ("none", None)

    # -- writes ------------------------------------------------------------

    def record(self, decision: Decision) -> str:
        """Write one decision; returns the ledger key."""
        doc: dict[str, Any] = {
            "schema": LEDGER_SCHEMA,
            "kind": "decision",
            "ts": self._clock().isoformat(),
            "verdict": decision.verdict.value,
            "prompt": decision.request.prompt,
            "modality": decision.request.modality,
            "aspect_ratio": decision.request.aspect_ratio,
            "style": decision.request.style,
            "saved_usd": decision.saved_usd,
            "reason": decision.reason,
            "alternatives": len(decision.alternatives),
        }
        if decision.candidate is not None:
            e = decision.candidate.entry
            doc["candidate"] = {
                "asset_id": e.asset_id,
                "run_id": e.run_id,
                "sha256": e.sha256,
                "storage_key": e.storage_key,
                "similarity": decision.candidate.similarity,
                "exact": decision.candidate.exact,
                "cost_usd": e.cost_usd,
            }
        return self._write(doc, decision.request.prompt)

    def record_accept(self, decision: Decision, *, review_id: str = "") -> str:
        """A human accepted a REVIEW: the saving becomes real, as a NEW record.

        The original decision object stays untouched (it may be object-locked);
        acceptance is its own event, carrying the money that became saved.
        """
        if decision.verdict is not Verdict.REVIEW or decision.candidate is None:
            raise ValueError("record_accept requires a REVIEW decision with a candidate")
        doc: dict[str, Any] = {
            "schema": LEDGER_SCHEMA,
            "kind": "accept",
            "ts": self._clock().isoformat(),
            "prompt": decision.request.prompt,
            # Names the offer this acceptance answers, so the ledger itself is
            # the record of which offers are already spent.
            "review_id": review_id,
            "saved_usd": decision.candidate.entry.cost_usd,
            "candidate": {
                "asset_id": decision.candidate.entry.asset_id,
                "run_id": decision.candidate.entry.run_id,
                "similarity": decision.candidate.similarity,
            },
        }
        return self._write(doc, decision.request.prompt)

    def _write(self, doc: dict[str, Any], prompt: str) -> str:
        self._seq += 1
        now = self._clock()
        ts = now.strftime("%Y%m%dT%H%M%S.%fZ")
        # Date and kind ride in the KEY, so the daily cap check is a listing
        # rather than a read of every record. Reading each object to find its
        # kind cost one paid Class B transaction per record per request, which
        # grew with the ledger and tripped Backblaze's transaction cap in
        # production (2026-07-26): the app fell to its fail-closed path and
        # stopped answering. Listing is one call per kind, whatever the size.
        day = now.strftime("%Y%m%d")
        kind = str(doc.get("kind", "decision"))
        # uuid4 suffix, not just the per-instance counter: on serverless every
        # instance starts its counter at 1, so two instances recording the same
        # prompt in the same microsecond would collide and silently lose a
        # record (and with it, a unit of the rate limiter's count).
        nonce = uuid.uuid4().hex[:8]
        key = (
            f"{self._prefix}/ledger/{day}/{kind}/{ts}-{self._seq:06d}-"
            f"{prompt_fingerprint(prompt)[:8]}-{nonce}.json"
        )
        data = json.dumps(doc, sort_keys=True).encode()
        lock = self._lock_for_write()
        if lock is not None:
            # genblaze-s3 extends put() with a first-class object_lock kwarg;
            # portable backends without it simply are not lockable ledgers.
            self._backend.put(  # type: ignore[call-arg]
                key, data, content_type="application/json", object_lock=lock
            )
        else:
            self._backend.put(key, data, content_type="application/json")
        return key

    def _lock_for_write(self) -> ObjectLockConfig | None:
        """Build the retention horizon for THIS write.

        A config built once at construction ages with the process: a warm
        serverless instance keeps writing records whose retain_until was
        measured from boot, and past the window it writes no real protection at
        all while the UI still advertises an object-locked ledger. Measuring
        from each write makes the horizon a property of the record.
        """
        if self._retain_days is not None:
            return ObjectLockConfig(
                retain_until=self._clock() + timedelta(days=self._retain_days)
            )
        return self._lock

    def reserve_spend(self, request_prompt: str, kind: str) -> str:
        """Book an intent to spend BEFORE the money leaves.

        The cap counts ledger records, so a record written only after a
        successful generation makes the counter fail OPEN: a generation that
        succeeds but whose ledger write fails costs money that is never
        counted, and the counter can freeze while `generation_available` stays
        true forever. Reserving first inverts that: the spend is counted even
        if everything downstream fails, and a reservation write that fails
        propagates (the caller must treat it as cap-exhausted, never as
        permission to spend).

        Reservations are their own `kind` so the audit trail distinguishes
        "we intended to spend" from "we did spend and here is the asset".
        """
        return self._write(
            {
                "schema": LEDGER_SCHEMA,
                "kind": kind,
                "ts": self._clock().isoformat(),
                "prompt": request_prompt,
            },
            request_prompt,
        )

    # -- reads -------------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        """Every ledger record, oldest first (keys sort chronologically)."""
        out: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            page = self._backend.list(f"{self._prefix}/ledger/", continuation_token=token)
            for fe in page.entries:
                out.append(json.loads(self._backend.get(fe.key)))
            token = page.next_token
            if token is None:
                break
        return out

    def spend_reservations_today(self, kinds: tuple[str, ...]) -> int:
        """Count today's spend reservations (the cap's source of truth).

        Counts KEYS under `{prefix}/ledger/{today}/{kind}/`, so the cost is one
        listing per kind instead of a read of every record ever written.
        Records written before this layout live at the flat `ledger/` root and
        are not counted here: they are yesterday's usage by the time it
        matters, and undercounting a past day cannot let today overspend.
        """
        day = self._clock().strftime("%Y%m%d")
        total = 0
        for kind in kinds:
            token: str | None = None
            while True:
                page = self._backend.list(
                    f"{self._prefix}/ledger/{day}/{kind}/", continuation_token=token
                )
                total += len(page.entries)
                token = page.next_token
                if token is None:
                    break
        return total

    def accepted_review_ids(self) -> set[str]:
        """Which review offers have already been spent.

        The ledger is the store: an acceptance is only real once its record is
        written, so asking the ledger is asking the same source the scoreboard
        is computed from, with no second database to fall out of sync. This is
        still read-then-act, so two simultaneous accepts of one offer can both
        pass; the check bounds replay, it does not serialize it.

        Only the accept partitions are read, not the whole ledger: acceptances
        are rare, and reading every decision to find them was part of what
        exhausted the account's transaction cap. Records written before the
        partitioned layout predate `review_id` entirely, so they cannot name an
        offer and cannot collide with one.
        """
        ids: set[str] = set()
        for key in self._ledger_keys():
            if "/accept/" not in key:
                continue
            try:
                doc = json.loads(self._backend.get(key))
            except Exception as e:
                # An unreadable accept record means we cannot prove this offer
                # is unspent, and the caller treats that as a refusal.
                raise RuntimeError(f"accept history unreadable at {key}: {e}") from e
            if doc.get("review_id"):
                ids.add(str(doc["review_id"]))
        return ids

    def _ledger_keys(self) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            page = self._backend.list(f"{self._prefix}/ledger/", continuation_token=token)
            keys.extend(fe.key for fe in page.entries)
            token = page.next_token
            if token is None:
                break
        return keys

    def _day_of(self, key: str) -> str:
        """The partition day a ledger key belongs to.

        Keys written before the date/kind partition sit at the flat root; they
        are treated as the earliest possible day so they fold into the first
        snapshot and are never re-read.
        """
        rest = key[len(f"{self._prefix}/ledger/") :]
        head = rest.split("/", 1)[0]
        return head if len(head) == 8 and head.isdigit() else "00000000"

    def _load_snapshot(self) -> tuple[str, Scoreboard]:
        try:
            doc = json.loads(self._backend.get(self._snapshot_key))
            if int(doc.get("schema", 0)) != LEDGER_SCHEMA:
                return ("", Scoreboard())
            t = doc["totals"]
            return (
                str(doc["through_day"]),
                Scoreboard(
                    reuses=int(t["reuses"]),
                    reviews=int(t["reviews"]),
                    generates=int(t["generates"]),
                    accepts=int(t["accepts"]),
                    saved_usd=float(t["saved_usd"]),
                ),
            )
        except Exception:
            # No snapshot, or one this version cannot read: recompute from the
            # ledger. The snapshot is a cache of immutable history, never the
            # authority, so losing it costs reads and nothing else.
            return ("", Scoreboard())

    def summarize(self) -> Scoreboard:
        """Totals over the whole ledger, reading only what can still change.

        Completed days are immutable, so they are folded once into a snapshot
        object and never read again; today is always recomputed live. Reading
        every record on every call cost O(history) BILLED reads per cold
        instance and grew without bound, which is how the account's transaction
        cap was reached (docs/solutions/2026-07-26-b2-class-b-transaction-cap.md).
        The ledger remains the authority: delete the snapshot and the next call
        rebuilds it.
        """
        today = self._clock().strftime("%Y%m%d")
        through, base = self._load_snapshot()
        pending: dict[str, list[str]] = {}
        for key in self._ledger_keys():
            day = self._day_of(key)
            if day <= through:
                continue
            pending.setdefault(day, []).append(key)

        closed_days = sorted(d for d in pending if d < today)
        board = base
        for day in [*closed_days, *(d for d in sorted(pending) if d >= today)]:
            docs = [json.loads(self._backend.get(k)) for k in pending[day]]
            board = _fold(board, docs)
            if day == (closed_days[-1] if closed_days else None):
                self._write_snapshot(day, board)
        return board

    def _write_snapshot(self, through_day: str, board: Scoreboard) -> None:
        """Persist totals through a day that can no longer change.

        Never covers today: freezing a day still being written would stop the
        scoreboard moving. Written without a lock, because a cache that cannot
        be replaced is a liability, not a guarantee.
        """
        try:
            self._backend.put(
                self._snapshot_key,
                json.dumps(
                    {
                        "schema": LEDGER_SCHEMA,
                        "through_day": through_day,
                        "totals": {
                            "reuses": board.reuses,
                            "reviews": board.reviews,
                            "generates": board.generates,
                            "accepts": board.accepts,
                            "saved_usd": board.saved_usd,
                        },
                    }
                ).encode(),
                content_type="application/json",
            )
        except Exception as e:  # a cache write must never fail a read
            log.warning("scoreboard snapshot write failed: %s", e)

