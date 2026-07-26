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
