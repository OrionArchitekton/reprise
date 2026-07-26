"""Turn Genblaze provenance manifests into library entries.

The asset library is not a second source of truth. Genblaze's ObjectStorageSink
already writes a canonical manifest next to every asset it stores in B2; the
library is a projection of those manifests, and this module is the projection.

Admission is gated on `Manifest.verify_hash()`: a manifest whose payload no
longer matches its canonical hash is refused ENTIRELY, assets and all. That is
the trust boundary of the product. Reuse is only safe if the manifest
describing an asset is the one Genblaze wrote; without this gate, editing the
prompt on a stored run would point a popular prompt at bytes of the editor's
choosing and Reprise would serve them as "already owned".

The hash is the hard gate; the rules below stay per-asset filters. Using the
stricter `verify()` for admission would let one URL-only asset disqualify a
run's other, properly bound assets, which throws away reusable work for no
gain in safety.

Reusability rules mirror `Manifest.verify()` semantics deliberately:

* only SUCCEEDED steps count (the SDK's StepStatus vocabulary; runs say
  "completed", steps say "succeeded") -- failure manifests are kept in the
  bucket for debugging, but nothing in them is servable;
* only sha256-bound assets count -- a URL-only asset cannot be byte-verified at
  serve time, so it cannot be reused (same rule that makes `verify()` fail);
* only prompted steps count -- a composite/ingest step has no prompt to match.

Anything skipped here is skipped silently by design: ingest runs over every
manifest in the bucket, and most buckets contain runs Reprise did not create.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlparse

from genblaze_core import Manifest, parse_manifest

from reprise.model import LibraryEntry


def entries_from_manifest(data: dict[str, Any] | Manifest) -> list[LibraryEntry]:
    """Project one manifest into zero or more reusable library entries."""
    manifest = data if isinstance(data, Manifest) else parse_manifest(data)
    if not manifest.verify_hash():
        return []
    run = manifest.run

    entries: list[LibraryEntry] = []
    for step in run.steps:
        if step.status.value != "succeeded" or not step.prompt:
            continue
        aspect_meta = step.metadata.get("aspect_ratio")
        style_meta = step.metadata.get("style")
        for asset in step.assets:
            if not asset.sha256:
                continue
            entries.append(
                LibraryEntry(
                    asset_id=asset.asset_id,
                    prompt=step.prompt,
                    modality=step.modality.value,
                    sha256=asset.sha256,
                    storage_key=_storage_key(asset.url),
                    cost_usd=step.cost_usd or 0.0,
                    provider=step.provider or "unknown",
                    model=step.model,
                    run_id=run.run_id,
                    created_at=run.created_at,
                    aspect_ratio=aspect_meta or _ratio(asset.width, asset.height),
                    style=style_meta,
                )
            )
    return entries


def _storage_key(url: str) -> str:
    """Reduce an asset URL to its bucket key.

    Sink-written URLs look like
    ``https://s3.<region>.backblazeb2.com/<bucket>/<key...>``; the key is the
    path minus the bucket segment. Presigned query strings are dropped: rotating
    URL forms must never be persisted (genblaze object-storage doctrine), and
    the key is stable where the URL is not.
    """
    path = urlparse(url).path.lstrip("/")
    _, _, key = path.partition("/")
    return key or path


def _ratio(width: int | None, height: int | None) -> str | None:
    """Reduce pixel dimensions to a canonical aspect ratio like ``16:9``."""
    if not width or not height:
        return None
    g = math.gcd(width, height)
    return f"{width // g}:{height // g}"
