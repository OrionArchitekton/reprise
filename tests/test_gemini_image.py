"""Custom Gemini image provider: unit tests via the transport seam.

The live path (real generateContent, real B2 persistence) is proven by
tools/live_generate.py; these tests pin the parsing, error, and asset
contracts without network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
from typing import Any

import pytest
from genblaze_core import MockProvider, Pipeline, ProviderError
from genblaze_core.models.step import Step

from reprise.gemini_image import GeminiImageProvider

PNG = b"\x89PNG\r\n\x1a\nfakebytes"


def ok_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    assert "gemini-2.5-flash-image:generateContent" in url
    assert headers["x-goog-api-key"] == "k"
    prompt = json.loads(body)["contents"][0]["parts"][0]["text"]
    assert prompt  # normalized prompt rides through
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "here is your image"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(PNG).decode(),
                            }
                        },
                    ]
                }
            }
        ]
    }


def run_step(provider: GeminiImageProvider) -> Step:
    result = (
        Pipeline("t")
        .step(provider, model="gemini-2.5-flash-image", prompt="a red bicycle", modality="image")
        .run(raise_on_failure=True)
    )
    return result.run.steps[0]  # type: ignore[no-any-return]


def test_inline_image_becomes_a_hashed_file_asset(tmp_path: Any) -> None:
    p = GeminiImageProvider(api_key="k", output_dir=tmp_path, transport=ok_transport)

    step = run_step(p)

    (asset,) = step.assets
    assert asset.url.startswith("file://")
    assert asset.media_type == "image/png"
    assert asset.sha256 == hashlib.sha256(PNG).hexdigest()
    assert asset.size_bytes == len(PNG)
    assert step.cost_usd == pytest.approx(0.0387)


def test_http_error_carries_upstream_message_verbatim(tmp_path: Any) -> None:
    def transport_404(
        url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        raise urllib.error.HTTPError(
            url, 404, "Not Found", None,  # type: ignore[arg-type]
            __import__("io").BytesIO(b'{"error":{"message":"model retired for new users"}}'),
        )

    p = GeminiImageProvider(api_key="k", output_dir=tmp_path, transport=transport_404)

    with pytest.raises(ProviderError, match="model retired for new users"):
        p.generate(_bare_step())


def test_no_inline_data_is_a_provider_error(tmp_path: Any) -> None:
    def transport_textonly(
        url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        return {"candidates": [{"content": {"parts": [{"text": "no image, sorry"}]}}]}

    p = GeminiImageProvider(api_key="k", output_dir=tmp_path, transport=transport_textonly)

    with pytest.raises(ProviderError, match="no inline image data"):
        p.generate(_bare_step())


def test_missing_key_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiImageProvider(api_key="")


def _bare_step() -> Step:
    # Cheapest way to get a well-formed Step: run a mock pipeline and reuse its
    # step shell (prompt/model/modality populated, assets empty).
    result = (
        Pipeline("shell")
        .step(MockProvider(), model="gemini-2.5-flash-image", prompt="a red bicycle")
        .run(raise_on_failure=True)
    )
    step: Step = result.run.steps[0]
    step.assets.clear()
    return step
