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
| Tests | `pytest` | 99 passed |
| Lint | `ruff check src tests tools` | clean |
| Types | `mypy` (bare: 21 files, src AND tests) | clean |
| Published numbers pinned to evidence | `tools/check_eval_freshness.py` | 38 pairs, false_auto=0, missed=0, count consistent across 5 docs |
| Gallery captions fit Devpost | `tools/check_captions.py` | 6 captions, longest 137 of 140 |
| No long dashes anywhere | repo-wide scan | 0 hits |
| CI | GitHub Actions on `2f738ac` | success |
| Clean-clone setup | fresh clone, README steps verbatim | 99 passed, ruff clean, mypy clean |
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

## 2026-07-30: the "try something new" preset had burned, and is fixed

Reproduced live before changing anything. The third preset returned:

```text
verdict: reuse
reason : exact prompt match against run 0fedbd11-f9da-4d14-83e5-cf444ee18b38
saved  : 0.0387
```

This is the failure shape already named above under "a stale demo prompt", but
it arrived through the demo itself rather than through a video re-render. The
lighthouse prompt was fixed in the template, so the first visitor to click the
button generated the asset and filed it in the library, and every visitor after
that got a correct REUSE from the one control that advertises a miss. Control
probes with unseen prompts returned GENERATE at similarity 0.73 and 0.81, so the
engine was working and only the prompt was spent.

Two things made it worth fixing rather than noting. A judge clicking the most
prominent control is told the thing is already in the library, which reads as
broken or staged. And it was the demo's only live-generation path, so it also
removed the visible evidence for the Genblaze criterion.

**The obvious fix does not work, and that is worth recording.** Appending a
nonce to the prompt changes the text without changing the meaning, and the
library matches on embedding similarity, not on text. A nonce still scores
around 0.99, which is above the 0.97 auto-reuse line, so it would have served
the same stored asset by a longer route and looked like the same bug.

Changed:

- The novel preset now draws from a rotating pool of 20 prompts that are far
  apart in meaning, shuffled per page load and not repeated until the pool is
  exhausted (`src/reprise/templates/index.html`).
- A REUSE card now offers "generate fresh instead", which the REVIEW card
  already had. The API always supported it; only the review path exposed it.
  This is the structural half: no burned prompt can strand a visitor again,
  whatever the pool does. It is not offered immediately after an accept, since
  that caller just chose the stored asset.
- A regression test asserts the preset carries no fixed prompt and that the
  pool holds at least 12 distinct entries (`tests/test_webapp.py`).
- `LICENSE` added. The README claimed MIT and the file was missing.
- A "Try it" block at the top of the README with the live URL and the video.
  Neither was linked from the repo, which is the first surface a judge reads.

Verified on branch `codex/reprise-demo-preset-20260730`, all offline:

| Check | Command | Result |
|---|---|---|
| Tests | `pytest` | 104 passed (99 before, plus the regressions) |
| Lint | `ruff check src tests tools` | clean |
| Types | `mypy` | clean, 21 files |
| Published numbers | `tools/check_eval_freshness.py` | 38 pairs, false_auto=0, missed=0, test count consistent across 5 docs at 104 |
| Captions | `tools/check_captions.py` | 6 captions, longest 137 of 140 |
| Long dashes | repo-wide scan | 0 hits |

The test count moved from 99 to 104, so README, DEVPOST_STORY, SUBMISSION and
TECHNICAL_BRIEF were updated together. `check_eval_freshness.py` enforces that,
which is why the number could not quietly drift.

### Revised after review, same day

The post-push review returned six findings and two changed the design. Both are
recorded because the first version of this fix was wrong in a way worth keeping
on the record.

**A forced generate after a REUSE would have inflated the savings metric.** The
first fix added "generate fresh instead" to the reuse card, reasoning that a
caller who has seen the stored asset may still need a different one. By the time
that card renders, `Gateway.handle()` has already written the reuse's
`saved_usd` into the object-locked ledger, and the forced generate records a
spend without compensating for it. The scoreboard would then report both, so the
one number this product exists to publish would overstate itself on the judged
surface. A REVIEW books zero saving, which is exactly why the override was
already sound there and only there. Reverted, and the reason is now a comment
next to the code rather than folklore.

**A client-side pool cannot keep the promise either.** Each page shuffled its
own copy of the 20 prompts, so it prevented repeats within one visit and knew
nothing about what other visitors had already generated. After ten were spent,
half of all first clicks would return REUSE, and eventually every one would: the
same failure, arriving more slowly. The library is shared, so the choice belongs
to the only party that can see it. `GET /api/novel-prompt` now picks a prompt
the library does not already hold, costs no embedding and no generation, and
reports `unseen: false` when the pool is exhausted rather than pretending.

That endpoint deliberately does not use the 60 second read cache. `scan()`
already answers from the in-process projection behind a cheap index-stamp
listing, and a cached answer here would hand back a prompt spent seconds
earlier, which is the bug it exists to prevent.

Three smaller findings applied: the README no longer promises the third preset
always generates, the regression test asserts the `data-novel` marker and an
exact pool size rather than a floor, and the fenced block above declares its
language.

**Two review engines did not run.** Phases 2 and 3 (codex standard and codex
adversarial) returned `usage_limit` and the grok leg errored, so the findings
above came from the bot threads and the final sweep only. This is not a clean
review, it is a partial one, and it is recorded as partial.

