#!/usr/bin/env python3
"""CI pin: the committed eval artifacts must be self-consistent, offline.

Recomputes every verdict from the similarities STORED in eval/report.json (no
network, no re-embedding) under the CURRENT thresholds, recomputes the
headline error counts, and checks that report.md AND the README table quote
those same numbers. A threshold change without a re-run, a doctored case list,
or a hand-edited scorecard row fails the build.

What it does NOT catch, stated plainly: the stored similarity values
themselves are taken on trust (only a live re-run of tools/run_eval.py can
re-derive those), so editing a similarity in a way that keeps its verdict band
would pass. The pin binds the published numbers to the committed data, not the
committed data to the providers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from reprise.nearmatch import AUTO_REUSE_THRESHOLD, REVIEW_THRESHOLD

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

    # The MD and the README must both carry the JSON's headline numbers.
    # Containment, not full re-render equality: cosmetic wording stays free,
    # but a hand-edited number in either file fails the build.
    fa = summary["false_auto_reuse"]
    md = REPORT_MD.read_text()
    needle = f"False auto-reuse: {fa['count']} / {fa['of_dangerous_pairs']} dangerous pairs"
    if needle not in md:
        fail(f"report.md does not carry the JSON headline ({needle!r})")

    readme = (ROOT / "README.md").read_text()
    claim = f"{fa['count']} / {fa['of_dangerous_pairs']} dangerous pairs auto-reused"
    if claim not in readme:
        fail(f"README.md does not carry the JSON headline ({claim!r})")

    # Every per-category count the README table quotes must match the JSON.
    for cat, s in summary["by_category"].items():
        row = f"| {s['n']} | {s['reuse']} | {s['review']} | {s['generate']} |"
        if row not in readme:
            fail(f"README table row for {cat!r} does not match report.json ({row!r})")

    print(
        f"eval artifacts consistent: {len(results)} pairs, "
        f"false_auto={len(false_auto)}, missed={len(missed)}, "
        f"thresholds {AUTO_REUSE_THRESHOLD}/{REVIEW_THRESHOLD}"
    )


if __name__ == "__main__":
    main()
