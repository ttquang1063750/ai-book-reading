"""Thin async client for the local Ollama server, with retry."""

import asyncio
import json
import logging

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
) -> str:
    """Send a chat request to Ollama and return the assistant message content."""
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if json_format:
        payload["format"] = "json"
    if temperature is not None:
        payload["options"] = {"temperature": temperature}

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


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]
