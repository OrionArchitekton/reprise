"""The Reprise web app: judge-facing surface over the gateway.

Design constraints that shaped this module:

* **App factory** (`create_app(gateway, ledger)`) so tests inject an in-memory
  stack; `build_production_app()` wires the real B2 + Gemini + ElevenLabs
  stack from env and is what the deployment entrypoint imports.
* **Server-rendered** single page (Jinja): the demo-video pipeline captures
  SSR HTML, and a static `?demo=1` mode renders seeded example cards with no
  backend calls at all -- capture-stable by construction.
* **Spend guard**: the public endpoint sits on real provider keys. Generation
  is capped per UTC day by COUNTING the ledger's GENERATE records -- the audit
  trail is the rate limiter's source of truth, no extra infra. When the cap is
  hit, /api/decide still answers REUSE/REVIEW verdicts (they are free); only
  fresh generation is refused, with the cap stated in the error.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from reprise.gateway import Gateway, GatewayResult
from reprise.ledger import Ledger
from reprise.model import Candidate, Decision, LibraryEntry, Request, Verdict

TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_DAILY_GENERATION_CAP = 25


class DecideBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    modality: str = Field(default="image", pattern="^(image|audio)$")
    aspect_ratio: str | None = None
    style: str | None = None


class AcceptBody(BaseModel):
    """Re-materialize the REVIEW decision to accept, by ledger identity."""

    prompt: str
    modality: str
    asset_id: str


def _entry_view(e: LibraryEntry, url: str | None = None) -> dict[str, Any]:
    return {
        "asset_id": e.asset_id,
        "prompt": e.prompt,
        "modality": e.modality,
        "sha256": e.sha256,
        "provider": e.provider,
        "model": e.model,
        "cost_usd": e.cost_usd,
        "run_id": e.run_id,
        "serve_url": url,
    }


def _decision_view(d: Decision, result: GatewayResult | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "verdict": d.verdict.value,
        "reason": d.reason,
        "saved_usd": d.saved_usd,
        "prompt": d.request.prompt,
        "modality": d.request.modality,
    }
    if d.candidate is not None:
        out["candidate"] = {
            **_entry_view(d.candidate.entry),
            "similarity": round(d.candidate.similarity, 4),
            "exact": d.candidate.exact,
        }
        out["alternatives"] = [
            {**_entry_view(c.entry), "similarity": round(c.similarity, 4)}
            for c in d.alternatives[:3]
        ]
    if result is not None:
        out["serve_url"] = result.serve_url
        if result.new_entry is not None:
            out["new_entry"] = _entry_view(result.new_entry)
    return out


def create_app(
    gateway: Gateway,
    ledger: Ledger,
    *,
    daily_generation_cap: int = DEFAULT_DAILY_GENERATION_CAP,
) -> FastAPI:
    app = FastAPI(title="Reprise", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )

    def generations_today() -> int:
        today = datetime.now(UTC).date().isoformat()
        return sum(
            1
            for doc in ledger.entries()
            if doc.get("verdict") == Verdict.GENERATE.value
            and str(doc.get("ts", "")).startswith(today)
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "app": "reprise"}

    @app.get("/", response_class=HTMLResponse)
    def index(demo: int = 0) -> str:
        scoreboard = ledger.summarize()
        return env.get_template("index.html").render(
            demo=bool(demo),
            scoreboard=asdict(scoreboard),
            decisions=scoreboard.decisions,
        )

    @app.post("/api/decide")
    def decide(body: DecideBody) -> JSONResponse:
        request = Request(
            prompt=body.prompt,
            modality=body.modality,
            aspect_ratio=body.aspect_ratio,
            style=body.style,
        )
        try:
            # Preview first: verdicts are free, only GENERATE spends. The cap
            # is checked BEFORE any generation is committed, so it binds.
            decision = gateway.preview(request)
            if decision.verdict is Verdict.GENERATE:
                used = generations_today()
                if used >= daily_generation_cap:
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"daily generation cap reached ({used}/"
                            f"{daily_generation_cap}); reuse and review still work"
                        ),
                    )
            result = gateway.handle(request)
        except HTTPException:
            raise
        except Exception as e:
            # Provider/storage failures surface verbatim (fallback-label lesson).
            raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
        return JSONResponse(_decision_view(result.decision, result))

    @app.get("/api/precheck")
    def precheck(prompt: str, modality: str = "image") -> dict[str, Any]:
        """Cap guard used by the UI before offering the generate action."""
        used = generations_today()
        return {
            "generations_today": used,
            "cap": daily_generation_cap,
            "generation_available": used < daily_generation_cap,
        }

    @app.post("/api/accept")
    def accept(body: AcceptBody) -> JSONResponse:
        # Rebuild the decision from the live library so acceptance can't book
        # a saving for an asset that no longer exists.
        request = Request(prompt=body.prompt, modality=body.modality)
        entries = gateway._library.scan()
        match = [e for e in entries if e.asset_id == body.asset_id]
        if not match:
            raise HTTPException(status_code=404, detail=f"asset {body.asset_id} not found")
        decision = Decision(
            verdict=Verdict.REVIEW,
            request=request,
            candidate=Candidate(entry=match[0], similarity=0.0, exact=False),
            reason="human accepted review candidate",
        )
        result = gateway.accept_review(decision)
        return JSONResponse(_decision_view(result.decision, result))

    @app.get("/api/scoreboard")
    def scoreboard() -> dict[str, Any]:
        s = ledger.summarize()
        return {**asdict(s), "decisions": s.decisions}

    return app


def build_production_app() -> FastAPI:
    """The deployment entrypoint: real B2, Gemini, ElevenLabs from env."""
    from genblaze_core.storage.base import ObjectLockConfig
    from genblaze_elevenlabs import ElevenLabsTTSProvider
    from genblaze_s3 import S3StorageBackend

    from reprise.embed import GeminiEmbedder
    from reprise.gemini_image import GeminiImageProvider

    backend = S3StorageBackend.for_backblaze()
    lock = ObjectLockConfig(retain_until=datetime(2026, 8, 15, tzinfo=UTC))
    ledger = Ledger(backend, prefix="reprise", lock=lock)
    gateway = Gateway(
        backend,
        GeminiEmbedder(),
        ledger,
        {
            "image": (GeminiImageProvider, "gemini-2.5-flash-image"),
            "audio": (ElevenLabsTTSProvider, "eleven_flash_v2_5"),
        },
        prefix="reprise",
    )
    cap = int(os.environ.get("REPRISE_DAILY_GENERATION_CAP", DEFAULT_DAILY_GENERATION_CAP))
    return create_app(gateway, ledger, daily_generation_cap=cap)
