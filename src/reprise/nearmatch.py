"""Near-match reuse: serving a request from an asset whose prompt is close but
not identical.

Slice 1 (`decide.py`) handles the case that needs no judgement: same prompt, same
constraints. This module handles the case that pays for itself far more often --
"a red bicycle against a white wall" when the library holds "a red bicycle on a
white background" -- and which carries all of the risk.

## The economics

Every request is one of four outcomes:

    reuse a genuinely equivalent asset   -> saved the generation cost. The win.
    generate because nothing fit         -> correct, costs what it always cost.
    generate when we DID own a match     -> a miss. Costs money, harms nobody.
    reuse an asset that does NOT fit     -> a FALSE REUSE. Ships wrong creative.

Those last two are not symmetric. A miss costs cents. A false reuse puts the
wrong image in front of a customer, and it is silent -- nobody reviews an asset
they believe they already approved. Reprise is therefore deliberately biased
toward generating.

## What similarity does and does not mean

`similarity` here is cosine similarity between embeddings of the two prompts,
after the hard constraint filter has already run. It measures how alike the two
REQUESTS read, not how alike the two IMAGES look. Two prompts differing only by
"red" and "blue" score very high and produce completely different assets, which
is exactly the failure mode the acceptance policy has to survive.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from reprise.decide import _rank, normalize_prompt, substitutable
from reprise.model import Candidate, Decision, LibraryEntry, Request, Verdict

# The acceptance lines (operator decision, 2026-07-26): auto-serve at or above
# AUTO_REUSE_THRESHOLD, queue a human review down to REVIEW_THRESHOLD, generate
# below that. The known cost of the bolder auto line -- attribute swaps such as
# "red" vs "blue" can score above it -- is measured by the eval set and
# disclosed in the README, never hidden.
AUTO_REUSE_THRESHOLD = 0.97
REVIEW_THRESHOLD = 0.85


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, clamped to [0.0, 1.0].

    Returns 0.0 for a zero-magnitude vector rather than raising: an un-embedded
    entry should fall out of near-matching quietly, not crash the request.
    """
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def score_candidates(
    request: Request,
    request_embedding: Sequence[float],
    library: Iterable[LibraryEntry],
) -> list[Candidate]:
    """Score every substitutable library entry against the request.

    Applies the hard constraint filter first, then scores only the survivors.
    Entries with no stored embedding are skipped rather than scored as 0.0, so a
    partially-embedded library degrades to exact-match behaviour instead of
    silently reporting everything as dissimilar.
    """
    wanted = normalize_prompt(request.prompt)
    scored: list[Candidate] = []
    for e in library:
        if not substitutable(request, e):
            continue
        if normalize_prompt(e.prompt) == wanted:
            scored.append(Candidate(entry=e, similarity=1.0, exact=True))
            continue
        if e.embedding is None:
            continue
        scored.append(
            Candidate(
                entry=e,
                similarity=cosine(request_embedding, e.embedding),
                exact=False,
            )
        )
    return _rank(scored)


def classify(request: Request, candidates: Sequence[Candidate]) -> Decision:
    """Turn scored candidates into a REUSE / REVIEW / GENERATE decision.

    `candidates` must arrive ranked best-first (`score_candidates` output).
    An exact match short-circuits the thresholds. A REVIEW saves nothing:
    `saved_usd` counts only money a human (or the exact/auto path) has actually
    agreed was saved, so the scoreboard the judges read is never inflated by
    unaccepted reviews.
    """
    if not candidates:
        return Decision(
            verdict=Verdict.GENERATE,
            request=request,
            reason="no substitutable asset in the library",
        )

    winner, *rest = candidates
    alternatives = tuple(rest)
    sim = winner.similarity

    if winner.exact:
        verdict, saved = Verdict.REUSE, winner.entry.cost_usd
        reason = (
            f"exact prompt match against run {winner.entry.run_id} "
            f"({winner.entry.provider}/{winner.entry.model})"
        )
    elif sim >= AUTO_REUSE_THRESHOLD:
        verdict, saved = Verdict.REUSE, winner.entry.cost_usd
        reason = (
            f"similarity {sim:.2f} >= auto-reuse line {AUTO_REUSE_THRESHOLD}: "
            f"serving {winner.entry.asset_id} from run {winner.entry.run_id}"
        )
    elif sim >= REVIEW_THRESHOLD:
        verdict, saved = Verdict.REVIEW, 0.0
        reason = (
            f"similarity {sim:.2f} in review band "
            f"[{REVIEW_THRESHOLD}, {AUTO_REUSE_THRESHOLD}): human decides; "
            f"accepting would save ${winner.entry.cost_usd:.2f}"
        )
    else:
        return Decision(
            verdict=Verdict.GENERATE,
            request=request,
            reason=f"best similarity {sim:.2f} below review line {REVIEW_THRESHOLD}",
        )

    return Decision(
        verdict=verdict,
        request=request,
        candidate=winner,
        saved_usd=saved,
        reason=reason,
        alternatives=alternatives,
    )
