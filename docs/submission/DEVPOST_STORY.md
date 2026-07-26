# Devpost story (paste into the matching fields)

## Inspiration

Every generative media team quietly pays for the same asset twice. The same
product shot, the same jingle, the same hero image, weeks apart, requested by
different people who had no way to know it already existed. The bucket holding
those assets is usually treated as an archive: somewhere finished work goes to
sit. We wanted to treat it as the opposite, an asset that appreciates, and put
it in the request path so that owning something is checked before paying for it
again.

The framing that stuck with us: your storage bill is not the cost. Regenerating
what is already in storage is the cost.

## What it does

Reprise sits in front of a Genblaze pipeline and answers one question per
request: did we already generate this?

- **Exact match** returns the stored asset from Backblaze B2 behind a short
  lived presigned URL. Nothing is generated, and the money not re-spent is
  booked as a saving.
- **Near match at or above 0.97 similarity** auto-serves the same way.
- **Between 0.85 and 0.97** stops in front of a human, who accepts or rejects.
  Accepting requires a signed capability token minted with that specific card,
  so a saving cannot be forged into the ledger by anyone who can reach the API.
- **Below 0.85** generates for real, through Genblaze, and files the result in
  the library with its provenance manifest so the next person gets it free.

Every decision, reuse or spend, is written as an Object Lock record in B2 under
GOVERNANCE retention. The savings scoreboard on the page is recomputed from
those records, not from an application counter that anyone can edit.

## How we built it

- **Genblaze** does the orchestration. Generations run as a `Pipeline` with
  `ObjectStorageSink(raise_on_failure=True)`, so nothing enters the library
  without a sha256 bound, verifiable manifest. The library itself is a
  projection of those manifests, which means there is no second database to
  drift out of sync with what B2 actually holds.
- **Backblaze B2** is the product's memory. Assets are content addressed via
  `KeyStrategy.CONTENT_ADDRESSABLE`, so identical bytes dedupe by construction.
  Manifests sit beside assets. Embedding sidecars are keyed by normalized prompt
  hash, so a library prompt is embedded once no matter how many runs reference
  it. The decision ledger is written with Object Lock.
- **Similarity** is cosine distance over `gemini-embedding-001` prompt
  embeddings, with modality, aspect ratio and style held as hard constraints
  rather than scored, because those are substitutability requirements and not
  matters of degree.
- **Image generation** runs through a custom Genblaze `SyncProvider` we wrote
  for Gemini native image models, plus the stock ElevenLabs provider for audio.
- **Provenance is checkable, not asserted.** Admission is gated on
  `Manifest.verify_hash()`, and every result carries a proof receipt: run id,
  manifest key and canonical hash, content addressed asset key, sha256,
  producing model, and the retention actually in force. Those are coordinates
  you can re-derive from the bucket yourself.
- FastAPI and server rendered Jinja for the app, deployed on Vercel, secrets in
  Doppler, 88 tests, mypy strict, and a CI check that pins the numbers in the
  README to the eval report that produced them.

## Challenges we ran into

**Every Imagen tier refuses newly created API keys.** The Google connector's
only image family matches `^imagen-`, and on a key created this month every one
of those slugs answers 404 "no longer available to new users". Worse, the SDK's
liveness probe calls `models.get`, which returns 200 for those same slugs,
because catalog membership and entitlement are different facts. Preflight passed
and the run died at call time. We wrote our own `SyncProvider` against
`generateContent`, which returns inline image bytes, and filed both findings
upstream (genblaze issues #205 and #206).

**A spend cap that counted the wrong thing.** Our first daily cap counted ledger
records written after a generation completed. Under any concurrency the cap
failed open: the spend happened, then the record it was counted by. We rewrote it
to reserve before spending, and treat an unwritable reservation as an exhausted
cap. That is a fail closed default, and the regression test asserts the
reservation exists before the provider is ever called.

**The accept button was an unauthenticated write.** Anything that can POST to
the API could have written savings into an object locked ledger, which is the
one place in the system where a wrong number is permanent. Acceptance now
requires an HMAC capability token bound to the asset, the prompt and an expiry,
issued only in the review response that offered it.

**Saying what we actually proved about Object Lock.** Our first probe asserted
that a delete should fail, saw it succeed, and reported that the lock had not
bound. The probe was wrong, not the control: on a versioned bucket an
unversioned delete writes a delete marker. The lock binds at the version. We
corrected the probe, kept the correction in the evidence file, and now say
precisely what holds: a delete can hide a record, it cannot destroy the version
while retention holds.

## Accomplishments that we're proud of

- **The thresholds are measured, not asserted.** 38 labeled prompt pairs across
  five categories, scored with live embeddings: 0 of 17 dangerous pairs auto
  reused, 0 of 10 non exact equivalents regenerated. The published caveat is the
  interesting number: the highest attribute swap similarity measured 0.968, just
  under the 0.97 auto line, which is exactly why the review band exists.
- **CI will not let those numbers go stale.** A check recomputes every verdict
  from the stored similarities and fails the build if the README, the report, or
  the test count drifts from the data. We proved the check fires by tampering
  with each claim and watching it exit non zero.
- **The honest limitations are in the product, not just the README.** Prompt
  similarity measures how alike two prompts read, not how alike two images look.
  That is why attribute swaps land in front of a person instead of silently on a
  customer.

## What we learned

- A model appearing in a provider's catalog listing is not an entitlement.
  Probe the endpoint you will actually call.
- A spend cap that counts records written after the spend fails open. Reserve
  first, and treat the reservation store being unavailable as exhausted.
- When a claim outruns its checker, strengthen the checker rather than softening
  the claim, then prove it fires. A green gate whose failure you have never
  observed is indistinguishable from a no op.
- Provenance is only as good as what you refuse to admit. Failed steps and URL
  only assets never enter the library, because a manifest that cannot verify is
  worth less than no manifest at all.
- A health check that touches nothing cannot see an outage of everything. Ours
  stayed green while every page that read storage was down. The smoke check now
  walks the ladder a visitor walks.
- The sharpest lesson came from an outage we caused ourselves. Backblaze's daily
  transaction cap tripped because every request re-read the whole ledger and the
  whole library, so the cost grew with the data. Reads are now bounded to what
  can still change. But the worse defect was what the outage revealed: with
  manifests unreadable, the library looked EMPTY, and a reuse-first product
  cheerfully paid to generate an asset it already owned. Absence of evidence had
  been coded as evidence of absence. It now refuses instead, and says why.

## What's next for Reprise

- Finish the index. Ledger reads are already bounded (day partitions plus a
  snapshot of completed days), but a cold instance still scans the library once;
  Genblaze's `ParquetSink` tables are the natural seed for persisting it.
- Add an image embedding signal alongside the prompt signal, so the review band
  can narrow honestly rather than by moving a number.
- Team scoped libraries with per project budgets, and a webhook so an existing
  pipeline can consult Reprise without changing its own code.
- Land the two upstream issues as pull requests against genblaze-google.
