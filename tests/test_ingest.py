"""Slice 2: manifest ingest.

The library is not a separate database to maintain -- it is a *view over the
provenance manifests* Genblaze already writes to B2. Ingest turns one manifest
into zero or more LibraryEntry rows, and its correctness rules mirror
`Manifest.verify()` semantics: only completed steps with sha256-bound assets
are reusable. A failure manifest is valuable for debugging, but nothing in it
may ever be served to a customer.
"""

from __future__ import annotations

from typing import Any

from reprise.ingest import entries_from_manifest

BUCKET_URL = "https://s3.us-west-004.backblazeb2.com/reprise-vault-9315d5"
SHA = "b1ff9c8ea3a780bad09b346c423d2d0e46815926879b18e841d928376a946640"


def manifest_dict(**over: Any) -> dict[str, Any]:
    """A realistic sink-written manifest, shaped like the real one in B2.

    Mirrors run f262d532 from docs/run-evidence.md: one completed image step,
    one sha256-bound asset whose URL points into the bucket.
    """
    base: dict[str, Any] = {
        "schema_version": "1.6",
        "canonical_hash": "4bc2e64f572895a14dbd66eab68261725da516028a2edd29c9214fb49a0b1a21",
        "manifest_uri": None,
        "encryption_scheme": None,
        "signature": None,
        "transfer_failures": [],
        "run": {
            "run_id": "f262d532-c38c-40f9-8b94-c0b8dd14740e",
            "tenant_id": None,
            "project_id": "reprise",
            "name": "reprise-b2-proof",
            "status": "completed",
            "parent_run_id": None,
            "idempotency_key": None,
            "created_at": "2026-07-26T15:20:00.000000Z",
            "started_at": "2026-07-26T15:20:00.000000Z",
            "completed_at": "2026-07-26T15:20:01.000000Z",
            "metadata": {},
            "steps": [
                {
                    "step_id": "step-1",
                    "run_id": "f262d532-c38c-40f9-8b94-c0b8dd14740e",
                    "provider": "mock",
                    "model": "mock-image-v1",
                    "step_type": "generate",
                    "model_version": None,
                    "model_hash": None,
                    "modality": "image",
                    "prompt": "a red bicycle against a white wall",
                    "negative_prompt": None,
                    "prompt_visibility": "public",
                    "seed": None,
                    "params": {},
                    "status": "succeeded",
                    "inputs": [],
                    "assets": [
                        {
                            "asset_id": "mock-red",
                            "url": f"{BUCKET_URL}/reprise/assets/b1/ff/{SHA}.png",
                            "media_type": "image/png",
                            "sha256": SHA,
                            "size_bytes": 69,
                            "width": 1024,
                            "height": 1024,
                            "duration": None,
                            "video": None,
                            "audio": None,
                            "tracks": None,
                            "metadata": {},
                        }
                    ],
                    "provider_payload": {},
                    "retries": 0,
                    "cost_usd": 0.042,
                    "error": None,
                    "error_code": None,
                    "started_at": "2026-07-26T15:20:00.100000Z",
                    "completed_at": "2026-07-26T15:20:00.900000Z",
                    "step_index": 0,
                    "metadata": {"aspect_ratio": "1:1", "style": "photo"},
                }
            ],
        },
    }
    base.update(over)
    return base


def test_completed_step_yields_one_entry() -> None:
    entries = entries_from_manifest(manifest_dict())

    assert len(entries) == 1
    e = entries[0]
    assert e.asset_id == "mock-red"
    assert e.prompt == "a red bicycle against a white wall"
    assert e.modality == "image"
    assert e.sha256 == SHA
    # storage_key is the BUCKET key, never the full URL: presigned/rotating URL
    # forms must not leak into the library (genblaze object-storage doc rule).
    assert e.storage_key == f"reprise/assets/b1/ff/{SHA}.png"
    assert e.cost_usd == 0.042
    assert e.provider == "mock"
    assert e.model == "mock-image-v1"
    assert e.run_id == "f262d532-c38c-40f9-8b94-c0b8dd14740e"
    # constraints come from step metadata, where our pipeline wrapper puts them
    assert e.aspect_ratio == "1:1"
    assert e.style == "photo"
    assert e.embedding is None


def test_failed_step_yields_nothing() -> None:
    m = manifest_dict()
    m["run"]["steps"][0]["status"] = "failed"
    m["run"]["steps"][0]["error"] = "provider exploded"

    assert entries_from_manifest(m) == []


def test_asset_without_sha256_is_not_reusable() -> None:
    """URL-only assets fail Manifest.verify(); they must fail ingest too."""
    m = manifest_dict()
    m["run"]["steps"][0]["assets"][0]["sha256"] = None

    assert entries_from_manifest(m) == []


def test_missing_constraint_metadata_derives_ratio_from_dimensions() -> None:
    """Manifests written outside our wrapper still ingest.

    aspect_ratio falls back to reduced width:height; style stays None rather
    than being guessed -- an absent style then simply hard-filters against
    styled requests, which is the safe direction.
    """
    m = manifest_dict()
    m["run"]["steps"][0]["metadata"] = {}
    m["run"]["steps"][0]["assets"][0]["width"] = 1920
    m["run"]["steps"][0]["assets"][0]["height"] = 1080

    (e,) = entries_from_manifest(m)

    assert e.aspect_ratio == "16:9"
    assert e.style is None


def test_step_without_prompt_yields_nothing() -> None:
    """No prompt means nothing to match on: composite/ingest steps are skipped."""
    m = manifest_dict()
    m["run"]["steps"][0]["prompt"] = None

    assert entries_from_manifest(m) == []


def test_multi_asset_step_yields_one_entry_per_asset() -> None:
    m = manifest_dict()
    a2 = dict(m["run"]["steps"][0]["assets"][0])
    a2["asset_id"] = "mock-red-2"
    sha2 = "c" * 64
    a2["sha256"] = sha2
    a2["url"] = f"{BUCKET_URL}/reprise/assets/cc/cc/{sha2}.png"
    m["run"]["steps"][0]["assets"].append(a2)

    entries = entries_from_manifest(m)

    assert [e.asset_id for e in entries] == ["mock-red", "mock-red-2"]
    assert entries[1].storage_key == f"reprise/assets/cc/cc/{sha2}.png"
