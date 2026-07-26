"""Slice 7: the web app, tested through the app factory with the real
gateway/ledger stack on the in-memory backend (a real pipeline runs behind
the GENERATE path, same as test_gateway).

The tests after the divider are regressions for the BLOCKING findings of the
2026-07-26 security review: spend counted only after it happened, an uncapped
embedding path, and an unauthenticated accept that could forge savings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    # retain_days mirrors production: the app reads its lock state from the
    # ledger, so a test double without it would advertise a lock nobody writes.
    ledger = Ledger(
        backend, prefix="reprise", retain_days=30, clock=lambda: datetime.now(UTC)
    )
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
    assert "Already in your library" in client.get("/?demo=1").text


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

    token = mint_accept_token(
        "a1", PROMPT, expires_at=1000, secret=SECRET, review_id="r1"
    )
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


def test_exact_repeat_does_not_consume_decision_budget() -> None:
    """The free path must not be billed.

    An exact repeat is answered without any embedding call, so reserving the
    embed budget before knowing the verdict charged a paid quota for work that
    never happened, and let a burst of free lookups exhaust the cap that exists
    to bound paid ones.
    """
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT})  # seeds the library
    before = ledger.spend_reservations_today(("reserve_embed",))

    repeat = client.post("/api/decide", json={"prompt": PROMPT}).json()

    assert repeat["verdict"] == "reuse"
    assert ledger.spend_reservations_today(("reserve_embed",)) == before


def test_an_accept_token_cannot_be_replayed_to_inflate_savings() -> None:
    """One offer, one saving.

    The token proved the server offered this candidate, but nothing stopped the
    same token being posted repeatedly, each time writing another accept record
    into an object-locked ledger. Savings are the product's headline number and
    the ledger cannot be edited afterwards, so a replay is permanent inflation.
    """
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT})
    review = client.post("/api/decide", json={"prompt": NEAR}).json()
    body = {
        "prompt": NEAR,
        "modality": "image",
        "asset_id": review["candidate"]["asset_id"],
        "token": review["accept_token"],
    }

    assert client.post("/api/accept", json=body).status_code == 200
    replay = client.post("/api/accept", json=body)

    assert replay.status_code == 409
    assert ledger.summarize().accepts == 1
    assert ledger.summarize().saved_usd == 0.05


def test_every_result_carries_a_checkable_proof_receipt() -> None:
    """Judges (and users) must be able to check the provenance claim.

    The system knew the run id, the manifest key, the B2 object key, the digest
    and the manifest's canonical hash all along; none of it reached the
    response, so "every asset carries a provenance manifest" was a claim the UI
    asserted about itself. Each field here is one a viewer can re-derive from
    the bucket.
    """
    client, *_ = build()
    generated = client.post("/api/decide", json={"prompt": PROMPT}).json()
    reused = client.post("/api/decide", json={"prompt": PROMPT}).json()

    for body in (generated, reused):
        proof = body["proof"]
        assert proof["run_id"]
        assert proof["manifest_key"] == f"reprise/manifests/{proof['run_id']}.json"
        assert proof["asset_key"].startswith("reprise/assets/")
        assert len(proof["sha256"]) == 64
        assert len(proof["manifest_hash"]) == 64
        assert proof["object_lock"]["mode"] == "GOVERNANCE"
        assert proof["provider"] and proof["model"]


def test_generate_fresh_overrides_a_reuse_and_costs_generation_budget() -> None:
    """"Generate fresh instead" has to actually generate.

    It was an alert() stub, so the only choice a reviewer could really make was
    "accept". An override must reach the provider, book generation budget, and
    file a NEW asset rather than re-serving the one being rejected.
    """
    client, _, ledger, _ = build()
    client.post("/api/decide", json={"prompt": PROMPT}).json()
    embeds_before = ledger.spend_reservations_today(("reserve_embed",))

    fresh = client.post("/api/decide", json={"prompt": PROMPT, "force": True}).json()

    # Without force this exact prompt reuses; the override must reach the
    # provider instead. (Asset ids can repeat: identical bytes are meant to
    # land on one content-addressed key.)
    assert fresh["verdict"] == "generate"
    assert fresh["new_entry"] is not None
    assert ledger.summarize().generates == 2
    assert ledger.spend_reservations_today(("reserve_generate",)) == 2
    # The override skips the library entirely, so it must not pay to embed.
    assert ledger.spend_reservations_today(("reserve_embed",)) == embeds_before


def test_the_page_still_loads_when_the_ledger_cannot_be_read() -> None:
    """Storage trouble must not take down the whole surface.

    A Backblaze transaction cap made every ledger read fail, and because the
    homepage rendered the scoreboard inline, the page itself 500ed: a visitor
    could not even see what the product was. The scoreboard is derived state;
    the right degradation is to show it as unavailable, not to lose the app.
    """

    class DeadLedger(Ledger):
        def summarize(self) -> Any:
            raise RuntimeError("Class B transaction cap exceeded")

    backend = MemoryBackend()
    dead = DeadLedger(backend, prefix="reprise", retain_days=30)
    gw = Gateway(
        backend, CountingEmbedder(), dead,
        {"image": (mock_image_provider, "mock-image-v1")}, prefix="reprise",
    )
    client = TestClient(create_app(gw, dead, accept_secret=SECRET))

    r = client.get("/")

    assert r.status_code == 200
    assert "Reprise" in r.text


def test_readyz_fails_when_storage_cannot_be_read() -> None:
    """Liveness is not readiness.

    /healthz answers from process state, so it stayed 200 for the whole B2
    transaction-cap outage while every page that touched storage was down. A
    readiness probe has to actually read the store it depends on, and say so
    when it cannot.
    """
    client, backend, *_ = build()
    assert client.get("/readyz").status_code == 200

    def refuse(key: str) -> bytes:
        raise RuntimeError("Class B transaction cap exceeded")

    backend.get = refuse  # type: ignore[method-assign]
    backend.list = lambda *a, **k: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("Class B transaction cap exceeded")
    )

    r = client.get("/readyz")

    assert r.status_code == 503
    assert r.json()["storage"] == "unreadable"
