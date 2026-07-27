# Run evidence (raw probe outputs, newest first)

All timestamps PT. Every claim below is a pasted probe result, not a paraphrase.

## 2026-07-26 ~19:40 - SDK feedback filed, and a correction to what the
## preflight probe actually proved

Re-probed the imagen question with free calls only (ListModels, models.get, and
:predict bodies that 404 or 400 before any generation), to state it precisely
enough to file upstream:

```
ListModels: 200, 56 models advertised
  imagen-* (3): imagen-4.0-generate-001, imagen-4.0-ultra-generate-001, imagen-4.0-fast-generate-001
  gemini-*image* (6): gemini-2.5-flash-image, gemini-3-pro-image-preview, gemini-3-pro-image,
                      gemini-3.1-flash-image-preview, gemini-3.1-flash-image, gemini-3.1-flash-lite-image

models.get imagen-3.0-fast-generate-001: 404  Model is not found: ... for api version v1beta
models.get imagen-3.0-generate-002:      404  Model is not found: ... for api version v1beta
models.get imagen-4.0-generate-001:      200  LIVE                      <- the genblaze family probe's signal
:predict   imagen-4.0-generate-001:      404  This model models/imagen-4.0-generate-001 is no longer
                                              available to new users. Please update your code to use
                                              a newer model for the latest features and improvements.
:predict   imagen-4.0-ultra-generate-001: 404 (same)
:predict   imagen-4.0-fast-generate-001:  404 (same)

entitlement is checked before params (both bodies deliberately invalid, zero cost):
  POST imagen-4.0-generate-001:predict        {}  -> 404 no longer available to new users
  POST gemini-2.5-flash-image:generateContent {}  -> 400 contents is not specified
```

CORRECTION to the 10:05 entry below. That entry credited the SDK preflight with
killing the Imagen step before spend. True, but only for `imagen-3.0-*`, which
left the catalog outright, so `models.get` 404s and the probe returns DEAD. For
the `imagen-4.0-*` line the probe reads 200 and returns LIVE, preflight PASSES,
and the 404 lands at call time. The probe measures catalog MEMBERSHIP; what
preflight needs is ENTITLEMENT. Our own product lesson restated: a listing is
not an entitlement.

Filed upstream (feedback prize track):
- https://github.com/backblaze-labs/genblaze/issues/206 - probe returns LIVE for
  slugs :predict rejects; proposed error mapping, an entitlement probe, and a
  third LiveProbeResult state. Includes the honest caveat that we have no
  Imagen-entitled key to confirm the 400 control on that endpoint.
- https://github.com/backblaze-labs/genblaze/issues/205 - no provider for the six
  Gemini-native image models a new key CAN call; wire-shape table and the
  `SyncProvider` patch sketch from `src/reprise/gemini_image.py`.

## 2026-07-26 ~10:25 - Phase 3 deploy verified (public URL live)

Vercel team project (dan-mercedes-projects/reprise), Python runtime, env from
doppler via stdin. Verification ladder, all live:

```
https://reprise-murex.vercel.app                       HTTP:200   <- PUBLIC alias
https://reprise-dan-mercedes-projects.vercel.app       HTTP:302 -> vercel SSO (as expected for team alias)
identity: <title>Reprise - reuse before you generate</title>   <- ours, not a squatter
healthz: {"status":"ok","app":"reprise"}
precheck: {"generations_today":2,"cap":40,"generation_available":true}  <- reads REAL B2 ledger
live decide (repeat prompt): verdict=reuse saved=0.0387
  serve_url host s3.us-west-004.backblazeb2.com; asset fetch 200 image/png 1907004 bytes
```

Cap note, stated honestly: the 429-before-spend path is proven by an
integration test (test_generation_cap_binds_with_429...); a live burst was NOT
fired against the public URL because each overflow attempt above the cap would
first burn ~40 real generations. /api/precheck live-verifies the counter reads
the same ledger the cap consults.

## 2026-07-26 ~10:05 - LIVE multi-provider generation proof (real spend)

tools/live_generate.py against the real bucket, real providers:

```
== 1. novel image request (expects GENERATE, real Imagen spend) ==
  generated: reprise/assets/b5/f8/b5f8a11f...cb5f785c.png
  sha256=b5f8a11ffe64d4f0... provider=gemini-image model=gemini-2.5-flash-image cost_usd=0.0387
== 2. exact repeat (expects REUSE, zero spend) ==
  reused 51919313-...-img-0, saved_usd=0.0387
== 3. novel audio request (expects GENERATE via ElevenLabs) ==
  generated: reprise/assets/c7/02/c7027ed2...8cfd8a81.mp3
  provider=elevenlabs-tts model=eleven_flash_v2_5
== ledger scoreboard: 4 decisions, 1 reuse, saved_usd=0.0387 ==
LIVE GENERATION PROOF PASSED
```

(The 4th ledger record is an early REVIEW decision from the first probe run,
immutable by design; the library's mock-era spike entries were delete-marked
before this run so only real-provider assets remain visible.)

