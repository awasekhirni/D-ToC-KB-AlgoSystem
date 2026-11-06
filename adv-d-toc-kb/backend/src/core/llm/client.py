"""Minimal, retry-aware OpenAI HTTP client.

Deliberately vendor-agnostic shape so a second provider (Anthropic, local
vLLM) can implement the same two methods (``embed``, ``chat_json``) without
changing call sites.

Retry policy: exponential backoff on 429/5xx, up to ``max_retries``.
JSON-mode chat is enforced (``response_format={"type": "json_object"}``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from src.config.settings import Settings
from src.observability.logging import get_logger
from src.observability.metrics import LLM_CALLS, LLM_ERRORS

logger = get_logger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)


class OpenAIClient:
    """Async OpenAI HTTP client with retry and JSON-mode chat."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        max_retries: int = 3,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._max_retries = max_retries

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        await self._client.aclose()

    # -- public ---------------------------------------------------------

    async def embed(
        self, texts: list[str], *, model: str, dimensions: int
    ) -> list[list[float]]:
        """Generate embeddings for ``texts``.

        Args:
            texts: Input strings (must be non-empty list).
            model: OpenAI embedding model name.
            dimensions: Output dimension (1536 or 3072 for text-embedding-3).

        Returns:
            List of embeddings in the same order as ``texts``.

        Raises:
            ValueError: If ``texts`` is empty.
            RuntimeError: If the API returns a mismatched count.
        """
        if not texts:
            return []
        LLM_CALLS.inc(labels={"endpoint": "embeddings"})
        payload: dict[str, Any] = {
            "model": model,
            "input": texts,
            "dimensions": dimensions,
            "encoding_format": "float",
        }
        data = await self._post_with_retry("/embeddings", payload)
        # API may return items out of order; sort defensively.
        items = sorted(data["data"], key=lambda d: d["index"])
        if len(items) != len(texts):
            LLM_ERRORS.inc(labels={"endpoint": "embeddings"})
            raise RuntimeError(
                f"Embedding count mismatch: sent {len(texts)}, got {len(items)}"
            )
        return [item["embedding"] for item in items]

    async def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> dict[str, Any]:
        """Run a chat completion in JSON mode and parse the response.

        Args:
            model: OpenAI chat model name.
            system: System prompt.
            user: User prompt.
            temperature: Sampling temperature (0.0 for determinism).
            max_tokens: Max response tokens.

        Returns:
            Parsed JSON dict.

        Raises:
            ValueError: If the response is not valid JSON.
        """
        LLM_CALLS.inc(labels={"endpoint": "chat"})
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        data = await self._post_with_retry("/chat/completions", payload)
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            LLM_ERRORS.inc(labels={"endpoint": "chat"})
            logger.error("LLM returned non-JSON: %s", content[:500])
            raise ValueError("LLM returned non-JSON payload") from exc

    # -- internals ------------------------------------------------------

    async def _post_with_retry(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """POST with exponential backoff on retryable status codes."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(path, json=payload)
                if resp.status_code in _RETRYABLE_STATUS:
                    if attempt < self._max_retries - 1:
                        delay = 2 ** attempt
                        logger.warning(
                            "OpenAI %s -> %d, retrying in %ds",
                            path, resp.status_code, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                LLM_ERRORS.inc(labels={"endpoint": path})
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError(
            f"Exhausted retries on {path}: {last_exc}"
        ) from last_exc


def build_client(settings: Settings) -> OpenAIClient:
    """Construct an ``OpenAIClient`` from settings.

    Raises:
        RuntimeError: If ``openai_api_key`` is not set.
    """
    if settings.openai_api_key is None:
        raise RuntimeError(
            "TOCKB_OPENAI_API_KEY is required when embedding_provider=openai"
        )
    logger.info("Building OpenAI client model=%s", settings.llm_model)
    return OpenAIClient(settings.openai_api_key.get_secret_value())
