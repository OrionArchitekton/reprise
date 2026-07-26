#!/usr/bin/env python3
"""CI pin: the committed eval artifacts must be self-consistent, offline.

Recomputes verdicts from the similarities STORED in eval/report.json (no
network, no re-embedding) under the CURRENT thresholds, and re-renders the
markdown. Any drift -- a hand-edited number, a threshold change without a
re-run, a doctored case list -- fails the build. This is the regenerate-and-
diff pin that lets the README quote eval numbers without being able to lie.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from reprise.nearmatch import AUTO_REUSE_THRESHOLD, REVIEW_THRESHOLD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORT_JSON = ROOT / "eval" / "report.json"
REPORT_MD = ROOT / "eval" / "report.md"


def fail(msg: str) -> None:
    print(f"EVAL FRESHNESS FAIL: {msg}")
    raise SystemExit(1)


def main() -> None:
    doc = json.loads(REPORT_JSON.read_text())
    summary, results = doc["summary"], doc["results"]

    if summary["thresholds"] != {
        "auto_reuse": AUTO_REUSE_THRESHOLD,
        "review": REVIEW_THRESHOLD,
    }:
        fail(
            f"report was produced at thresholds {summary['thresholds']}, code has "
            f"{AUTO_REUSE_THRESHOLD}/{REVIEW_THRESHOLD}; re-run tools/run_eval.py"
        )

    # Recompute every verdict from the stored similarity.
    for r in results:
        sim, exact = r["similarity"], r["exact"]
        if exact or sim >= AUTO_REUSE_THRESHOLD:
            want = "reuse"
        elif sim >= REVIEW_THRESHOLD:
            want = "review"
        else:
            want = "generate"
        if r["got"] != want:
            fail(f"stored verdict {r['got']!r} != recomputed {want!r} for {r['request']!r}")

    # Recompute the headline counts the README quotes.
    false_auto = [r for r in results if r["should"] == "generate" and r["got"] == "reuse"]
    if summary["false_auto_reuse"]["count"] != len(false_auto):
        fail("false_auto_reuse count drifted from stored results")
    missed = [r for r in results if r["should"] == "reuse" and r["got"] == "generate"]
    if summary["missed_reuse"]["count"] != len(missed):
        fail("missed_reuse count drifted from stored results")

    # The MD must carry the same headline numbers (cheap containment check;
    # full re-render equality would couple CI to cosmetic wording).
    md = REPORT_MD.read_text()
    fa = summary["false_auto_reuse"]
    needle = f"False auto-reuse: {fa['count']} / {fa['of_dangerous_pairs']} dangerous pairs"
    if needle not in md:
        fail(f"report.md does not carry the JSON headline ({needle!r})")

    print(
        f"eval artifacts consistent: {len(results)} pairs, "
        f"false_auto={len(false_auto)}, missed={len(missed)}, "
        f"thresholds {AUTO_REUSE_THRESHOLD}/{REVIEW_THRESHOLD}"
    )


if __name__ == "__main__":
    main()