### Operator actions, deadline 2026-08-03 17:00 EDT

Devpost re-challenges reCAPTCHA on automated edits, so these are manual:

1. **The live Devpost page says "95 tests". The correct number is 105.**
   This line previously said "100 today", which was itself stale and would have
   had the operator paste a wrong number a second time. Verified 2026-08-03:
   `pytest -q` exits 0 with exactly 105 passing and 0 failures, and
   `tools/check_eval_freshness.py` reports "test count consistent across 5 docs:
   105". Update the story text from `docs/submission/DEVPOST_STORY.md`.

   Note the two are different claims: the freshness gate proves the five DOCS
   agree with each other, not that the suite passes. Both were run.
2. **TECHNICAL_BRIEF.pdf** on Devpost still reads 99. Regenerate from the HTML
   and re-upload, or leave it and accept a one-digit mismatch against the repo.
3. **Raise the B2 caps** for the 08-05 to 08-11 judging window. The Class B cap
   has already been exhausted twice under far lighter load than judging.
4. **Paste the Genblaze issue links** (#205, #206) into "Additional info", still
   outstanding from the 07-27 list above.

## 2026-08-03 pre-deadline verification (run, not assumed)

Deadline is 2026-08-03 17:00 EDT. The submission itself was filed 2026-07-27, so
this window is for edits, not for submitting. Everything automatable on the
"Pre-submit verification" list was executed:

| Check | Result |
|---|---|
| `pytest -q` | **exit 0, 105 passed, 0 failures** |
| `tools/check_eval_freshness.py` | exit 0; 38 pairs, false_auto=0, missed=0, thresholds 0.97/0.85; docs consistent at 105 |
| `tools/smoke.py https://reprise-murex.vercel.app` | **SMOKE PASSED**, all 10 stages |
| Live site signed-out | HTTP 200 |
| GitHub repo public | HTTP 200 |
| YouTube link | HTTP 303 (youtu.be short-link redirect, expected) |
| Long dashes in Devpost-bound text | 0 in DEVPOST_STORY.md and SUBMISSION.md |

Smoke confirmed the load-bearing path end to end, not just liveness: exact repeat
returns REUSE, the reuse carries a serve URL and a proof receipt, and the served
asset fetches from B2 with a 200. Scoreboard at check time: 100 decisions, 52
reuses, 30 reviews, 18 generates, 6 accepts, 2.2059 USD booked saved. Budgets
readable, generation cap 40/day and decision cap 400/day, both with full headroom.

**Still MANUAL and still outstanding** (Devpost re-challenges reCAPTCHA on
automated edits, and B2 caps live in the Backblaze console):

1. Update the Devpost story text from 95 to **105** tests.
2. Regenerate and re-upload TECHNICAL_BRIEF.pdf, or accept the digit mismatch.
3. Raise the B2 caps for the 08-05 to 08-11 judging window. The smoke run above
   used a little Class B quota; the Class B cap has been exhausted twice before
   under lighter load than judging will apply.
4. Paste the Genblaze issue links (#205, #206) into "Additional info".

## Live re-probe, 2026-08-03 04:20 UTC (00:20 EDT, 16h40m before the edit window closes)

The four-item list above was authored from local state and had gone stale against
the live submission. The published project page was re-probed directly. Two of the
four are already satisfied.

| # | Action as written above | Live state | Verdict |
|---|---|---|---|
| 1 | Story says 95, change to 105 | Page reads "... Doppler, 105 tests, mypy strict, and a CI check that pins the numbers in the README to the eval report that produced them", matching `DEVPOST_STORY.md:59` verbatim | **DONE, no edit needed** |
| 2 | `TECHNICAL_BRIEF.pdf` still reads 99 | The PDF on disk reads "105 tests, ruff, mypy strict, an eval-freshness pin, and a long-dash scan, all in CI" (`pdftotext`), rendered 2026-08-01 20:29 from `TECHNICAL_BRIEF.html:134` | **Local artifact is current.** Open question is only whether the copy attached to Devpost is this render |
| 3 | Raise B2 caps for 08-05 to 08-11 | Not checkable from here, the Caps page is console-only | **OUTSTANDING, and the only hard one** |
| 4 | Paste #205 / #206 into "Additional info" | Both literals appear on the live page inside "Challenges we ran into". The page has no "Additional info" section at all | **Substantively covered as prose**, links-in-a-field is cosmetic |

Method note: the page was read through an independent fetch, not from these local
files. The quoted sentence reproduces `DEVPOST_STORY.md:59` word for word, which is
what makes it a page read rather than an echo of local state. Both reads fall inside
one 15 minute fetch cache, so they describe the page as of roughly 04:16 to 04:20
UTC, not two samples separated in time.

Also stale above: line 74 lists genblaze #205 and #206 as "both open". The live page
states a Genblaze maintainer landed both in PR #220, merged 2026-07-28, closing them.
That is a better story beat than this checklist knew about.

### What actually remains

1. **Raise the B2 caps** for the judging window. This is the highest real risk in the
   submission: the Class B cap has been exhausted twice already under lighter load
   than judging will apply, and a cold serverless instance pays a full library scan,
   so read cost scales with the number of judges.
2. Confirm the `TECHNICAL_BRIEF.pdf` attached to Devpost is the 2026-08-01 render.
   Re-upload only if it is not.
3. Optional, cosmetic: add #205 and #206 as clickable links.
