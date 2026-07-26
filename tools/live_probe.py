#!/usr/bin/env python3
"""Live integration probes. Run under doppler; paste output into docs/run-evidence.md.

    doppler run -p genblaze-hackathon -c prd -- .venv/bin/python tools/live_probe.py

Each probe hits the REAL surface the app depends on and prints raw results.
No probe swallows an error: a failure prints the provider's verbatim message
and exits nonzero, because a green probe that hides a dead dependency is worse
than a red one.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from reprise.embed import GeminiEmbedder
from reprise.nearmatch import cosine


def probe_gemini_embeddings() -> None:
    e = GeminiEmbedder()
    a = e.embed("a red bicycle against a white wall")
    b = e.embed("a blue bicycle against a white wall")
    c = e.embed("quarterly revenue forecast spreadsheet")
    print(f"gemini-embedding-001 dims={len(a)}")
    print(f"  red-vs-blue same scene : cosine={cosine(a, b):.4f}")
    print(f"  vs unrelated           : cosine={cosine(a, c):.4f}")
    exact = e.embed("A RED  bicycle against a white wall ")
    print(f"  normalized repeat      : cosine={cosine(a, exact):.4f}")
    assert cosine(a, exact) > 0.999, "normalization must make case variants identical"


if __name__ == "__main__":
    probe_gemini_embeddings()
    print("ALL LIVE PROBES PASSED")
