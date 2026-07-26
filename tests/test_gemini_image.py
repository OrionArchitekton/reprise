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


def test_a_retired_primary_model_falls_back_and_the_manifest_records_which_ran(
    tmp_path: Any,
) -> None:
    """A model id in the catalog is not a model you are allowed to call.

    Google retired every Imagen tier for new API keys while still listing them
    (genblaze#206), and it can do the same to a Gemini image tier. A pipeline
    pinned to one slug dies when that happens, so the provider walks its
    fallback chain, and the manifest must name the model that ACTUALLY produced
    the bytes: a manifest claiming the retired model would be provenance that
    describes a call which never happened.
    """
    tried: list[str] = []

    def retire_the_primary(
        url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        model = url.rsplit("/", 1)[-1].split(":")[0]
        tried.append(model)
        if model == "gemini-2.5-flash-image":
            raise urllib.error.HTTPError(
                url, 404, "Not Found", None,  # type: ignore[arg-type]
                __import__("io").BytesIO(
                    b'{"error":{"message":"no longer available to new users"}}'
                ),
            )
        return ok_transport(
            url.replace(model, "gemini-2.5-flash-image"), body, headers, timeout
        )

    p = GeminiImageProvider(
        api_key="k",
        output_dir=tmp_path,
        transport=retire_the_primary,
        fallback_models=("gemini-3.1-flash-image",),
    )

    step = run_step(p)

    assert tried == ["gemini-2.5-flash-image", "gemini-3.1-flash-image"]
    assert step.model == "gemini-3.1-flash-image"
    assert step.assets and step.assets[0].sha256 == hashlib.sha256(PNG).hexdigest()


def test_every_model_failing_surfaces_the_last_upstream_message(tmp_path: Any) -> None:
    """A chain that runs out must not swallow why. Silence here would look
    exactly like a network blip and hide an entitlement change."""

    def always_404(
        url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        raise urllib.error.HTTPError(
            url, 404, "Not Found", None,  # type: ignore[arg-type]
            __import__("io").BytesIO(b'{"error":{"message":"no longer available"}}'),
        )

    p = GeminiImageProvider(
        api_key="k", output_dir=tmp_path, transport=always_404,
        fallback_models=("gemini-3.1-flash-image",),
    )

    with pytest.raises(ProviderError, match="no longer available"):
        p.generate(_bare_step())
