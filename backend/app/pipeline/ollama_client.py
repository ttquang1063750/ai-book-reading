"""Thin async client for the local Ollama server, with retry."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 300.0  # seconds; 14B inference on M1 can be slow for long chunks
RETRY_DELAYS = [1.0, 3.0, 9.0]


class OllamaError(Exception):
    pass


async def chat(
    model: str,
    messages: list[dict],
    *,
    json_format: bool = False,
    temperature: float | None = None,
    num_ctx: int | None = None,
) -> str:
    """Send a chat request to Ollama and return the assistant message content."""
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if json_format:
        payload["format"] = "json"
    options: dict = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if options:
        payload["options"] = options

    last_error: Exception | None = None
    for attempt, delay in enumerate([0.0, *RETRY_DELAYS]):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            if response.status_code >= 500:
                raise OllamaError(f"Ollama 5xx: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.TransportError, OllamaError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("Ollama call failed (attempt %d): %s", attempt + 1, exc)
    raise OllamaError(f"Ollama call failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}")


async def chat_stream(
    model: str,
    messages: list[dict],
    *,
    temperature: float | None = None,
    num_ctx: int | None = None,
) -> AsyncIterator[str]:
    """Stream a chat response token-by-token. No retry — a chat reply is a
    live conversation, not a resumable batch job like translate/summarize;
    if the stream drops mid-way the caller surfaces the error to the user."""
    payload: dict = {"model": model, "messages": messages, "stream": True}
    options: dict = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise OllamaError(f"Ollama chat_stream error: {response.status_code} {body[:200]}")
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("message", {}).get("content")
                if content:
                    yield content
                if data.get("done"):
                    break


async def embed(model: str, texts: list[str]) -> list[list[float]]:
    """Batch-embed texts via Ollama's /api/embed (plural, batched — not the
    older singular /api/embeddings). Returns one vector per input text, same
    order."""
    payload = {"model": model, "input": texts}

    last_error: Exception | None = None
    for attempt, delay in enumerate([0.0, *RETRY_DELAYS]):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(f"{OLLAMA_BASE_URL}/api/embed", json=payload)
            if response.status_code >= 500:
                raise OllamaError(f"Ollama 5xx: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
            return response.json()["embeddings"]
        except (httpx.TransportError, OllamaError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("Ollama embed call failed (attempt %d): %s", attempt + 1, exc)
    raise OllamaError(f"Ollama embed call failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}")


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]
