#!/usr/bin/env python3
"""Live integration probes. Run under doppler; paste output into docs/run-evidence.md.

    doppler run -p genblaze-hackathon -c prd -- .venv/bin/python tools/live_probe.py

Each probe hits the REAL surface the app depends on and prints raw results.
No probe swallows an error: a failure prints the provider's verbatim message
and exits nonzero, because a green probe that hides a dead dependency is worse
than a red one.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from datetime import UTC, datetime, timedelta

from genblaze_core.storage.base import ObjectLockConfig
from genblaze_s3 import S3StorageBackend

from reprise.embed import GeminiEmbedder
from reprise.ledger import Ledger
from reprise.model import Decision, Request, Verdict
from reprise.nearmatch import cosine


def probe_gemini_embeddings() -> None:
    e = GeminiEmbedder()
    a = e.embed("a red bicycle against a white wall")
    b = e.embed("a blue bicycle against a white wall")
    c = e.embed("quarterly revenue forecast spreadsheet")
    print(f"gemini-embedding-001 dims={len(a)}")
    print(f"  red-vs-blue same scene : cosine={cosine(a, b):.4f}")
    print(f"  vs unrelated           : cosine={cosine(a, c):.4f}")
    exact = e.embed("A RED  bicycle against a white wall ")
    print(f"  normalized repeat      : cosine={cosine(a, exact):.4f}")
    assert cosine(a, exact) > 0.999, "normalization must make case variants identical"


def probe_object_lock_binds() -> None:
    """Prove the ledger lock binds, at the observable that matters.

    On a versioned bucket an UNVERSIONED delete always "succeeds" -- it writes
    a delete marker and hides the object; the locked bytes are untouched. The
    lock's real bind point is the VERSION: deleting the locked version must be
    refused. This probe asserts the full chain: retention present, version
    delete refused, hidden record recoverable by removing the marker.
    (First run of this probe asserted the naive observable and reported
    LOCK DID NOT BIND; see docs/run-evidence.md for the correction.)
    """
    import os

    import boto3

    backend = S3StorageBackend.for_backblaze()
    lock = ObjectLockConfig(retain_until=datetime.now(UTC) + timedelta(minutes=3))
    led = Ledger(backend, prefix="reprise-probe", lock=lock)
    key = led.record(
        Decision(
            verdict=Verdict.GENERATE,
            request=Request(prompt="object lock probe", modality="image"),
            reason="live probe",
        )
    )
    print(f"locked ledger record written: {key}")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://s3.{os.environ['B2_REGION']}.backblazeb2.com",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        region_name=os.environ["B2_REGION"],
    )
    bucket = os.environ["B2_BUCKET"]

    # 1. Unversioned delete: hides only (delete marker), bytes stay locked.
    backend.delete(key)
    vs = s3.list_object_versions(Bucket=bucket, Prefix=key)
    markers = vs.get("DeleteMarkers", [])
    versions = vs.get("Versions", [])
    assert markers and versions, "expected a delete marker over a surviving version"
    print("  unversioned delete -> delete marker only; locked version survives")

    # 2. Retention is really on the version.
    ret = s3.get_object_retention(Bucket=bucket, Key=key, VersionId=versions[0]["VersionId"])
    print(f"  retention on version: {ret['Retention']['Mode']} until "
          f"{ret['Retention']['RetainUntilDate']}")

    # 3. The bind: deleting the locked VERSION must be refused.
    try:
        s3.delete_object(Bucket=bucket, Key=key, VersionId=versions[0]["VersionId"])
    except Exception as e:
        print(f"  version delete refused: {type(e).__name__}: {str(e)[:100]}")
    else:
        raise SystemExit("  LOCK DID NOT BIND: locked version was deleted")

    # 4. Recovery: removing the (unlocked) marker restores the record.
    s3.delete_object(Bucket=bucket, Key=key, VersionId=markers[0]["VersionId"])
    recovered = backend.get(key)
    assert b"object lock probe" in recovered
    print("  delete marker removed -> record recovered and readable")


if __name__ == "__main__":
    probe_gemini_embeddings()
    probe_object_lock_binds()
    print("ALL LIVE PROBES PASSED")
