# Reprise

**Check what you already own before you pay to generate it.**

Every generative-media team quietly regenerates assets it already paid for:
the same product shot, the same jingle, the same hero image with the same
prompt, weeks apart, by different people. Reprise sits in front of your
[Genblaze](https://github.com/backblaze-labs/genblaze) pipeline and answers
one question per request: *do we already own this?* If yes, it serves the
stored asset from Backblaze B2 and books the money you did not re-spend. If
almost, a human decides. Only if no does it generate.

Built for the Backblaze Generative Media Hackathon 2026.

## How a request flows

```
prompt ->  exact match?  ------ yes -> REUSE   (serve from B2, $0, saving booked)
             | no
           embed + score library
             |- similarity >= 0.97 -> REUSE    (auto-serve)
             |- 0.85 .. 0.97       -> REVIEW   (human one-click accept)
             '- below 0.85         -> GENERATE (Genblaze pipeline -> B2 + manifest)
```

Every decision is written to an **Object-Lock ledger** in B2 (GOVERNANCE
retention): the savings scoreboard is recomputed from records nobody can edit
or destroy while retention holds. Every generated asset carries Genblaze's
provenance manifest, sha256-bound by `ObjectStorageSink`.

## Measured, not promised

The acceptance thresholds are evaluated against a labeled dataset with live
`gemini-embedding-001` embeddings ([eval/report.md](eval/report.md), regenerated
by `tools/run_eval.py`; CI fails if the numbers drift from the generator):

| category | n | reuse | review | generate |
|---|---|---|---|---|
| exact repeat | 6 | 6 | 0 | 0 |
| equivalent phrasing | 10 | 5 | 5 | 0 |
| attribute swap (red->blue, mug->glass) | 10 | 0 | 9 | 1 |
| same domain, different ask | 7 | 0 | 0 | 7 |
| unrelated | 5 | 0 | 0 | 5 |

**0 / 17 dangerous pairs auto-reused. 0 / 10 non-exact equivalent pairs
regenerated** (the other 6 equivalent pairs are exact repeats, which cannot
miss by construction; of the 10, five auto-reused and five went to review).
Honest caveat: the highest attribute-swap similarity measured 0.968, close
under the 0.97 auto line. The review band exists precisely because prompt
similarity cannot safely separate "same scene, different subject" on its own;
swaps land in front of a human, never silently on a customer.

## How it uses B2 and Genblaze

**Backblaze B2** is the product's memory, not a dump:
- content-addressed asset layout (`assets/{sha[:2]}/{sha[2:4]}/{sha}`) via
  `KeyStrategy.CONTENT_ADDRESSABLE` -- identical bytes dedupe by construction;
- provenance manifests beside assets (`manifests/{run_id}.json`);
- embedding sidecars keyed by normalized-prompt sha256 (`embeddings/`) -- a
  library prompt is embedded once and never again, however many runs reuse it;
- an append-only decision ledger (`ledger/`) written with **Object Lock**
  GOVERNANCE retention -- deleting a record's *version* is refused by B2
  itself. A plain delete can still *hide* a record behind a delete marker
  (tamper-evident and recoverable, not indestructible), and the demo
  scoreboard reads current versions, so it would not show a hidden record.
  Verified live, correction history included, in
  [docs/run-evidence.md](docs/run-evidence.md);
- assets served with short-lived presigned URLs; rotating URLs are never
  persisted.

**Genblaze** does the orchestration:
- `Pipeline` + `ObjectStorageSink(raise_on_failure=True)` for every generation,
  so nothing enters the library without a sha256-bound, verifiable manifest;
- the library itself is a *projection of Genblaze manifests* -- there is no
  second database to drift;
- providers per modality behind one interface: a **custom `SyncProvider`**
  for Gemini-native image models (`gemini-2.5-flash-image`) -- written because
  every `imagen-*` tier now answers "no longer available to new users" on
  fresh API keys -- plus the stock `ElevenLabsTTSProvider` for audio;
- `Manifest.verify()` semantics gate what is reusable: failed steps and
  URL-only assets never enter the library.

AI providers and models used: `gemini-2.5-flash-image` (image generation),
`eleven_flash_v2_5` (ElevenLabs TTS), `gemini-embedding-001` (prompt
embeddings for near-match scoring).

## Run it

```bash
pip install -r requirements.lock

export B2_KEY_ID=... B2_APP_KEY=... B2_BUCKET=... B2_REGION=...   # scoped key; bucket created WITH Object Lock
export GEMINI_API_KEY=...
export ELEVENLABS_API_KEY=...

uvicorn "reprise.webapp:build_production_app" --factory --app-dir src --port 8000
```

Then open http://localhost:8000. `pytest` runs the 68-test suite offline
(a real Genblaze pipeline against an in-memory storage backend; only the
provider network calls are mocked). CI checks that this number still matches
what pytest collects, so it cannot quietly go stale. Live integration probes,
which spend a few cents, are `tools/live_probe.py` and `tools/live_generate.py`.

## Honesty notes

- The similarity guard measures how alike two *prompts* read, not how alike
  two *images* look. That limitation is why the review band exists and why
  auto-reuse is deliberately conservative.
- A B2 delete can *hide* a locked ledger record behind a delete marker
  (tamper-evident, recoverable); it cannot destroy the version until
  retention expires. Verified live, correction history included, in
  [docs/run-evidence.md](docs/run-evidence.md).
- The public demo caps two budgets per day: fresh generations, and decisions
  (which each pay for an embedding). Both reserve before spending and return
  HTTP 429 when exhausted; free paths keep working. The reservation is
  written before the provider call, so a spend is never uncounted, but the
  check is still read-then-act: a burst of concurrent requests can overshoot
  a cap by roughly the concurrency level before the reservations land.
- Acceptance of a review candidate requires an HMAC capability token issued
  in the review response; there is no user accounts system in the demo.
- Demo-scale scans re-list the bucket per request; a production deployment
  would maintain an index (Genblaze's `ParquetSink` tables are the natural
  seed).

## License

MIT
