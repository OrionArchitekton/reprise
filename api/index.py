"""Vercel Python entrypoint: exposes the production ASGI app.

Vercel's Python runtime looks for an `app` object here; everything real lives
in reprise.webapp.build_production_app (env-driven: B2_*, GEMINI_API_KEY,
ELEVENLABS_API_KEY, REPRISE_DAILY_GENERATION_CAP).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from reprise.webapp import build_production_app  # noqa: E402

app = build_production_app()