Model-id gauntlet, all live-probed the same hour:
- SDK preflight killed `imagen-3.0-fast-generate-001` BEFORE spend ("upstream
  probe returned DEAD") - the registry-decoupling probe working as designed.
- The live catalog lists imagen-4.0-{generate,ultra,fast}; every one 404s
  "no longer available to new users" for this (new) key on :predict.
- `gemini-2.5-flash-image` generateContent returned a real PNG (2.4MB b64).
=> custom `GeminiImageProvider` (SyncProvider seam) is the image path; the
stock google connector's `^imagen-` family is unusable on new keys (filed as
SDK feedback candidate).

## 2026-07-26 ~09:00 - Object Lock binds (after a probe correction worth reading)

First probe asserted the naive observable (unversioned delete should fail) and
reported "LOCK DID NOT BIND: delete succeeded". That was the PROBE wrong, not
the control: on a versioned bucket an unversioned delete writes a delete
MARKER and reports success; the locked bytes are untouched. The lock's real
bind point is the version. Corrected probe output, live bucket:

```
locked ledger record written: reprise-probe/ledger/20260726T155906...-94e9e427.json
  unversioned delete -> delete marker only; locked version survives
  retention on version: GOVERNANCE until 2026-07-26 16:02:06+00:00
  version delete refused: AccessDenied (DeleteObject on VersionId)
  delete marker removed -> record recovered and readable
ALL LIVE PROBES PASSED
```

Product consequence, stated honestly: a plain delete can HIDE a ledger record
from naive listings (tamper-EVIDENT, not tamper-proof); the record is always
recoverable and the locked version undeletable until retention expires. The
app's audit view must read through delete markers.

## 2026-07-26 ~08:55 - Gemini embedding calibration (policy-critical)

```
gemini-embedding-001 dims=3072
  red-vs-blue same scene : cosine=0.9182   <- REVIEW band, NOT auto-reuse
  vs unrelated           : cosine=0.4763   <- GENERATE
  normalized repeat      : cosine=1.0000   <- exact path, never embedded twice
```

MANIFEST_OPENAI_API_KEY is a Manifest-gateway key (`mnfst_...`), rejected by
api.openai.com with a verbatim 401; Manifest's /v1/embeddings returns 404
(gateway has no embeddings route). Hence Gemini as default embedder.

## 2026-07-26 ~08:20 - Genblaze -> ObjectStorageSink -> real B2, verified

Full pipeline against the live bucket (`reprise-vault-9315d5`, us-west-004,
Object Lock enabled at creation). MockProvider handed a real 1x1 PNG via
`file://` (SSRF gate allows https/file); the sink fetched, hashed, and
transferred it; manifest uploaded alongside.

```
run: f262d532-c38c-40f9-8b94-c0b8dd14740e status: completed
verify(): True  verify_hash(): True
canonical_hash: 4bc2e64f572895a14dbd66eab68261725da516028a2edd29c9214fb49a0b1a21
step cost_usd: 0.042
asset url: https://s3.us-west-004.backblazeb2.com/reprise-vault-9315d5/reprise/assets/b1/ff/b1ff9c8e...png
  sha256: b1ff9c8ea3a780bad09b346c423d2d0e46815926879b18e841d928376a946640

B2 OBJECTS UNDER reprise/:
   reprise/assets/b1/ff/b1ff9c8e...a946640.png 69 bytes
     re-hash matches: True        <- independent boto3 read-back, not via genblaze
   reprise/manifests/f262d532-c38c-40f9-8b94-c0b8dd14740e.json 1538 bytes
```

Notable: with an unfetchable asset URL the sink FAILED CLOSED
(`SinkError: 1/1 asset transfer(s) failed; manifest was not uploaded`) instead
of uploading a manifest that would fail verification. Also: `Pipeline.run()`
emits a DeprecationWarning to pass `raise_on_failure=True` (default flips in
core 0.4.0) - our code should pass it explicitly.

## 2026-07-26 ~08:15 - scoped S3 key round-trip

Master key cannot use the S3 API (deterministic `InvalidAccessKeyId: Malformed
Access Key Id` in us-west-004 AND us-west-001; master keyID is 12 chars = the
account id, S3 requires the 25-char application keyID). Scoped key
`reprise-hackathon-s3` minted via native `b2_create_key` (master holds
`writeKeys`), stored in doppler `genblaze-hackathon/prd` as
B2_KEY_ID / B2_APP_KEY / B2_BUCKET / B2_REGION (the names
`S3StorageBackend.for_backblaze()` reads natively).

```
S3 PUT+GET OK  bucket: reprise-vault-9315d5  sha256: 7ccbd6858c8f6e41 ...
S3 DELETE OK
```

Bucket created with `fileLockEnabled=True` (Object Lock is create-time-only;
needed for the append-only decision ledger). The operator's earlier
console-created key was lost-by-design (B2 shows the secret exactly once).

