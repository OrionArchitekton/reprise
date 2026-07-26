"""Slice 7: the web app, tested through the app factory with the real
gateway/ledger stack on the in-memory backend (a real pipeline runs behind
the GENERATE path, same as test_gateway).

The tests after the divider are regressions for the BLOCKING findings of the
2026-07-26 security review: spend counted only after it happened, an uncapped
embedding path, and an unauthenticated accept that could forge savings.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reprise.gateway import Gateway
from reprise.ledger import Ledger
from reprise.webapp import create_app
from tests.test_gateway import CountingEmbedder, mock_image_provider
from tests.test_library import MemoryBackend

SECRET = b"test-secret"
PROMPT = "a red bicycle against a white wall"
NEAR = "a blue bicycle against a white wall"


def build(
    cap: int = 25, decision_cap: int = 400, embedder: CountingEmbedder | None = None
) -> tuple[TestClient, MemoryBackend, Ledger, Gateway]:
    backend = MemoryBackend()
    ledger = Ledger(backend, prefix="reprise", clock=lambda: datetime.now(UTC))
    gw = Gateway(
        backend,
        embedder or CountingEmbedder(),
        ledger,
        {"image": (mock_image_provider, "mock-image-v1")},
        prefix="reprise",
    )
    app = create_app(
        gw,
        ledger,
        daily_generation_cap=cap,
        daily_decision_cap=decision_cap,
        accept_secret=SECRET,
    )
    return TestClient(app), backend, ledger, gw


def test_healthz() -> None:
    client, *_ = build()
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["app"] == "reprise"


def test_index_renders_scoreboard() -> None:
    client, *_ = build()
    r = client.get("/")
    assert r.status_code == 200 and "Reprise" in r.text and "decisions" in r.text


def test_demo_mode_renders_static_card() -> None:
    client, *_ = build()
    assert "You already own this" in client.get("/?demo=1").text


def test_decide_generate_then_reuse_roundtrip() -> None:
    client, *_ = build()

    r1 = client.post("/api/decide", json={"prompt": PROMPT})
    assert r1.status_code == 200
    assert r1.json()["verdict"] == "generate"
    assert r1.json()["new_entry"]["cost_usd"] == 0.05

    body = client.post("/api/decide", json={"prompt": PROMPT.upper()}).json()
    assert body["verdict"] == "reuse"
    assert body["saved_usd"] == 0.05
    # Containment holds: the served key is inside our asset tree.
    assert "/bucket/reprise/assets/" in body["serve_url"]

    s = client.get("/api/scoreboard").json()
    assert (s["reuses"], s["generates"], s["saved_usd"]) == (1, 1, 0.05)


def test_invalid_modality_rejected() -> None:
    client, *_ = build()
    assert client.post(
        "/api/decide", json={"prompt": "x", "modality": "video"}
    ).status_code == 422


def test_oversized_prompt_rejected_before_any_spend() -> None:
    client, _, ledger, _ = build()
    assert client.post("/api/decide", json={"prompt": "x" * 2001}).status_code == 422
    assert ledger.spend_reservations_today(("reserve_embed",)) == 0


# --- BLOCKING regressions -------------------------------------------------


def test_generation_is_reserved_before_spend_not_after() -> None:
    """A generation must be counted even if its outcome record never lands.

    Previously the cap counted ledger GENERATE records written AFTER the
    provider call, so a failed ledger write meant money spent and never
    counted, freezing the counter while the cap stayed open.
    """
    client, _, ledger, _ = build(cap=5)

    client.post("/api/decide", json={"prompt": PROMPT})

    assert ledger.spend_reservations_today(("reserve_generate",)) == 1
    assert client.get("/api/precheck").json()["generations_today"] == 1


def test_generation_cap_binds_and_reuse_still_works() -> None:
    client, *_ = build(cap=1)

    assert client.post("/api/decide", json={"prompt": PROMPT}).status_code == 200

    r = client.post(
        "/api/decide", json={"prompt": "quarterly revenue forecast spreadsheet"}
    )
    assert r.status_code == 429 and "generate budget reached" in r.json()["detail"]

    r2 = client.post("/api/decide", json={"prompt": PROMPT})
    assert r2.status_code == 200 and r2.json()["verdict"] == "reuse"


def test_embedding_spend_is_capped_independently_of_generation() -> None:
    """Denial of wallet: distinct prompts bill embeddings even when nothing
    is generated, so the decision budget must bind on its own."""
    client, *_ = build(cap=99, decision_cap=2)

    assert client.post("/api/decide", json={"prompt": PROMPT}).status_code == 200
    assert client.post("/api/decide", json={"prompt": "a lighthouse"}).status_code == 200

    r = client.post("/api/decide", json={"prompt": "a third distinct prompt"})
    assert r.status_code == 429 and "embed budget reached" in r.json()["detail"]


def test_decide_embeds_the_request_once_not_twice() -> None:
    """preview + handle must not each pay to embed the same prompt."""
    embedder = CountingEmbedder()
    client, *_ = build(embedder=embedder)
    client.post("/api/decide", json={"prompt": PROMPT})  # seed the library
    embedder.calls = 0

    client.post("/api/decide", json={"prompt": NEAR})

    # One request embed + one library-sidecar embed. Three would mean the
    # request was embedded twice (preview and handle both deciding).
    assert embedder.calls == 2


def test_accept_requires_a_valid_server_issued_token() -> None:
    """Forging savings must be impossible: without the token from a REVIEW
    response there is no ledger record and no presigned URL."""
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT})
    review = client.post("/api/decide", json={"prompt": NEAR}).json()

    forged = client.post(
        "/api/accept",
        json={
            "prompt": NEAR,
            "modality": "image",
            "asset_id": review["candidate"]["asset_id"],
            "token": "9999999999." + "de" * 16,
        },
    )

    assert forged.status_code == 403
    assert ledger.summarize().saved_usd == 0.0


def test_accept_token_is_bound_to_its_prompt() -> None:
    client, *_ = build()
    client.post("/api/decide", json={"prompt": PROMPT})
    review = client.post("/api/decide", json={"prompt": NEAR}).json()

    r = client.post(
        "/api/accept",
        json={
            "prompt": "an entirely different prompt",
            "modality": "image",
            "asset_id": review["candidate"]["asset_id"],
            "token": review["accept_token"],
        },
    )
    assert r.status_code == 403


def test_expired_accept_token_is_refused() -> None:
    from reprise.webapp import mint_accept_token, verify_accept_token

    token = mint_accept_token("a1", PROMPT, expires_at=1000, secret=SECRET)
    assert verify_accept_token(token, "a1", PROMPT, secret=SECRET, now=999)
    assert not verify_accept_token(token, "a1", PROMPT, secret=SECRET, now=1001)


def test_review_accept_flow_books_saving_with_the_issued_token() -> None:
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT})
    review = client.post("/api/decide", json={"prompt": NEAR}).json()
    assert review["verdict"] == "review"

    a = client.post(
        "/api/accept",
        json={
            "prompt": NEAR,
            "modality": "image",
            "asset_id": review["candidate"]["asset_id"],
            "token": review["accept_token"],
        },
    )

    assert a.status_code == 200
    assert ledger.summarize().saved_usd == 0.05


def test_accept_response_reports_the_saving_the_ledger_booked() -> None:
    """The card a user sees must not understate what the ledger recorded.

    The response was built from the REVIEW decision, whose saved_usd is 0.0 by
    construction, while record_accept books the candidate's cost. The two
    surfaces disagreed: "Saved $0.00" on screen over a $0.05 ledger record.
    """
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT})
    review = client.post("/api/decide", json={"prompt": NEAR}).json()

    accepted = client.post(
        "/api/accept",
        json={
            "prompt": NEAR,
            "modality": "image",
            "asset_id": review["candidate"]["asset_id"],
            "token": review["accept_token"],
        },
    ).json()

    assert accepted["saved_usd"] == review["candidate"]["cost_usd"] > 0
    assert accepted["saved_usd"] == ledger.summarize().saved_usd


def test_upstream_errors_do_not_leak_internals() -> None:
    """The 502 body must carry a correlation id, not the exception text."""

    class ExplodingEmbedder(CountingEmbedder):
        def embed(self, prompt: str) -> tuple[float, ...]:
            raise RuntimeError("ClientError: bucket reprise-vault-9315d5 endpoint")

    client, *_ = build(embedder=ExplodingEmbedder())

    r = client.post("/api/decide", json={"prompt": "something novel entirely"})

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "reference" in detail
    assert "reprise-vault" not in detail and "ClientError" not in detail


def test_serving_outside_the_asset_prefix_is_refused() -> None:
    """A manifest pointing outside reprise/assets/ must never be presigned."""
    _, _, _, gw = build()
    with pytest.raises(ValueError, match="refusing to serve"):
        gw._serve_url("reprise/ledger/some-record.json")
