"""Prompt embeddings for near-match scoring.

Embeddings are computed over the NORMALIZED prompt (`normalize_prompt`), so the
same text that exact-matching compares is the text near-matching embeds -- the
two stages can never disagree about what a prompt "is". Vectors are cached in
B2 as sidecars keyed by the sha256 of that normalized text (see `library.py`),
which makes embedding idempotent across ingest runs and free for repeats.

Three implementations:

* `GeminiEmbedder` -- the DEFAULT live path (gemini-embedding-001, 3072 dims),
  plain stdlib HTTP so the app adds no SDK dependency for one endpoint.
  Live-calibrated 2026-07-26: red-vs-blue same-scene scores 0.9182 (lands in
  the REVIEW band, not auto-reuse), unrelated text 0.4763 (GENERATE).
* `OpenAIEmbedder` -- same contract for deployments holding a real OpenAI key
  (the estate's MANIFEST_OPENAI_API_KEY is a Manifest-gateway key, NOT valid
  on api.openai.com -- its 401 is what this class's verbatim-error rule caught).
* `HashEmbedder` -- deterministic, offline, for tests and demo-static mode.
  Similarity numbers it produces are structural, not semantic; nothing outside
  tests may present them as meaning anything.

Errors carry the provider's own message verbatim; a dead model id or bad key
must never degrade into a silent zero-vector (that would score 0.0 against
everything and quietly turn every request into GENERATE -- an invisible outage).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Protocol

from reprise.decide import normalize_prompt


class EmbedError(RuntimeError):
    """Embedding failed; the message carries the provider's verbatim error."""


class Embedder(Protocol):
    """Turns a prompt into a unit-ish dense vector."""

    def embed(self, prompt: str) -> tuple[float, ...]: ...


def prompt_fingerprint(prompt: str) -> str:
    """Stable id of a prompt's normalized text; the sidecar cache key."""
    return hashlib.sha256(normalize_prompt(prompt).encode()).hexdigest()


class OpenAIEmbedder:
    """text-embedding-3-small via the REST endpoint, stdlib only."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "text-embedding-3-small",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise EmbedError("OPENAI_API_KEY is not set")
        self._model = model
        self._timeout = timeout

    def embed(self, prompt: str) -> tuple[float, ...]:
        body = json.dumps(
            {"model": self._model, "input": normalize_prompt(prompt)}
        ).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as e:
            # Surface the provider's own words: a generic label here once hid a
            # dead model id for hours in a prior build. Never swallow this.
            detail = e.read().decode(errors="replace")[:500]
            raise EmbedError(f"OpenAI embeddings HTTP {e.code}: {detail}") from e
        except OSError as e:
            raise EmbedError(f"OpenAI embeddings unreachable: {e}") from e
        try:
            vec = payload["data"][0]["embedding"]
        except (KeyError, IndexError) as e:
            raise EmbedError(
                f"OpenAI embeddings response missing data: {json.dumps(payload)[:300]}"
            ) from e
        return tuple(float(x) for x in vec)


class GeminiEmbedder:
    """gemini-embedding-001 via the REST endpoint, stdlib only."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "gemini-embedding-001",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise EmbedError("GEMINI_API_KEY is not set")
        self._model = model
        self._timeout = timeout

    def embed(self, prompt: str) -> tuple[float, ...]:
        body = json.dumps(
            {
                "model": f"models/{self._model}",
                "content": {"parts": [{"text": normalize_prompt(prompt)}]},
            }
        ).encode()
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:embedContent",
            data=body,
            headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise EmbedError(f"Gemini embeddings HTTP {e.code}: {detail}") from e
        except OSError as e:
            raise EmbedError(f"Gemini embeddings unreachable: {e}") from e
        try:
            vec = payload["embedding"]["values"]
        except KeyError as e:
            raise EmbedError(
                f"Gemini embeddings response missing values: {json.dumps(payload)[:300]}"
            ) from e
        return tuple(float(x) for x in vec)


def default_embedder() -> Embedder:
    """The embedder the app uses when nothing overrides it: Gemini."""
    return GeminiEmbedder()


class HashEmbedder:
    """Deterministic offline embedder for tests and static demo mode.

    Buckets character trigrams of the normalized prompt into a fixed number of
    dimensions and L2-normalizes. Similar strings overlap in trigrams, so small
    edits yield high-but-not-1.0 cosine -- structurally useful for exercising
    thresholds, semantically meaningless. Never present its scores as semantic.
    """

    def __init__(self, dims: int = 256) -> None:
        self._dims = dims

    def embed(self, prompt: str) -> tuple[float, ...]:
        text = normalize_prompt(prompt)
        vec = [0.0] * self._dims
        padded = f"  {text}  "
        for i in range(len(padded) - 2):
            tri = padded[i : i + 3]
            h = int.from_bytes(hashlib.blake2s(tri.encode(), digest_size=4).digest(), "big")
            vec[h % self._dims] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return tuple(vec)
        return tuple(x / norm for x in vec)
