# Submission freeze, 2026-07-27

**Frozen at `2f738ac`** on `main`, CI green, working tree clean, local equals
origin. Deadline 2026-08-03 5:00pm EDT; target submit 2026-08-01.

Everything below was run, not assumed. Where a line could not be verified it
says so rather than being ticked.

## Verified at the frozen SHA

| Check | Command | Result |
|---|---|---|
| Tests | `pytest` | 92 passed |
| Lint | `ruff check src tests tools` | clean |
| Types | `mypy` (bare: 21 files, src AND tests) | clean |
| Published numbers pinned to evidence | `tools/check_eval_freshness.py` | 38 pairs, false_auto=0, missed=0, count consistent across 5 docs |
| Gallery captions fit Devpost | `tools/check_captions.py` | 6 captions, longest 137 of 140 |
| No long dashes anywhere | repo-wide scan | 0 hits |
| CI | GitHub Actions on `2f738ac` | success |
| Clean-clone setup | fresh clone, README steps verbatim | 92 passed, ruff clean, mypy clean |
| Live ladder | `tools/smoke.py https://reprise-murex.vercel.app` | 10 of 10 PASS |
| Readiness | `GET /readyz` | 200 `storage: readable` |
| Repo | `gh repo view` | PUBLIC |
| Upstream feedback issues | `gh issue view 205 / 206` | both OPEN |

Live scoreboard at freeze: 29 reuses, 24 reviews, 12 generates, 4 accepts,
$1.2771 booked as saved across 65 decisions. Every one of those is a real
decision against the real bucket.

## Artifacts

| Artifact | Path | State |
|---|---|---|
| Demo video | `demo/out/final.mp4` | 158.3s (2:38, under the 3:00 rule cap), 22 MB. Gitignored, so it lives on disk until it is on YouTube |
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
| Video under 3 minutes | 2:38 |
| Video shows the project functioning | five live shots against the real bucket, no slides |
| Video publicly visible on YouTube, Vimeo or Youku | **operator action, not yet done** |
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

## Operator actions remaining (both need a human)

1. **Upload the video to YouTube.** Fields are in `YOUTUBE.md`. It must be
   **Public**, not unlisted: the rules require a publicly viewable video and
   the judges' link check will not accept unlisted. Confirm it plays signed out
   and reads under 3:00 on the watch page.
2. **Create the Devpost project and submit.** Operator only: the flow
   re-challenges an invisible reCAPTCHA on automated clicks, and evading bot
   detection is not something to attempt. `SUBMISSION.md` has every field ready
   to paste, including the two Genblaze issue links that the 10x Feedback Prize
   is judged on.

## Re-verify before submitting

The state below can drift between now and submit day, so re-run this:

```
python tools/smoke.py https://reprise-murex.vercel.app   # must PASS end to end
python tools/check_eval_freshness.py
python tools/check_captions.py
```

Two failure shapes are worth naming, because both have already happened here:

- **The bucket's daily transaction cap.** On 2026-07-26 the Class B cap was
  exhausted and every storage read failed; the homepage rendered a degraded
  scoreboard and `/api/decide` refused. `smoke.py` fails on both shapes now.
  Caps reset daily at 00:00 UTC. Check the headroom in Backblaze's Caps and
  Alerts before the judging window: a judge who hits an exhausted cap sees a
  refusal, not a demo.
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
