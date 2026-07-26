"""Slice 7: the web app, tested through the app factory with the real
gateway/ledger stack on the in-memory backend (a real pipeline runs behind
the GENERATE path, same as test_gateway)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reprise.gateway import Gateway
from reprise.ledger import Ledger
from reprise.webapp import create_app
from tests.test_gateway import CountingEmbedder, mock_image_provider
from tests.test_library import MemoryBackend


def make_client(cap: int = 25) -> tuple[TestClient, MemoryBackend]:
    backend = MemoryBackend()
    ledger = Ledger(backend, prefix="reprise", clock=lambda: datetime.now(UTC))
    gw = Gateway(
        backend,
        CountingEmbedder(),
        ledger,
        {"image": (mock_image_provider, "mock-image-v1")},
        prefix="reprise",
    )
    app = create_app(gw, ledger, daily_generation_cap=cap)
    return TestClient(app), backend


def test_healthz() -> None:
    client, _ = make_client()
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["app"] == "reprise"


def test_index_renders_scoreboard() -> None:
    client, _ = make_client()
    r = client.get("/")
    assert r.status_code == 200
    assert "Reprise" in r.text and "decisions" in r.text


def test_demo_mode_renders_static_card_without_backend_calls() -> None:
    client, _ = make_client()
    r = client.get("/?demo=1")
    assert "You already own this" in r.text


def test_decide_generate_then_reuse_roundtrip() -> None:
    client, _backend = make_client()

    r1 = client.post("/api/decide", json={"prompt": "a red bicycle against a white wall"})
    assert r1.status_code == 200
    assert r1.json()["verdict"] == "generate"
    assert r1.json()["new_entry"]["cost_usd"] == 0.05

    r2 = client.post("/api/decide", json={"prompt": "A RED bicycle against a white wall"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["verdict"] == "reuse"
    assert body["saved_usd"] == 0.05
    assert body["serve_url"].startswith("memory://")

    s = client.get("/api/scoreboard").json()
    assert s["reuses"] == 1 and s["generates"] == 1
    assert s["saved_usd"] == 0.05


def test_generation_cap_binds_with_429_but_reuse_still_works() -> None:
    client, _ = make_client(cap=1)

    assert client.post(
        "/api/decide", json={"prompt": "a red bicycle against a white wall"}
    ).status_code == 200

    # Cap of 1 reached: a novel prompt (far outside the review band) must 429...
    r = client.post(
        "/api/decide", json={"prompt": "quarterly revenue forecast spreadsheet"}
    )
    assert r.status_code == 429
    assert "cap" in r.json()["detail"]

    # ...while an exact repeat still reuses for free.
    r2 = client.post(
        "/api/decide", json={"prompt": "a red bicycle against a white wall"}
    )
    assert r2.status_code == 200 and r2.json()["verdict"] == "reuse"


def test_review_accept_flow_books_saving() -> None:
    client, _ = make_client()
    client.post("/api/decide", json={"prompt": "a red bicycle against a white wall"})

    r = client.post("/api/decide", json={"prompt": "a blue bicycle against a white wall"})
    assert r.json()["verdict"] == "review"
    asset_id = r.json()["candidate"]["asset_id"]

    a = client.post(
        "/api/accept",
        json={
            "prompt": "a blue bicycle against a white wall",
            "modality": "image",
            "asset_id": asset_id,
        },
    )
    assert a.status_code == 200
    assert client.get("/api/scoreboard").json()["saved_usd"] == 0.05


def test_accept_unknown_asset_is_404() -> None:
    client, _ = make_client()
    r = client.post(
        "/api/accept",
        json={"prompt": "x", "modality": "image", "asset_id": "nope"},
    )
    assert r.status_code == 404


def test_invalid_modality_rejected() -> None:
    client, _ = make_client()
    r = client.post("/api/decide", json={"prompt": "x", "modality": "video"})
    assert r.status_code == 422
