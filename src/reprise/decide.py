"""The reuse decision.

Reprise answers "do we already own this?" in two stages, cheapest first:

1. A hard constraint filter. Modality, aspect ratio and style are not similarity
   signals -- they are substitutability requirements. A 16:9 video never serves a
   1:1 image request, however close the prompt reads. Filtering first also keeps
   the expensive stage small.
2. An exact-prompt check on the survivors. Same prompt, same constraints, already
   paid for. This needs no threshold and no embedding, so it is both the cheapest
   reuse and the only one that cannot produce a near-miss.

Near-match (semantic) reuse builds on this in `nearmatch.py`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from reprise.model import Candidate, Decision, LibraryEntry, Request, Verdict

_WHITESPACE = re.compile(r"\s+")


def normalize_prompt(prompt: str) -> str:
    """Fold the incidental differences that should not force a regeneration.

    Case and whitespace only. Deliberately conservative: stemming or stopword
    removal would start collapsing prompts that genuinely differ ("a cat on a
    mat" vs "a mat on a cat"), and a false reuse is far more expensive than a
    missed one -- it ships the wrong creative.
    """
    return _WHITESPACE.sub(" ", prompt.strip().lower())


def substitutable(request: Request, entry: LibraryEntry) -> bool:
    """Whether `entry` is even eligible to serve `request`."""
    return request.constraint_key() == entry.constraint_key()


def decide(request: Request, library: Iterable[LibraryEntry]) -> Decision:
    """Decide whether to reuse an existing asset or generate a new one.

    Exact-match only. Returns GENERATE when nothing in the library shares both
    the request's hard constraints and its normalized prompt.
    """
    wanted = normalize_prompt(request.prompt)

    exact: list[Candidate] = [
        Candidate(entry=e, similarity=1.0, exact=True)
        for e in library
        if substitutable(request, e) and normalize_prompt(e.prompt) == wanted
    ]

    if not exact:
        return Decision(
            verdict=Verdict.GENERATE,
            request=request,
            reason="no stored asset matches this prompt under the requested constraints",
        )

    ranked = _rank(exact)
    winner, *rest = ranked
    return Decision(
        verdict=Verdict.REUSE,
        request=request,
        candidate=winner,
        saved_usd=winner.entry.cost_usd,
        reason=(
            f"exact prompt match against run {winner.entry.run_id} "
            f"({winner.entry.provider}/{winner.entry.model})"
        ),
        alternatives=tuple(rest),
    )


def _rank(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Order qualifying candidates best-first.

    Highest recorded cost wins: reuse avoids repeating a spend, so the most
    valuable reuse is the one that would have cost the most to redo. `asset_id`
    is the final tiebreak purely to keep the ordering deterministic, which the
    decision ledger and the tests both depend on.
    """
    return sorted(
        candidates,
        key=lambda c: (-c.similarity, -c.entry.cost_usd, c.entry.asset_id),
    )
