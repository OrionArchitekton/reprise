# YouTube upload fields

**File:** `demo/out/final.mp4` (rendered from `demo/DEMO_SCRIPT.md`)
**Visibility:** Public (the rules require a publicly viewable video; unlisted is
not sufficient for the judges' link check)
**Category:** Science and Technology

## Title

Reprise: check what you already generated before you pay to generate it again (Backblaze Generative Media Hackathon)

## Description

Reprise sits in front of a Genblaze pipeline and answers one question per
request: did we already generate this? Exact matches and near matches at or above
0.97 similarity are served straight from Backblaze B2 and the money not
re-spent is booked as a saving. Between 0.85 and 0.97 a human decides. Below
0.85 it generates for real and files the result, with its provenance manifest,
back into the library.

Every decision, reuse or spend, is written as an Object Lock record in B2 under
GOVERNANCE retention, and the savings scoreboard is recomputed from those
records rather than from an editable counter.

Built for the Backblaze Generative Media Hackathon 2026.

Live demo: https://reprise-murex.vercel.app
Source: https://github.com/OrionArchitekton/reprise
Evaluation report: https://github.com/OrionArchitekton/reprise/blob/main/eval/report.md

AI providers and models used:
- gemini-2.5-flash-image (image generation, through a custom Genblaze SyncProvider)
- eleven_flash_v2_5 (ElevenLabs text to speech)
- gemini-embedding-001 (prompt embeddings for near-match scoring)
- eleven_multilingual_v2 (narration in this video)

Measured, not asserted: 38 labeled prompt pairs, 0 of 17 dangerous pairs auto
reused, 0 of 10 non exact equivalents regenerated. The highest attribute-swap
similarity measured 0.968, just under the auto-reuse line, which is why the
human review band exists.

## Tags

backblaze, b2, genblaze, generative ai, cost control, provenance, object lock,
gemini, elevenlabs, fastapi, hackathon

## Checks before publishing

- [ ] Runtime is under 3:00 (judges may stop watching at 3:00)
- [ ] No third-party marks or copyrighted music (the ambient bed is synthesized
      by the render pipeline, not licensed music)
- [ ] The video shows the project functioning, not slides
- [ ] Link is public and plays in a signed-out browser
