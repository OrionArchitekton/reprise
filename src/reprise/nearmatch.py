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
from reprise.model import Candidate, Decision, LibraryEntry, Request


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


# ---------------------------------------------------------------------------
# TODO(dan): implement the acceptance policy.
#
# `score_candidates` has already done the mechanical work: hard constraints are
# filtered, survivors are scored, and the list arrives ranked best-first. What is
# left is the product judgement -- where the lines sit and whether there is a
# middle band at all.
#
# Things worth deciding:
#   * The auto-reuse line. Above what similarity do we serve WITHOUT a human?
#     Prompt embeddings routinely put unrelated-but-same-domain prompts around
#     0.80-0.88, and "red" vs "blue" variants well above 0.95, so this number
#     does real work.
#   * Whether a REVIEW band exists between "obviously fine" and "obviously not".
#     A review band turns some false reuses into a human decision, but a band
#     nobody actions is just a slower GENERATE.
#   * Whether an exact match should short-circuit the thresholds entirely.
#   * What `saved_usd` should be for a REVIEW. Counting a review as savings
#     inflates the headline number before anyone has accepted it, and that
#     number goes on the scoreboard the judges read.
#
# Return a Decision. `_rank` output is best-first; `candidates[0]` is the winner
# and the rest are alternatives. Populate `reason` -- it is written verbatim into
# the audit ledger and shown in the UI.
#
# You will need `Verdict` from reprise.model; it is not imported above precisely
# because nothing references it until this policy exists.
# ---------------------------------------------------------------------------
def classify(request: Request, candidates: Sequence[Candidate]) -> Decision:
    """Turn scored candidates into a REUSE / REVIEW / GENERATE decision."""
    raise NotImplementedError("acceptance policy not yet implemented")
