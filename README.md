# Reprise

**Check what you already generated before you pay to generate it again.**

Every generative-media team quietly regenerates assets it already paid for:
the same product shot, the same jingle, the same hero image with the same
prompt, weeks apart, by different people. Reprise sits in front of your
[Genblaze](https://github.com/backblaze-labs/genblaze) pipeline and answers
one question per request: *did we already generate this?* If yes, it serves the
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
retention, computed at each write): the savings scoreboard is recomputed from
records nobody can edit or destroy while retention holds. Every generated asset
carries Genblaze's provenance manifest, sha256-bound by `ObjectStorageSink`, and
every result carries a **proof receipt**: run id, manifest key and canonical
hash, content-addressed asset key, sha256, producing model, and the retention
actually in force. Those are coordinates you can re-derive from the bucket, not
a badge the app issues about itself.

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

## What it is worth at team scale

One reuse in this demo saves $0.0387, which proves the mechanism and not much
else. The arithmetic that matters is per team, and it is yours to run rather
than ours to assert:

| generations / day | monthly spend at $0.0387 | 10% duplicates | 30% duplicates |
|---|---|---|---|
| 50 | ~$58 | ~$6 | ~$17 |
| 200 | ~$232 | ~$23 | ~$70 |
| 1,000 | ~$1,161 | ~$116 | ~$348 |

We deliberately do not publish a duplicate rate of our own. We have not measured
one on real team traffic, and inventing one would be exactly the kind of number
this project exists to refuse. The rate is an input you supply; what Reprise
supplies is the mechanism that turns it into money not spent, plus the audit
trail that proves each instance. Video and audio move the same arithmetic
further, because their unit costs are higher and their regeneration latency is
measured in minutes rather than seconds.


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
- **`Manifest.verify_hash()` gates admission**: a manifest whose payload no
  longer matches its canonical hash is refused entirely, so editing a stored
  run's prompt cannot point a popular prompt at bytes of someone's choosing.
  Failed steps and URL-only assets are then filtered per asset, mirroring
  `verify()` semantics without letting one URL-only asset disqualify a run's
  properly bound ones;
- **a model fallback chain**, because a slug in the catalog is not a slug you
  are entitled to call (see the upstream issues below). If the pinned model
  answers 404, the provider walks its chain and the manifest records the model
  that actually produced the bytes.

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

Then open http://localhost:8000. `pytest` runs the 92-test suite offline
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
- A review shows you the candidate asset before asking you to judge it, and
  "generate fresh instead" really generates (it skips the library and pays).
- Acceptance requires an HMAC capability token issued in the review response,
  and each offer can be accepted once: the token names its offer and the ledger
  is the record of which offers are spent. That check is still read-then-act,
  so two simultaneous accepts of one offer could both pass; it bounds replay,
  it does not serialize it. There is no user accounts system in the demo.
- Reads are bounded rather than proportional to history: the ledger is
  partitioned by day and record kind, so a cap check is a listing; completed
  days fold once into a scoreboard snapshot and are never read again; the
  library projection is cached per process and invalidated on write. The ledger
  stays the authority, so deleting the snapshot just costs a rebuild. This was
  learned the hard way, in production: see
  [docs/solutions/2026-07-26-b2-class-b-transaction-cap.md](docs/solutions/2026-07-26-b2-class-b-transaction-cap.md).
- If the library cannot be READ, Reprise refuses to decide (HTTP 503) rather
  than treating an empty projection as "you do not own this" and generating. A
  manifest that reads fine but does not parse still only skips itself.
- A cold instance still pays one full library scan; a persisted library index
  (Genblaze's `ParquetSink` tables are the natural seed) is the next step.

## License

MIT
