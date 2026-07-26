# Devpost image gallery: capture plan and captions

Six images, in gallery order. Devpost truncates long captions, so every caption
below is under 140 characters (checked by `tools/check_captions.py`).

Capture against the live deployment, signed out, at 1440x900, light theme.
These are judge-facing evidence, so every number in a shot must be a real one
the live bucket produced. Do not stage them against a mock backend, and do not
crop out a degraded scoreboard if one is showing: fix the site first.

**Prerequisite:** `GET /readyz` returns 200 and `python tools/smoke.py <url>`
passes. A capped bucket renders the degraded scoreboard, which is exactly what
must not be photographed.

Save to `docs/screenshots/NN-slug.png`.

## 01-homepage.png

Landing page with the savings scoreboard.

> Every total on the scoreboard is folded from Object Lock records in B2, not
> from a counter the app can edit.

**Capture:** `/` at the top of the page, scoreboard fully visible.

## 02-exact-reuse.png

The exact-repeat result card.

> An exact repeat is answered from the library before any model is called, and
> the money not spent is booked as a saving.

**Capture:** click "try an exact repeat", then "Did we already generate this?".
Wait for the result card and the served asset to render.

## 03-review-card.png

The human review band.

> Between 0.85 and 0.97 similarity a human decides. The request, the stored
> prompt and the runner-up candidates are all shown side by side.

**Capture:** click "try a near-duplicate", then submit. Frame the comparison
rows and both action buttons.

## 04-proof-receipt.png

The receipt drawer, open.

> The receipt names the run, model, stored key and manifest hash, and links
> the manifest so a reader can recompute the hash.

**Capture:** on any result card, expand the receipt drawer. The manifest link
must be visible.

## 05-generate.png

A real generation.

> Below 0.85 it generates for real, files the asset and its provenance manifest
> into B2, and the next identical request is free.

**Capture:** click "try something new", submit, wait for the image. This spends
about $0.04 of real money, so capture it once.

## 06-evidence.png

The eval report or the ledger evidence in `docs/run-evidence.md`.

> 38 labeled pairs: nothing dangerous auto-reused, nothing equivalent
> regenerated. The published numbers are pinned to this data in CI.

**Capture:** `eval/report.md` rendered on GitHub, top table visible.

## Thumbnail

`docs/submission/thumbnail.png` (1280x720) is uploaded separately as the
project thumbnail, not as a gallery image.
