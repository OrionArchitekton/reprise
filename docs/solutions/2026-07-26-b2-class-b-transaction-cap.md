---
title: Backblaze Class B transaction cap took the live demo down
date: 2026-07-26
severity: SEV-1
status: mitigated
systems: [reprise, backblaze-b2, vercel]
symptoms:
  - "homepage 500, /api/scoreboard 500, /api/precheck 500"
  - "POST /api/decide returns 503 spend budget unavailable"
  - "/healthz stays 200 throughout"
root_cause: read-amplification against a per-account daily transaction cap
verified: 2026-07-26
review_after: 2026-10-26
topics: [object-storage, rate-limits, fail-closed, cost-control]
references:
  - src/reprise/ledger.py
  - src/reprise/library.py
  - src/reprise/gateway.py
  - tools/smoke.py
---

# Backblaze Class B transaction cap took the live demo down

## What happened

At roughly 20:50 UTC on 2026-07-26 the public demo stopped answering. The
homepage, the scoreboard and the budget precheck returned 500; `POST
/api/decide` returned 503 `spend budget unavailable, try later`. `/healthz`
stayed 200 the entire time, because it touches no storage.

An external reviewer looking at the same window concluded the cause was the
20:52 production deploy. It was not. The server log carried the actual error:

```
genblaze_core.exceptions.StorageError: Storage get for
'reprise/ledger/20260726T170027.634280Z-000001-434d4ea3.json' failed:
Cannot download file, download bandwidth or transaction (Class B) cap exceeded.
```

A Backblaze account-level daily cap on Class B transactions (object reads) had
been exhausted. Every read failed after that, regardless of which code was
deployed. A rollback would not have restored service.

## Why the cap was reachable

Read amplification that grew with the data:

- every `/api/decide` checked two daily budgets, and each check read EVERY
  ledger object to find records whose `kind` and date matched;
- every decide also read EVERY manifest to project the library;
- the scoreboard read every ledger object again, cached for only 10 seconds.

So a single request cost O(ledger + library) billed reads, and the ledger grows
by several records per request. A demo-video render that drives the app dozens
of times, plus judges probing the live URL, was enough to cross the cap.

## The worse defect the outage exposed

With manifests unreadable, `B2Library.scan()` skipped every object (its
resilience path for corrupt files), returned an empty projection, and the
gateway concluded the library held nothing and GENERATED. The product paid
again for an asset it already owned, which is the one outcome it exists to
prevent. Two real generations were spent this way before it was caught.

## Fixes

1. **Ledger key layout carries the date and kind**
   (`{prefix}/ledger/{YYYYMMDD}/{kind}/...`), so a cap check is one listing per
   kind rather than a read of every record. Records written before this layout
   remain at the flat root and are simply not counted toward today.
2. **Library projection is cached per process** (120s) and invalidated on
   write, so a repeat request re-reads nothing.
3. **Scoreboard cache raised** from 10s to 60s. It is a derived total.
4. **Unreadable is not empty.** `scan()` now separates objects it could not
   READ from objects it could not PARSE. The gateway refuses to decide when
   anything was unreadable (`LibraryUnavailable` -> 503 with a plain message),
   while a corrupt or foreign object still only skips itself.
5. **The homepage degrades** instead of 500ing when the scoreboard is
   unavailable.
6. **`tools/smoke.py`** walks the ladder a visitor walks. `/healthz` was green
   through the entire outage, so it was never going to catch this.

## Operator action still required

The engineering fixes cut the ongoing burn by orders of magnitude but cannot
restore service while the cap is exhausted. Either:

- wait for the daily cap to reset (Backblaze caps reset daily, UTC), or
- raise the caps in the Backblaze console under Caps and Alerts (a spend
  decision, so it is the operator's call).

## Verification

```
POST /api/decide {"prompt": "<an exact library prompt>"}
-> 503 {"detail":"the asset library is temporarily unreadable, so we will not
        generate: retry shortly rather than pay twice"}
```

Before the fix the same request returned `verdict: generate` and spent money.
After the cap resets, `python tools/smoke.py <base-url>` must pass end to end.

## Lesson

A health check that touches nothing cannot see an outage of everything. Probe
the path the user uses, and make sure a storage failure can never be read as a
business fact ("you do not own this") that authorises spend.
