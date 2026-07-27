# Devpost image gallery: capture plan and captions

Six images, in gallery order. Devpost truncates long captions, so every caption
below is under 140 characters (checked by `tools/check_captions.py`).

Captured by `tools/capture_screenshots.py`, so the gallery can be regenerated
when the UI changes instead of being a folder of images nobody can re-derive:

```
python tools/capture_screenshots.py https://reprise-murex.vercel.app
python tools/capture_screenshots.py <url> --spend      # adds 05, real money
```

Against the live deployment, signed out, at 1440x1200. The viewport is 1200
tall rather than 900 because the result card measures about 1145px: at 900 no
scroll position shows a verdict headline and its evidence in the same frame,
and shrinking the asset with capture-only CSS would put a UI in the gallery
that the site does not render. A taller window is a real window.

These are judge-facing evidence, so every number in a shot is one the live
bucket produced. Do not stage them against a mock backend, and do not crop out
a degraded scoreboard if one is showing: fix the site first.

**Prerequisite:** `GET /readyz` returns 200 and `python tools/smoke.py <url>`
passes. A capped bucket renders the degraded scoreboard, which is exactly what
must not be photographed.

Written to `docs/screenshots/NN-slug.png`.

## 01-homepage.png

Landing page with the savings scoreboard.

> Every total on the scoreboard is folded from Object Lock records in B2, not
> from a counter the app can edit.

**Capture:** automated. Landing page at the top, scoreboard fully visible.

## 02-exact-reuse.png

The exact-repeat result card.

> An exact repeat is answered from the library before any model is called, and
> the money not spent is booked as a saving.

**Capture:** automated. Clicks "try an exact repeat" and submits, then frames
the result card from its top edge.

## 03-review-card.png

The human review band.

> Between 0.85 and 0.97 similarity a human decides. The request, the stored
> prompt and the runner-up candidates are all shown side by side.

**Capture:** automated. Clicks "try a near-duplicate" and submits. The frame
holds the badge, the headline, the comparison rows and both action buttons.

## 04-proof-receipt.png

The receipt drawer, open.

> The receipt names the run, model, stored key and manifest hash, and links
> the manifest so a reader can recompute the hash.

**Capture:** automated. Expands the receipt drawer on the reuse card and
frames the receipt with room under the manifest link, since this caption
promises a reader can open it.

## 05-generate.png

A real generation.

> Below 0.85 it generates for real, files the asset and its provenance manifest
> into B2, and the next identical request is free.

**Capture:** automated, behind `--spend`: it costs a real generation, about
$0.04. The prompt is filed in the library by the run, so a second `--spend`
needs a fresh novel prompt (`--generate-prompt`, checked with
`tools/band_probe.py`) or it captures a REUSE card under a generate filename.

## 06-evidence.png

The eval report as a reader meets it, rendered on GitHub.

> 38 labeled pairs: nothing dangerous auto-reused, nothing equivalent
> regenerated. The published numbers are pinned to this data in CI.

**Capture:** automated. Opens `eval/report.md` on GitHub signed out, which is
the page a judge would actually open to check the pinned numbers.

## Thumbnail

`docs/submission/thumbnail.png` (1280x720) is uploaded separately as the
project thumbnail, not as a gallery image.
