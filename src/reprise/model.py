"""Core domain types for Reprise.

Reprise sits in front of a generative-media pipeline and answers one question:
"do we already own something that satisfies this request?"

The vocabulary here is deliberately small and provider-agnostic. A `Request` is
what someone is about to spend money on. A `LibraryEntry` is something a prior
run already produced and paid for. A `Decision` is the answer, and it always
carries its own justification so a reuse can be audited after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Verdict(StrEnum):
    """What Reprise decided to do with a request."""

    # An existing asset satisfies the request. Nothing is generated, nothing is spent.
    REUSE = "reuse"
    # Nothing in the library is close enough. Hand off to the Genblaze pipeline.
    GENERATE = "generate"
    # Something is close but not close enough to serve automatically. A human picks.
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class Request:
    """A generation someone is about to pay for."""

    prompt: str
    modality: str = "image"
    # Constraints that a candidate MUST satisfy to be substitutable at all.
    # Kept separate from the prompt because they are hard filters, not similarity
    # signals: a 16:9 asset never satisfies a 1:1 request no matter how close the
    # prompt text is.
    aspect_ratio: str | None = None
    style: str | None = None

    def constraint_key(self) -> tuple[str, str | None, str | None]:
        """The hard-filter identity a candidate must match exactly."""
        return (self.modality, self.aspect_ratio, self.style)


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    """An asset a previous run already generated, paid for, and stored in B2."""

    asset_id: str
    prompt: str
    modality: str
    # SHA-256 of the stored bytes. Populated by Genblaze's ObjectStorageSink.
    sha256: str
    # Storage key in the B2 bucket (not a presigned URL -- those rotate and must
    # never be persisted; see genblaze docs/features/object-storage.md).
    storage_key: str
    # What this asset originally cost to produce, from the Genblaze step ledger.
    cost_usd: float
    provider: str
    model: str
    run_id: str
    created_at: datetime
    aspect_ratio: str | None = None
    style: str | None = None
    # Optional dense vector of the prompt, used for near-match. Absent entries
    # can still be matched exactly.
    embedding: tuple[float, ...] | None = None

    def constraint_key(self) -> tuple[str, str | None, str | None]:
        return (self.modality, self.aspect_ratio, self.style)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A library entry scored against a request."""

    entry: LibraryEntry
    similarity: float
    # True when the request prompt is byte-identical to the entry prompt after
    # normalization. An exact match needs no threshold judgement.
    exact: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    """The answer, plus enough context to audit it later."""

    verdict: Verdict
    request: Request
    # The winning candidate for REUSE/REVIEW; None for GENERATE.
    candidate: Candidate | None = None
    # Money not spent because this request was served from the library. Always
    # 0.0 for GENERATE and REVIEW -- a review has not saved anything yet.
    saved_usd: float = 0.0
    # Human-readable justification, written into the decision ledger.
    reason: str = ""
    # Runners-up, retained so a REVIEW can offer real choices.
    alternatives: tuple[Candidate, ...] = field(default_factory=tuple)
