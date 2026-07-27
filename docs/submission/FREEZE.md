# Submission freeze, 2026-07-27

**Submitted 2026-07-27**: https://devpost.com/software/reprise-2s8tvi

This document is a running record, not a sealed one. It said "code frozen at
`2f738ac`, later commits are documentation only" and that went stale within
hours, when `e788d1a` changed `src/reprise/library.py`. A freeze note that
asserts a thing it cannot keep true is worse than no freeze note, so it now
names the last runtime-changing commit and expects that to move.

**Last runtime-changing commit: see `git log --oneline -- src/`.** Judging runs
2026-08-05 to 08-11, and fixing a real defect before a judge meets it beats
holding a frozen SHA.

Everything below was run, not assumed. Where a line could not be verified it
says so rather than being ticked.

## Verified at the frozen SHA

| Check | Command | Result |
|---|---|---|
| Tests | `pytest` | 95 passed |
| Lint | `ruff check src tests tools` | clean |
| Types | `mypy` (bare: 21 files, src AND tests) | clean |
| Published numbers pinned to evidence | `tools/check_eval_freshness.py` | 38 pairs, false_auto=0, missed=0, count consistent across 5 docs |
| Gallery captions fit Devpost | `tools/check_captions.py` | 6 captions, longest 137 of 140 |
| No long dashes anywhere | repo-wide scan | 0 hits |
| CI | GitHub Actions on `2f738ac` | success |
| Clean-clone setup | fresh clone, README steps verbatim | 95 passed, ruff clean, mypy clean |
| Live ladder | `tools/smoke.py https://reprise-murex.vercel.app` | 10 of 10 PASS at freeze. **FAILING again 2026-07-27 16:08 UTC**: the B2 Class B cap is exhausted a second time, see below |
| Readiness | `GET /readyz` | 200 at freeze; 503 `storage: unreadable` at 16:08 UTC |
| Repo | `gh repo view` | PUBLIC |
| Upstream feedback issues | `gh issue view 205 / 206` | both OPEN |

Live scoreboard at freeze: 29 reuses, 24 reviews, 12 generates, 4 accepts,
$1.2771 booked as saved across 65 decisions. Every one of those is a real
decision against the real bucket.

## Artifacts

| Artifact | Path | State |
|---|---|---|
| Demo video | `demo/out/final.mp4`, published at https://youtu.be/OhkccSow8hY | 158.3s (2:38, under the 3:00 rule cap), 22 MB. Gitignored, so the master lives on local disk; the published copy is the durable one |
| Thumbnail | `docs/submission/thumbnail.png` | 1280x720, 150 KB (limit 2 MB) |
| Technical brief | `docs/submission/TECHNICAL_BRIEF.pdf` | 2 pages, regenerated from the HTML at current copy |
| Gallery | `docs/screenshots/01..06` | 6 shots, regenerable via `tools/capture_screenshots.py` |
| Devpost fields | `docs/submission/SUBMISSION.md` | staged field by field |
| Story | `docs/submission/DEVPOST_STORY.md` | section per Devpost heading |
| YouTube fields | `docs/submission/YOUTUBE.md` | title, description, tags, pre-publish checks |

The video was frame-checked against the artifact, not the script: the review
card's comparison rows and both buttons are in frame at t=75 under the caption
that describes them, the accept lands at t=84 on "signed capability token", the
generate shot shows a real rejection and a real generation at t=131, and the
title card carries the current copy.

## Official rules, checked line by line

Read from the rules page on 2026-07-27, not from memory. Dates confirmed:
submission closes **2026-08-03 5:00pm ET**, judging 08-05 to 08-11, winners
announced on or around 08-12.

| Requirement | State |
|---|---|
| Working app using B2 Cloud Storage and Genblaze | yes, both load-bearing |
| Functions as depicted in the video | video frame-checked against the live behaviour |
| URL judges can access, test, evaluate | https://reprise-murex.vercel.app, no auth, so no test account needed |
| Public GitHub repo with all source, assets, and **setup instructions in the README** | public; the README steps were BROKEN until `2f738ac` and are now verified from a clean clone |
| Text description: features, how it uses B2 and Genblaze, **and a clearly defined list of AI providers and models** | the models table was missing from the Devpost text and is now in "How we built it" |
| Video under 3 minutes | 2:38 (`lengthSeconds:158` on the published video) |
| Video shows the project functioning | five live shots against the real bucket, no slides |
| Video publicly visible on YouTube, Vimeo or Youku | https://youtu.be/OhkccSow8hY, verified `isUnlisted:false` / `isPrivate:false` from a signed-out fetch |
| No third party trademarks or copyrighted music | audio bed is synthesized by the render pipeline, not licensed |
| Optional: SDK feedback via Genblaze issues | genblaze #205 and #206, both open |
| Project is new, created in the submission period | yes |

