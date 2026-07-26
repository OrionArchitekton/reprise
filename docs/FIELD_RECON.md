# Field recon - Backblaze Generative Media Hackathon (probed 2026-07-24/26)

Facts from the LIVE rules page, the genblaze repo, and its issue tracker.
Re-persisted from the session scratchpad after a /tmp wipe; probe outputs that
back these claims are in `run-evidence.md`.

## Eligibility / clock (Phase 0: PASS)
- Open worldwide except Brazil, Quebec, Russia, Crimea, Cuba, Iran, North Korea;
  age of majority. Online. Dan (San Diego) eligible.
- Submissions close **Aug 3, 2026 5:00pm EDT**. Judging Aug 5-11, winners ~Aug 12.
- Prizes: $7,000 / $2,000 / $1,000. Bonus: 10x Feedback Prize (1hr Backblaze
  architecture session) for SDK feedback filed as a genblaze GitHub issue;
  stackable with one overall prize.
- Stage One is pass/fail: must use **both B2 and Genblaze** meaningfully.
- Criteria, equally weighted, tie-break in listed order:
  1. Real-world Utility  2. Production Readiness
  3. B2 Storage + Data Orchestration  4. Use of Genblaze
- Video **< 3:00** (judges may stop watching at 3:00), public YouTube/Vimeo/Youku,
  must show the project functioning; no third-party marks / copyrighted music.
- Repo public (or grant github.com/b2genblaze); README with full setup; text
  description must list AI providers + models used; working URL judges can test.

## Self-clone zone (sponsor's own samples - do NOT build these)
- `genblaze-gen-media-multi-provider-sample`: one prompt -> narrated, scored,
  captioned MP4; per-modality provider picker. The "AI media studio" IS theirs.
- `nvidia-nemotron-genblaze-b2`: upload media -> summaries/illustration/
  narration/music with provenance + B2.

## Known competitors (from their own feedback issues on the genblaze repo)
- Cinemory (#176): photo memories -> AI video reels, "provenance-first", B2.
- ProofRelay (#172): field report -> media brief, hash-verifiable provenance,
  Manifest.verify() as a publish gate.
- Reel (#168): screenplay -> previs cut, B2 + provenance.
=> ALL lead with provenance + generation. Provenance is the MODAL angle;
   generation studios are the modal shape. Differentiation lives elsewhere.

## Maintainer roadmap collisions (do not build these either)
- Manifest signing (JWS sidecar, Signer ABC) is an ACTIVE exec-plan tranche.
- C2PA is planned Mode 3. Both could land mid-judging and obsolete an entry.

## The white space our pick occupies
SDK primitives no sample and no known competitor uses: StepCache, CAS dedup
(sink normalizes extension case for dedup since 0.6.0-wave), per-step cost_usd
ledger, ParquetSink analytics tables, Evaluator/ThresholdEvaluator,
probe_models/fallback chains. Everyone GENERATES; nobody OPERATES the asset
corpus afterward. Criterion 3 explicitly rewards "store, organize, serve, or
MANAGE"; criterion 1 rewards a spend line every media team recognizes.

## Landmines other entrants already paid for (their issues, our free intel)
- Private B2 buckets break image->video chaining: downstream providers fetch the
  start image themselves; private-bucket URLs 422 ("start_image is required").
  Working pattern: provider-to-provider public URL handoff, persist to B2 after.
- Local bytes as inputs: raw bytes and data: URIs are rejected (SSRF gate allows
  https:// and file:// only). Working pattern: write bytes to the backend under
  a content-addressed key, mint backend.get_url(key), build a full
  Asset(url=, media_type=, sha256=, size_bytes=) for external_inputs=.
- Manifest.verify() fails URL-only outputs by design; route outputs through
  ObjectStorageSink so sha256 is populated (verify_hash() for hash-only checks).
- Pipeline.step() on core 0.3.7 DOES expose metadata= and prompt_visibility=
  (the #172 gap is fixed in the released version we run).
- Sink fails closed on transfer errors (SinkError before manifest upload).
- Pass raise_on_failure=True explicitly (default flips in core 0.4.0).

## GMI Cloud credits
First-270-participants gate; 1042 registered as of 07-24 => assume exhausted.
GMI is optional per the rules ("other cloud providers may be used"). Providers
with keys on hand: OpenAI (MANIFEST_OPENAI_API_KEY), Google (GEMINI_API_KEY),
ElevenLabs (ELEVENLABS_API_KEY) - three modalities, three providers.
