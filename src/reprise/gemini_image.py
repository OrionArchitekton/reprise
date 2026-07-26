"""A custom Genblaze provider for Gemini-native image generation.

Why this exists (recorded verbatim in docs/run-evidence.md, 2026-07-26): the
stock ``genblaze-google`` connector's image family matches ``^imagen-`` only,
and every Imagen tier now answers ``404 ... no longer available to new users``
for fresh Gemini API keys. The models new keys CAN use (``gemini-2.5-flash-
image`` and the gemini-3.x image line) speak ``generateContent`` and return
inline bytes -- a different wire shape the connector does not cover. This is
exactly the seam Genblaze's provider system is for: implement ``SyncProvider.
generate()``, and the pipeline, sink, manifest, and provenance machinery all
work unchanged. (Also filed as SDK feedback -- the connector's family list
strands new-key users.)

The provider writes returned bytes to a temp file and hands the sink a
``file://`` asset with sha256/size prefilled; ObjectStorageSink re-hashes and
transfers to B2, so the manifest's digests are computed from the bytes that
were actually stored.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from genblaze_core import Asset, ProviderError, ProviderErrorCode
from genblaze_core.models.step import Step
from genblaze_core.providers.base import SyncProvider  # deep import: typed (issue #55)
from genblaze_core.runnable.config import RunnableConfig

# $30 / 1M output tokens, 1290 tokens per image (Gemini pricing page,
# checked 2026-07-26) -> $0.0387 per generated image.
COST_PER_IMAGE_USD = 0.0387

# Transport seam for tests: (url, body, headers, timeout) -> parsed JSON.
Transport = Callable[[str, bytes, dict[str, str], float], dict[str, Any]]


def _urllib_transport(
    url: str, body: bytes, headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)  # type: ignore[no-any-return]


class GeminiImageProvider(SyncProvider):
    """Image generation via Gemini ``generateContent`` (inline PNG bytes)."""

    name = "gemini-image"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        output_dir: str | Path | None = None,
        timeout: float = 120.0,
        transport: Transport | None = None,
    ) -> None:
        super().__init__()
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set", error_code=ProviderErrorCode.AUTH_FAILURE
            )
        self._output_dir = Path(output_dir) if output_dir else None
        self._timeout = timeout
        self._transport = transport or _urllib_transport

    def generate(self, step: Step, config: RunnableConfig | None = None) -> Step:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{step.model}:generateContent"
        )
        body = json.dumps(
            {"contents": [{"parts": [{"text": step.prompt or ""}]}]}
        ).encode()
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        try:
            payload = self._transport(url, body, headers, self._timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            code = (
                ProviderErrorCode.MODEL_ERROR
                if e.code == 404
                else ProviderErrorCode.UNKNOWN
            )
            # The upstream message rides along verbatim; a generic label here
            # once hid a dead model id for hours in another build.
            raise ProviderError(
                f"Gemini generateContent HTTP {e.code}: {detail}", error_code=code
            ) from e
        except OSError as e:
            raise ProviderError(
                f"Gemini generateContent unreachable: {e}",
                error_code=ProviderErrorCode.UNKNOWN,
            ) from e

        images = self._extract_images(payload)
        if not images:
            raise ProviderError(
                "Gemini returned no inline image data: "
                + json.dumps(payload)[:300],
                error_code=ProviderErrorCode.INVALID_INPUT,
            )

        out_dir = self._output_dir or Path(tempfile.mkdtemp(prefix="gemini-img-"))
        out_dir.mkdir(parents=True, exist_ok=True)
        for idx, (mime, data) in enumerate(images):
            ext = mime.rsplit("/", 1)[-1] or "png"
            sha = hashlib.sha256(data).hexdigest()
            path = out_dir / f"{step.step_id}-{idx}.{ext}"
            path.write_bytes(data)
            step.assets.append(
                Asset(
                    asset_id=f"{step.step_id}-img-{idx}",
                    url=path.as_uri(),
                    media_type=mime,
                    sha256=sha,
                    size_bytes=len(data),
                )
            )
        step.cost_usd = COST_PER_IMAGE_USD * len(images)
        return step

    @staticmethod
    def _extract_images(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for cand in payload.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    out.append(
                        (
                            inline.get("mimeType", "image/png"),
                            base64.b64decode(inline["data"]),
                        )
                    )
        return out