Two of these were found failing during this check rather than passing: the
README setup instructions and the models list. Both are explicit requirements,
not preferences.

**Registration.** The rules require completing the "Enter a Submission" page
during the submission period, which presumes a registered Devpost entrant. An
unauthenticated read of the site cannot tell whether this account is
registered. Confirm you are joined to the hackathon before submit day.

## Operator actions remaining

1. ~~Upload the video to YouTube.~~ **Done 2026-07-27**:
   https://youtu.be/OhkccSow8hY. Verified public rather than unlisted, 158
   seconds, and the description carries the models list and both links.
2. ~~Create the Devpost project and submit.~~ **Done 2026-07-27**:
   https://devpost.com/software/reprise-2s8tvi

Verified from a signed-out fetch of the public project page, which is the view
a judge gets: it reads "Submitted to" the hackathon (created and entered, not
merely created), the video is embedded as youtube.com/embed/OhkccSow8hY, the
live URL and repo are both linked, all ten Built-with tags are present, six
gallery images uploaded, and the story text carries the models and the B2 and
Genblaze explanation.

(An earlier revision of this file said twelve. That came from counting
`software_photos` occurrences in the page source, which appears twice per
image. A probe that counts the wrong thing returns a number rather than an
error, and a number reads as verified.)

**One thing left, and it is small.** The two Genblaze issue URLs are not on the
page as links. They appear only inside the Challenges prose as "(genblaze
issues #205 and #206)". The issues themselves are filed and open, which is what
the 10x Feedback Prize is actually judged on, so nothing is disqualified. But a
judge assessing that prize should not have to search for them. Paste the block
from `SUBMISSION.md` into the project's "Additional info" field so they are one
click away.

## Re-verify before submitting

The state below can drift between now and submit day, so re-run this:

```
python tools/smoke.py https://reprise-murex.vercel.app   # must PASS end to end
python tools/check_eval_freshness.py
python tools/check_captions.py
```

Two failure shapes are worth naming, because both have already happened here:

- **The bucket's daily transaction cap. This has now happened twice.** On
  2026-07-26 it was caused by read amplification in the code, which is fixed.
  On 2026-07-27 at 16:08 UTC it happened AGAIN, roughly 16 hours into the UTC
  day, with the fix in place and under nothing heavier than a video render,
  three screenshot runs and a handful of probes. So the second occurrence is
  not a defect: it is ordinary volume against a cap that is too low.

  That matters for judging (08-05 to 08-11) more than it matters for us. Each
  cold serverless instance pays a full library scan, one listing plus a read
  per manifest and per embedding sidecar, and Vercel gives a cold instance to
  requests it has no warm one for. So the read cost scales with judges times
  library size, and the library grows every time anyone generates.

  Two ways out, and they are not exclusive: raise the cap in Backblaze's Caps
  and Alerts (a spend decision, so an operator call), or cut the cold-start
  cost structurally by persisting the library projection as a single index
  object the way the scoreboard snapshot already is, taking a cold instance
  from about 2N+1 reads to about 1. The code already names the persisted index
  as the right fix at scale.

  Caps reset daily at 00:00 UTC.
- **A stale demo prompt.** Re-rendering the video consumes the generate shot's
  prompt, since the render files that asset in B2 under that exact text. Check
  a fresh one with `tools/band_probe.py` before any re-render.

## Known limits, stated rather than hidden

- The library projection is a per-process cache over a bucket listing, not a
  persisted index. It is right for a demo corpus and named as a scale limit in
  the code and the brief.
- Accept replay protection is read-then-act against the ledger. It bounds
  replay, it does not serialize it, and the docstring says so.
- The similarity thresholds are measured on 38 labeled pairs, which is a small
  set. The eval report publishes the full per-category table including the
  ranges, so the reader can judge the sample rather than take a headline.
