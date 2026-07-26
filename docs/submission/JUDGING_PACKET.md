# Judging packet - Reprise (for external fresh-model review relays)

Paste this whole file into a FRESH chat with a frontier model, plus the repo
URL. Ask it to score per the criteria and return blocking findings. Relay the
scorecard back; findings are adjudicated against primary sources before any fix.

## The entry

- Product: **Reprise**, a reuse-first gateway for generative media. Before a
  Genblaze pipeline generates, Reprise checks a Backblaze B2 asset library for
  an exact or near-match; exact/high-similarity requests are served from
  storage (money not re-spent, booked on a scoreboard), a middle band goes to
  human review, everything else generates and is filed with provenance.
- Live URL: https://reprise-murex.vercel.app
- Repo: https://github.com/OrionArchitekton/reprise
- Hackathon: Backblaze Generative Media Hackathon 2026 (Devpost), deadline
  Aug 3 2026 5pm EDT.

## Criteria VERBATIM (equally weighted; ties break in listed order)

1. **Real-world Utility** - Does the application solve a practical problem for
   a clear audience, and would that audience actually use it?
2. **Production Readiness** - Does the application function reliably and
   support real-world workflows beyond a simple demo?
3. **B2 Storage + Data Orchestration** - Does the app use Backblaze B2
   meaningfully to store, organize, serve, or manage generated media,
   metadata, provenance, or app assets?
4. **Use of Genblaze** - Does the app use Genblaze meaningfully to build,
   connect, or orchestrate generative media workflows across models,
   providers, or steps?

Stage One is pass/fail: must reasonably fit the theme and apply B2 + Genblaze.

## Ground truth (facts external reviewers commonly hallucinate about)

- The library is a PROJECTION of Genblaze provenance manifests in B2; there is
  no separate database. Embedding sidecars + an object-locked decision ledger
  also live in the same bucket.
- Matching is on PROMPT embeddings (gemini-embedding-001), not image
  similarity. This is disclosed; the review band exists because of it.
- Policy: exact match short-circuits; auto-reuse at sim >= 0.97; review band
  [0.85, 0.97) saves nothing until a human accepts; below generates.
- Measured on a 38-pair labeled set with live embeddings: 0/17 dangerous pairs
  auto-reused; max attribute-swap similarity 0.968 (thin margin, disclosed).
- Generation providers actually wired and live-proven: a CUSTOM Genblaze
  SyncProvider for gemini-2.5-flash-image (all imagen-* tiers are retired for
  new API keys - documented with verbatim 404s), and stock ElevenLabs TTS.
- Two upstream SDK issues were filed from this build:
  backblaze-labs/genblaze#206 (the Google family probe reports LIVE for slugs
  that :predict rejects, so preflight passes and the run dies at call time) and
  #205 (no provider for the Gemini-native image models a new key can call).
- The Object Lock claim is scoped honestly: version deletes are refused by B2;
  an unversioned delete can HIDE a record behind a delete marker
  (tamper-evident, recoverable). docs/run-evidence.md records the probe
  correction that established this.
- TWO daily budgets are capped, both RESERVED before the money leaves (429
  before spend, fail closed if the reservation cannot be written): fresh
  generations, and decisions that have to embed. An exact repeat is free and
  consumes neither. Reuse/review stay available when a cap binds.
- Acceptance is authenticated by an HMAC capability token minted with the
  review that offered it, and each offer can be accepted ONCE (the token names
  its offer; the ledger records which offers are spent; a replay gets 409).
- Ingest gates on Manifest.verify_hash(): a manifest edited after Genblaze
  sealed it admits nothing. Per-asset rules (succeeded steps, sha256-bound
  assets, prompted steps) then filter within a verified manifest.
- Every result carries a proof receipt (run id, manifest key + canonical hash,
  asset key, sha256, producing provider/model, original cost, retention in
  force). A REVIEW serves the candidate so the human can see what they are
  judging, and "generate fresh instead" really generates.
- The image provider walks a model FALLBACK chain and the manifest records the
  model that actually produced the bytes.
- Object Lock retention is computed at each write, not at process start.
- What is DEMOED vs DESIGNED: single-tenant demo; per-request bucket rescan
  (an index is future work, ParquetSink named as the seed); the cap and
  replay checks are read-then-act, so a concurrent burst can overshoot by
  roughly the concurrency level (disclosed in the README).
- Everything in docs/run-evidence.md is a pasted probe output, never
  retro-edited; it includes two probe corrections (lock observable, model
  entitlement) kept deliberately.

## What to return

Per criterion: score /10 + one sentence. Then: blocking findings (things a
Devpost judge would penalize or that are DQ-risks), each with where you saw it
and why it matters. Then: the three questions a skeptical judge would ask.
Verdict: submit as-is, or fix X first.
