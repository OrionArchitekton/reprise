#!/usr/bin/env python3
"""Devpost truncates gallery captions, so the captions have a hard length.

The caption file is written by hand and edited under deadline, which is exactly
when a sentence grows past the limit and gets cut mid-word in the gallery a
judge is looking at. Devpost gives no warning and no preview of the truncation,
so the check has to live here.

Captions are the blockquote lines under each `## NN-slug.png` heading.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_CAPTION = 140
CAPTIONS = Path(__file__).resolve().parent.parent / "docs/submission/SCREENSHOT_CAPTIONS.md"


def captions(text: str) -> list[tuple[str, str]]:
    """(section, caption) for every image section, in file order."""
    out: list[tuple[str, str]] = []
    section = ""
    buf: list[str] = []

    def flush() -> None:
        if section and buf:
            out.append((section, " ".join(buf)))

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            buf = []
            heading = line[3:].strip()
            section = heading if heading.endswith(".png") else ""
        elif line.startswith("> ") and section:
            buf.append(line[2:].strip())
        elif not line.strip() and buf:
            flush()
            buf = []
            section = ""
    flush()
    return out


def main() -> int:
    if not CAPTIONS.exists():
        print(f"CAPTIONS FAIL: {CAPTIONS} is missing")
        return 1
    found = captions(CAPTIONS.read_text())
    if not found:
        # A parser that silently finds nothing would pass forever. An empty
        # result means the file's shape changed, not that every caption is fine.
        print("CAPTIONS FAIL: no captions parsed; the file's shape changed")
        return 1
    bad = [(s, c) for s, c in found if len(c) > MAX_CAPTION]
    for section, caption in bad:
        print(f"CAPTIONS FAIL: {section} caption is {len(caption)} chars (max {MAX_CAPTION})")
        print(f"  {caption}")
    if bad:
        return 1
    longest = max(len(c) for _, c in found)
    print(f"captions ok: {len(found)} captions, longest {longest} of {MAX_CAPTION} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
