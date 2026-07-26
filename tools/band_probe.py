"""What band does each demo prompt land in, WITHOUT reading B2?

The bucket's transaction cap is exhausted, so the library cannot be projected.
But the verdict does not depend on B2: it depends on the cosine between the
request embedding and the stored prompt's embedding, and the stored prompt text
is on record in tools/live_generate.py. Gemini is a different service with a
different quota.

Runs the PRODUCTION functions (score_candidates + classify) over a hand-supplied
library rather than re-deriving the thresholds here, so a threshold change in
the app cannot leave this probe quietly asserting the old bands.

Caveat this cannot escape: the real verdict is the max over EVERY library entry,
and only the image entry's prompt is known here. A higher-scoring entry would
have to out-score a same-subject bicycle prompt, so this is a tight lower bound,
not a proof. Confirm against the live library once reads recover.
"""

import sys
from datetime import UTC, datetime

sys.path.insert(0, "src")

from reprise.embed import GeminiEmbedder
from reprise.model import LibraryEntry, Request
from reprise.nearmatch import classify, score_candidates

STORED = "a red bicycle leaning against a white brick wall, product photo"

CANDIDATES = [
    ("exact repeat (UI preset)", STORED),
    (
        "near-dupe (UI preset)",
        "a crimson bicycle propped against a white brick wall, product shot",
    ),
    (
        "reject shot (demo video)",
        "a scarlet racing bicycle resting on a whitewashed brick wall, catalogue shot",
    ),
    ("something new (UI preset)", "a lighthouse on a cliff in a thunderstorm, oil painting"),
]

emb = GeminiEmbedder()
stored_vec = emb.embed(STORED)
entry = LibraryEntry(
    asset_id="stored",
    prompt=STORED,
    modality="image",
    sha256="0" * 64,
    storage_key="reprise/assets/stored.png",
    cost_usd=0.04,
    provider="gemini",
    model="gemini-2.5-flash-image",
    run_id="run-stored",
    created_at=datetime(2026, 7, 26, tzinfo=UTC),
    embedding=stored_vec,
)

print(f"stored prompt: {STORED!r}  ({len(stored_vec)} dims)\n")
for label, prompt in CANDIDATES:
    req = Request(prompt=prompt, modality="image")
    cands = score_candidates(req, emb.embed(prompt), [entry])
    d = classify(req, cands)
    sim = f"{d.candidate.similarity:.4f}" if d.candidate else "n/a"
    print(f"{label:28s} -> {d.verdict.value:8s} sim={sim}")
    print(f"{'':28s}    {prompt}")
