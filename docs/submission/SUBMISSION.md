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
Reprise checks whether your Genblaze library already holds an asset before paying to generate it again, serves it from Backblaze B2, and books every decision to an Object Lock ledger.
```

**Story**: paste each section of `DEVPOST_STORY.md` under the matching Devpost
heading (Inspiration, What it does, How we built it, Challenges we ran into,
Accomplishments that we're proud of, What we learned, What's next).

Do not drop the **AI providers and models used** table at the end of "How we
built it". The official rules require the text description to carry "a clearly
defined list of the AI providers and models used", so that table is a
submission requirement, not decoration.

**Providers and models** (dedicated Devpost field: "List the AI providers and
models used"). Every id below was read out of the source, not recalled:

```
Google Gemini
- gemini-2.5-flash-image: image generation, called through a custom Genblaze
  SyncProvider we wrote, because genblaze-google ships no provider for the
  Gemini-native image models (filed as genblaze issue #205)
- gemini-3.1-flash-image: first choice in the provider's fallback chain; the
  manifest records whichever model actually produced the bytes
- gemini-embedding-001: prompt embeddings, 3072 dims, used for near-match
  similarity scoring

ElevenLabs
- eleven_flash_v2_5: audio generation in the app, via the stock Genblaze
  ElevenLabsTTSProvider
- eleven_multilingual_v2: narration in the demo video only, not in the product

Storage is Backblaze B2 throughout, via genblaze-s3. Nothing else is called at
runtime. The source also contains an OpenAIEmbedder (text-embedding-3-small)
implementing the same contract for anyone deploying with an OpenAI key; the
deployed app never constructs it.
```

**B2 and Genblaze usage** (dedicated Devpost field: "Explain how your app uses
both"):

```
B2 is the system of record, not a dump. Five prefixes carry the whole product
state, and the app holds no database beside them:

- reprise/assets: generated media, content addressed (key_strategy
  "content_addressable"), so identical bytes dedupe by construction
- reprise/manifests: the Genblaze provenance manifest for every run. The
  library is a PROJECTION of these, so there is nothing to drift out of sync
  with what the bucket actually holds
- reprise/embeddings: one sidecar per normalized prompt hash, so a prompt is
  embedded once no matter how many runs reference it
- reprise/ledger: every decision, written under Object Lock with GOVERNANCE
  retention, partitioned by date and kind so a daily spend check is a listing
  rather than a read of history
- reprise/index: a folded scoreboard snapshot over completed days

Reads are served as short-lived presigned URLs, and only for keys inside our
own asset tree, because a shared bucket accumulates objects this app did not
write.

Genblaze does the generation and the provenance. Every generation runs as a
Pipeline whose ObjectStorageSink(raise_on_failure=True) writes asset and
manifest together, so a failed persist is an error rather than a ledger row
claiming work that never landed. Manifest.verify_hash() is the admission gate:
a manifest that no longer matches its own canonical hash never enters the
library, which is what makes reuse safe to offer. Providers sit behind one
interface per modality, including a custom SyncProvider we wrote for the
Gemini-native image models. ObjectLockConfig sets the retention actually in
force, and the proof receipt on every result quotes it back.

Two findings from building on it went upstream as genblaze issues #205 and
#206.
```

**Built with** (tags)

```
python, fastapi, backblaze-b2, genblaze, gemini, elevenlabs, vercel, jinja, s3, object-lock
```

**Try it out links**

```
https://reprise-murex.vercel.app
https://github.com/OrionArchitekton/reprise
```

**Video demo link**

```
https://youtu.be/OhkccSow8hY
```

Uploaded 2026-07-27. Verified from a signed-out fetch: `isUnlisted:false`,
`isPrivate:false`, `lengthSeconds:158` (2:38, under the 3:00 cap), and the
description carries the AI providers and models list plus the live and repo
links.

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
| Real-world utility | The cost of regenerating what your own pipeline already made is the problem; the live demo books real savings against a real bucket. |
| Production readiness | 93 tests, mypy strict, CI pinning published numbers to the eval data, reserve-before-spend budgets, capability-gated writes, correlation-id error handling. |
| B2 storage and data orchestration | Content addressing, manifests, sidecars, Object Lock ledger, presigned serving with a prefix containment check. |
| Use of Genblaze | Pipeline, ObjectStorageSink, manifest verification as an admission gate, a custom provider, and two upstream issues filed from real findings. |

## Pre-submit verification (run these, do not assume)

- [ ] `https://reprise-murex.vercel.app` returns 200 in a signed-out browser
- [ ] A decide request on the live site returns a verdict and a working asset URL
- [ ] The YouTube link plays signed out and is under 3:00
- [ ] The GitHub repo is public and the README setup steps work from a clean clone
- [ ] `python tools/check_eval_freshness.py` exits 0 at the submitted SHA
- [ ] No long dashes anywhere in the pasted text
- [ ] `python tools/smoke.py https://reprise-murex.vercel.app` passes end to end.
      It starts at `/readyz`, which reads storage where `/healthz` does not, and
      it fails if the homepage is showing the degraded scoreboard: those are the
      two shapes the 2026-07-26 transaction-cap outage took.
- [ ] The Backblaze caps have headroom for the judging window (Caps and Alerts):
      a judge hitting an exhausted cap sees a refusal, not a demo
