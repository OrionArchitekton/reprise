# Devpost submission (operator checklist)

Devpost's "Create project" and final submit are **operator only**: the flow
re-challenges an invisible reCAPTCHA on automated clicks. Everything below is
staged so submitting is copy, paste, upload.

**Deadline: 2026-08-03, 5:00pm EDT. Target submit: 2026-08-01**, so a platform
problem on the last day is survivable.

## Field by field

**Project name**

```
Reprise
```

**Elevator pitch** (Devpost caps this at 200 characters)

```
Reprise checks whether you already own an asset before paying Genblaze to generate it again, serving it from Backblaze B2 and booking every decision to an Object Lock ledger.
```

**Story**: paste each section of `DEVPOST_STORY.md` under the matching Devpost
heading (Inspiration, What it does, How we built it, Challenges we ran into,
Accomplishments that we're proud of, What we learned, What's next).

**Built with** (tags)

```
python, fastapi, backblaze-b2, genblaze, gemini, elevenlabs, vercel, jinja, s3, object-lock
```

**Try it out links**

```
https://reprise-murex.vercel.app
https://github.com/OrionArchitekton/reprise
```

**Video demo link**: the public YouTube URL from `YOUTUBE.md` (must be public,
under 3:00).

**Image gallery**: upload `docs/screenshots/*` with the captions in
`SCREENSHOT_CAPTIONS.md` (Devpost truncates long captions, so each is under 140
characters).

**Thumbnail**: `docs/submission/thumbnail.png` (1280x720, under 2MB).

**Additional info / anything else**: mention the two Genblaze feedback issues,
which are what the 10x Feedback Prize is judged on and stack with an overall
prize:

```
SDK feedback filed during the build:
https://github.com/backblaze-labs/genblaze/issues/206 (the Google family probe reports LIVE for imagen-4.0 slugs that :predict rejects as unavailable to new users, so preflight passes and the run dies at call time)
https://github.com/backblaze-labs/genblaze/issues/205 (genblaze-google ships no provider for the Gemini-native image models, which are the only image models a newly created key can call)
```

## Stage One gate (pass/fail: both B2 and Genblaze used meaningfully)

- **B2**: content-addressed asset layout, provenance manifests, embedding
  sidecars, and an Object Lock decision ledger under GOVERNANCE retention. The
  library is a projection of what is in the bucket, so B2 is the system of
  record and not a dump.
- **Genblaze**: every generation runs as a `Pipeline` with
  `ObjectStorageSink(raise_on_failure=True)`; `Manifest.verify()` semantics gate
  what is eligible for reuse; providers per modality behind one interface,
  including a custom `SyncProvider` we wrote for Gemini-native image models.

## Judging criteria, and what answers each

| Criterion | Evidence |
|---|---|
| Real-world utility | The cost of regenerating what you already own is the problem; the live demo books real savings against a real bucket. |
| Production readiness | 69 tests, mypy strict, CI pinning published numbers to the eval data, reserve-before-spend budgets, capability-gated writes, correlation-id error handling. |
| B2 storage and data orchestration | Content addressing, manifests, sidecars, Object Lock ledger, presigned serving with a prefix containment check. |
| Use of Genblaze | Pipeline, ObjectStorageSink, manifest verification as an admission gate, a custom provider, and two upstream issues filed from real findings. |

## Pre-submit verification (run these, do not assume)

- [ ] `https://reprise-murex.vercel.app` returns 200 in a signed-out browser
- [ ] A decide request on the live site returns a verdict and a working asset URL
- [ ] The YouTube link plays signed out and is under 3:00
- [ ] The GitHub repo is public and the README setup steps work from a clean clone
- [ ] `python tools/check_eval_freshness.py` exits 0 at the submitted SHA
- [ ] No long dashes anywhere in the pasted text