## 2026-07-24 ~20:00 - SDK spike (pre-pick, per hackathon-build Phase 1.4)

PyPI `genblaze` 0.4.4 project_urls -> github.com/backblaze-labs/genblaze (the
repo named in the official rules) - official surface confirmed. End-to-end
in-memory pipeline:

```
canonical_hash: 38affaa6b097af3ac7bf22ea2080260dd6d2d01d87d4a21be9fec1e6d530314e
verify_hash() -> True
```

"v0.6.0" in Devpost updates is the release WAVE name / git tag; the umbrella
package is 0.4.4 (CHANGELOG states this verbatim). We are current.

## 2026-07-26 21:55 UTC - demo prompt bands, measured without touching B2

The bucket's Class B cap was still exhausted, so the library could not be
projected. The verdict does not need it: a near-match score is the cosine
between the request embedding and the STORED PROMPT's embedding, the stored
image prompt is on record (`tools/live_generate.py:34`), and Gemini is a
separate service with a separate quota. Probe ran the production
`score_candidates` + `classify` over a one-entry library rather than
re-deriving the thresholds, so an app-side threshold change cannot leave the
numbers below asserting bands that no longer exist.

Stored prompt: `a red bicycle leaning against a white brick wall, product
photo` (gemini-embedding-001, 3072 dims).

```
exact repeat (UI preset)     -> reuse    sim=1.0000
near-dupe (UI preset)        -> review   sim=0.9348
reject shot (demo video)     -> review   sim=0.8710
something new (UI preset)    -> generate sim=n/a
```

Two things this settles:

- The demo video's generate shot works. It types the reject-shot prompt,
  expects a REVIEW card, and clicks "generate fresh instead". That prompt
  scores 0.8710, inside [0.85, 0.97).
- The narration's "ninety three percent similar" for the near-duplicate is
  accurate at 0.9348.

Uncertainty runs the safe way. A one-entry library is a LOWER bound on the real
score, because the real verdict takes the max over every substitutable entry:
adding entries can only raise it. So the reject shot cannot fall through to
GENERATE; the only way it changes is another entry scoring 0.97 or above, which
would need a stored prompt closer to a scarlet racing bicycle than the red
bicycle already in the library. Confirm against the live library before
rendering anyway, since that is one cheap call once reads recover.

## 2026-07-27 00:00 UTC - cap reset, live confirmation

The Class B cap reset on schedule. `/readyz` returned 200 `storage: readable`,
and `tools/smoke.py` passed all ten checks against the live deployment for the
first time, including the asset fetch from B2. (It had never reached that rung:
the tool was written during the outage, and its last check crashed on a PNG
body, which only happens when everything else succeeds. Fixed in `50e05aa`.)

Live scoreboard at reset: 16 reuses, 5 reviews, 9 generates, 2 accepts,
$0.6966 saved across 30 decisions.

The demo prompt bands, re-measured against the REAL library rather than the
one-entry lower bound probed while reads were capped:

```
exact repeat     -> reuse    sim=1.0000  exact prompt match against run 9d6097da
near-duplicate   -> review   sim=0.9348  review band [0.85, 0.97)
reject shot      -> review   sim=0.8710  review band [0.85, 0.97)
something new    -> generate best similarity 0.77 below review line 0.85
```

Identical to the offline probe on all three scored prompts, which is the
result the lower-bound argument predicted: no other library entry outscores
the red-bicycle entry for a bicycle prompt.

## 2026-07-27 01:05 UTC - demo video re-rendered and frame-checked

First full render (158.6s) was discarded. It exposed three defects that are
invisible in a script and only appear in the artifact:

1. The review shot's accept fired about nine seconds before the narration that
   explains accepting. A viewer watched the saving get booked while being told
   a human still had to decide.
2. The comparison rows were never on screen. Measured: at the shipped capture
   CSS the `.compare` block ends at y=1675 in a 1080-tall viewport, and review
   was the only shot with no scroll of its own.
3. The generate shot consumed its own prompt. The render clicks "generate fresh
   instead", which files the asset in B2 under that exact text, so the same
   prompt scored 1.0000 on the next run and returned a REUSE with no review
   card and no reject button. Confirmed live: the old prompt now matches run
   d1fe7951 exactly.

Second render, 158.3s (2:38, under the 3:00 rule cap), 7 segments. Frame
checks against the artifact rather than the script:

```
t=75  review card, comparison rows and BOTH buttons in frame,
      caption "is shown, not just scored: you decide"
t=84  card border green (accepted), caption "signed capability token"
t=131 GENERATE card: "Generated fresh via gemini-image ($0.04) and filed in
      your library", reason "human rejected the library candidate"
t=1   title card reads "Check what you already generated before you pay to
      generate it again" (was "already own", pre-a3876dc copy)
```

New reject-shot prompt scored 0.8873 before the render, picked over a 0.8549
candidate for floor margin. Scoreboard moved 46 to 48 decisions across the
review and the forced generate, which is the two real decisions the shot makes.
