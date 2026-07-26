"""The Reprise web app: judge-facing surface over the gateway.

Design constraints that shaped this module:

* **App factory** (`create_app(gateway, ledger)`) so tests inject an in-memory
  stack; `build_production_app()` wires the real B2 + Gemini + ElevenLabs
  stack from env and is what the deployment entrypoint imports.
* **Server-rendered** single page (Jinja): the demo-video pipeline captures
  SSR HTML, and a static `?demo=1` card renders with no gateway call at all.
* **Spend is reserved before it is spent.** This endpoint is unauthenticated
  and sits on real provider keys, so every billable path is counted BEFORE the
  money leaves: a reservation record is written first, and a reservation that
  cannot be written is treated as cap-exhausted (fail closed), never as
  permission to proceed. Two separate budgets exist because two separate
  resources cost money:
    - GENERATE   -> provider image/audio generation (the expensive one)
    - any decide -> an embedding call on caller-chosen text (the unbounded one)
  Capping only generation would leave an attacker free to bill unlimited
  embeddings by posting distinct prompts, so both are capped.
* **Acceptance is authenticated by capability.** A REVIEW response carries an
  HMAC token bound to (asset_id, prompt, expiry); `/api/accept` requires it.
  Without that, anyone could book savings for any asset id and permanently
  pollute an object-locked audit trail.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from reprise.embed import prompt_fingerprint
from reprise.gateway import Gateway, GatewayResult
from reprise.ledger import Ledger
from reprise.model import Candidate, Decision, LibraryEntry, Request, Verdict

log = logging.getLogger("reprise")

TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_DAILY_GENERATION_CAP = 25
DEFAULT_DAILY_DECISION_CAP = 400
ACCEPT_TOKEN_TTL_SEC = 1800
# Reads that scan the whole ledger are cached briefly: every unauthenticated
# request would otherwise cost O(ledger size) storage GETs, a cost an attacker
# can inflate simply by making the ledger longer.
READ_CACHE_TTL_SEC = 10.0


class DecideBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    modality: str = Field(default="image", pattern="^(image|audio)$")
    aspect_ratio: str | None = Field(default=None, max_length=32)
    style: str | None = Field(default=None, max_length=64)


class AcceptBody(BaseModel):
    """Accept a REVIEW candidate, proving the server offered it.

    Same input bounds as DecideBody: this route also writes an object-locked
    ledger record, so an unbounded prompt would mean unbounded undeletable
    storage written by an anonymous caller.
    """

    prompt: str = Field(min_length=1, max_length=2000)
    modality: str = Field(default="image", pattern="^(image|audio)$")
    asset_id: str = Field(min_length=1, max_length=200)
    token: str = Field(min_length=1, max_length=200)


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


def _accept_secret() -> bytes:
    """Key for accept-capability tokens.

    Prefers an explicit secret; otherwise derives a stable one from the B2
    application key. The derived value is a one-way digest that never leaves
    the server, and using it keeps the demo deployable without provisioning a
    second secret.
    """
    explicit = os.environ.get("REPRISE_ACCEPT_SECRET", "")
    if explicit:
        return explicit.encode()
    base = os.environ.get("B2_APP_KEY", "")
    if not base:
        raise RuntimeError("neither REPRISE_ACCEPT_SECRET nor B2_APP_KEY is set")
    return hashlib.sha256(b"reprise-accept-v1|" + base.encode()).digest()


def mint_accept_token(
    asset_id: str, prompt: str, *, expires_at: int, secret: bytes, review_id: str
) -> str:
    """Capability token: this server offered THIS asset for THIS prompt, once.

    `review_id` names the individual offer. It rides in the clear (the MAC
    covers it) so acceptance can be checked against the ledger for that exact
    offer, which is what makes a replayed token a detectable duplicate rather
    than a second saving.
    """
    payload = f"{asset_id}|{prompt_fingerprint(prompt)}|{expires_at}|{review_id}".encode()
    mac = hmac.new(secret, payload, hashlib.sha256).hexdigest()[:32]
    return f"{expires_at}.{review_id}.{mac}"


def review_id_from_token(token: str) -> str:
    """The offer id carried by a token. Empty when the token is malformed."""
    parts = token.split(".")
    return parts[1] if len(parts) == 3 else ""


def verify_accept_token(
    token: str, asset_id: str, prompt: str, *, secret: bytes, now: int
) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    exp_str, review_id, mac = parts
    if not mac or not exp_str.isdigit():
        return False
    if int(exp_str) < now:
        return False
    expected = mint_accept_token(
        asset_id, prompt, expires_at=int(exp_str), secret=secret, review_id=review_id
    )
    # Constant-time: token comparison must not leak via timing.
    return hmac.compare_digest(token, expected)


def create_app(
    gateway: Gateway,
    ledger: Ledger,
    *,
    daily_generation_cap: int = DEFAULT_DAILY_GENERATION_CAP,
    daily_decision_cap: int = DEFAULT_DAILY_DECISION_CAP,
    accept_secret: bytes | None = None,
    now: Callable[[], int] | None = None,
) -> FastAPI:
    app = FastAPI(title="Reprise", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )
    clock: Callable[[], int] = now or (lambda: int(time.time()))
    secret_holder: dict[str, bytes] = {}

    def secret() -> bytes:
        if "k" not in secret_holder:
            secret_holder["k"] = accept_secret or _accept_secret()
        return secret_holder["k"]

    cache: dict[str, tuple[float, Any]] = {}

    def cached(key: str, produce: Callable[[], Any]) -> Any:
        hit = cache.get(key)
        stamp = time.monotonic()
        if hit and stamp - hit[0] < READ_CACHE_TTL_SEC:
            return hit[1]
        value = produce()
        cache[key] = (stamp, value)
        return value

    def budget(kind: str, cap: int) -> None:
        """Reserve one unit of a daily budget, or refuse. Fails closed."""
        try:
            used = ledger.spend_reservations_today((kind,))
        except Exception as e:  # storage unreadable: cannot prove budget remains
            log.warning("budget read failed for %s: %s", kind, e)
            raise HTTPException(
                status_code=503, detail="spend budget unavailable, try later"
            ) from e
        if used >= cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"daily {kind.removeprefix('reserve_')} budget reached "
                    f"({used}/{cap}); free paths still work"
                ),
            )
        try:
            ledger.reserve_spend("budget", kind)
        except Exception as e:  # cannot record the intent: do NOT spend
            log.warning("reservation write failed for %s: %s", kind, e)
            raise HTTPException(
                status_code=503, detail="could not reserve spend budget"
            ) from e
        cache.pop(f"used:{kind}", None)

    def fail(e: Exception) -> HTTPException:
        """Log the real error; return a correlation id, not internals."""
        cid = uuid.uuid4().hex[:12]
        log.exception("request %s failed: %s", cid, e)
        return HTTPException(status_code=502, detail=f"upstream error (reference {cid})")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "app": "reprise"}

    @app.get("/", response_class=HTMLResponse)
    def index(demo: int = 0) -> str:
        board = cached("scoreboard", ledger.summarize)
        return env.get_template("index.html").render(
            demo=bool(demo),
            scoreboard=asdict(board),
            decisions=board.decisions,
        )

    @app.post("/api/decide")
    def decide(body: DecideBody) -> JSONResponse:
        request = Request(
            prompt=body.prompt,
            modality=body.modality,
            aspect_ratio=body.aspect_ratio,
            style=body.style,
        )
        # A decide that has to embed caller-chosen text costs money whether or
        # not anything is generated, so the budget is reserved at the moment the
        # gateway is about to make that call and not before: an exact repeat is
        # answered for free and must not consume a paid quota. The HTTPException
        # a refusal raises propagates out of the hook, so the embedding never
        # happens.
        try:
            decision = gateway.preview(
                request, before_embed=lambda: budget("reserve_embed", daily_decision_cap)
            )
        except HTTPException:
            raise
        except Exception as e:
            raise fail(e) from e

        if decision.verdict is Verdict.GENERATE:
            # Reserved BEFORE the provider call, so a spend can never go
            # uncounted even if the outcome record later fails to write.
            budget("reserve_generate", daily_generation_cap)

        try:
            # Reuse the preview decision: re-deciding would repeat the library
            # scan and pay for a second embedding of the same prompt.
            result = gateway.handle(request, decision=decision)
        except Exception as e:
            raise fail(e) from e

        view = _decision_view(result.decision, result)
        if result.decision.verdict is Verdict.REVIEW and result.decision.candidate:
            view["accept_token"] = mint_accept_token(
                result.decision.candidate.entry.asset_id,
                body.prompt,
                expires_at=clock() + ACCEPT_TOKEN_TTL_SEC,
                secret=secret(),
                review_id=uuid.uuid4().hex[:16],
            )
        cache.pop("scoreboard", None)
        return JSONResponse(view)

    @app.get("/api/precheck")
    def precheck() -> dict[str, Any]:
        """Remaining daily budgets (prompt-independent, by construction)."""
        gen = cached(
            "used:reserve_generate",
            lambda: ledger.spend_reservations_today(("reserve_generate",)),
        )
        dec = cached(
            "used:reserve_embed",
            lambda: ledger.spend_reservations_today(("reserve_embed",)),
        )
        return {
            "generations_today": gen,
            "generation_cap": daily_generation_cap,
            "generation_available": gen < daily_generation_cap,
            "decisions_today": dec,
            "decision_cap": daily_decision_cap,
        }

    @app.post("/api/accept")
    def accept(body: AcceptBody) -> JSONResponse:
        if not verify_accept_token(
            body.token, body.asset_id, body.prompt, secret=secret(), now=clock()
        ):
            raise HTTPException(
                status_code=403,
                detail="invalid or expired accept token; re-run the check first",
            )
        review_id = review_id_from_token(body.token)
        try:
            already = ledger.accepted_review_ids()
        except Exception as e:  # cannot prove this offer is unspent: refuse
            raise fail(e) from e
        if review_id in already:
            raise HTTPException(
                status_code=409,
                detail="this review was already accepted; re-run the check to decide again",
            )
        try:
            entries = gateway.library.scan()
        except Exception as e:
            raise fail(e) from e
        match = [e for e in entries if e.asset_id == body.asset_id]
        if not match:
            raise HTTPException(status_code=404, detail="asset not found")
        decision = Decision(
            verdict=Verdict.REVIEW,
            request=Request(prompt=body.prompt, modality=body.modality),
            candidate=Candidate(entry=match[0], similarity=0.0, exact=False),
            reason="human accepted review candidate",
        )
        try:
            result = gateway.accept_review(decision, review_id=review_id)
        except Exception as e:
            raise fail(e) from e
        cache.pop("scoreboard", None)
        return JSONResponse(_decision_view(result.decision, result))

    @app.get("/api/scoreboard")
    def scoreboard() -> dict[str, Any]:
        s = cached("scoreboard", ledger.summarize)
        return {**asdict(s), "decisions": s.decisions}

    return app


def build_production_app() -> FastAPI:
    """The deployment entrypoint: real B2, Gemini, ElevenLabs from env."""
    from genblaze_elevenlabs import ElevenLabsTTSProvider
    from genblaze_s3 import S3StorageBackend

    from reprise.embed import GeminiEmbedder
    from reprise.gemini_image import GeminiImageProvider

    backend = S3StorageBackend.for_backblaze()
    retain_days = int(os.environ.get("REPRISE_LEDGER_RETAIN_DAYS", "30"))
    # Pass the WINDOW, not a computed horizon: the Ledger measures retention
    # from each write. A horizon computed here would be fixed at process boot
    # and would age with a warm serverless instance, eventually writing no real
    # protection while the UI still advertised an object-locked ledger.
    ledger = Ledger(backend, prefix="reprise", retain_days=retain_days)
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
    return create_app(
        gateway,
        ledger,
        daily_generation_cap=int(
            os.environ.get("REPRISE_DAILY_GENERATION_CAP", DEFAULT_DAILY_GENERATION_CAP)
        ),
        daily_decision_cap=int(
            os.environ.get("REPRISE_DAILY_DECISION_CAP", DEFAULT_DAILY_DECISION_CAP)
        ),
    )
