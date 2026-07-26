# Reprise demo script

Rendered with `agent-demo-video` against a LOCAL production server
(`uvicorn reprise.webapp:build_production_app`) wired to the real Backblaze B2
bucket, real Gemini, and the real Object Lock ledger. Nothing in the recording
is mocked: the reuse really serves from B2, the generation really spends, and
the scoreboard really reads the ledger.

Each shot runs in a fresh browser context, so every shot re-navigates and
replays its own flow from the landing page.

### SHOT problem
- target: dashboard
- url: /
- narration: Every team building with generative media pays for the same asset twice. The same product shot, the same jingle, weeks apart, requested by different people. Reprise sits in front of a Genblaze pipeline and asks one question first: did we already generate this? Those numbers come from an object locked ledger in B2, not from a counter.
- action: goto url="/"
- action: wait ms=700
- action: highlight selector="#board"

### SHOT reuse
- target: dashboard
- narration: Here is a prompt this library has already paid for. Reprise finds the exact match and serves the stored asset straight out of B2 behind a short lived presigned URL. Nothing was generated, and the four cents is booked as a saving. You do not have to take our word for it. Every result opens a proof receipt: the Genblaze run, the manifest key and its canonical hash, the object key, the digest, and the retention in force. Every line is checkable in the bucket.
- action: goto url="/"
- action: wait ms=400
- action: click selector="button[data-fill*='a red bicycle']"
- action: click selector="#go"
- action: wait ms=7000
- action: highlight selector="#result"
- action: wait ms=1200
- action: click selector=".receipt summary"
- action: wait ms=800
- action: scroll selector=".receipt dl"
- action: highlight selector=".receipt dl"

### SHOT review
- target: dashboard
- narration: Now a near duplicate. Crimson instead of red, propped instead of leaning. Ninety three percent similar. But similarity between prompts measures how alike two prompts read, not how alike two images look, so the candidate is shown, not just scored: you decide by looking at it. Anything between 0.85 and 0.97 stops here. Accepting is a signed capability token that can be spent once, and only then does the saving count.
- action: goto url="/"
- action: wait ms=400
- action: click selector="button[data-fill*='a crimson bicycle']"
- action: click selector="#go"
- action: wait ms=8000
- action: highlight selector="#result"
- action: wait ms=1500
- action: click selector=".actions button.primary"
- action: wait ms=6000
- action: highlight selector="#result"

### SHOT generate
- target: dashboard
- narration: And what happens when the human says no. Same kind of near duplicate, but this time we reject it, and Reprise pays. It generates through a provider we wrote ourselves, because every Imagen tier now refuses newly created API keys while still advertising itself as available. So it carries a fallback chain, and the manifest records the model that actually produced the bytes. The asset lands in B2 addressed by its own sha256, so the next person who asks gets it free.
- action: goto url="/"
- action: wait ms=400
- action: type selector="#prompt" text="a scarlet racing bicycle resting on a whitewashed brick wall, catalogue shot"
- action: click selector="#go"
- action: wait ms=9000
- action: highlight selector=".actions"
- action: wait ms=1200
- action: click selector=".actions button:not(.primary)"
- action: wait ms=26000
- action: highlight selector="#result"

### SHOT ledger
- target: dashboard
- narration: The board moved because the ledger moved. Every decision is an object locked record: a delete can hide one behind a delete marker, but it cannot destroy the version while retention holds. And the thresholds are measured, not asserted. Thirty eight labeled pairs, zero false auto reuse, published with the code.
- action: goto url="/"
- action: wait ms=700
- action: highlight selector="#board"
- action: wait ms=1500
- action: scroll selector="footer"
- action: highlight selector="footer"
