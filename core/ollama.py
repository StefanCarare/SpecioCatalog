"""Minimal Ollama client for Specio Catalog.

SpecioIdentify owns the canonical copy of this code, but this project is a
separate, read-only application and must keep working on its own — so it carries
its own small client rather than importing across project boundaries.

Only the describe-and-find box uses it, and only text generation: no images,
no streaming, no thinking channel.
"""
from __future__ import annotations

from typing import Optional

import requests

__all__ = ["OllamaError", "check_ollama", "list_models", "generate", "get_response"]

# A catalogue query is one round trip; a slow model must not look like a hang.
DEFAULT_TIMEOUT = 300


class OllamaError(Exception):
    """Ollama was unreachable or answered with an error."""


def check_ollama(ollama_url: str) -> bool:
    """True when the server answers /api/tags quickly."""
    try:
        requests.get(f"{ollama_url}/api/tags", timeout=5).raise_for_status()
        return True
    except requests.RequestException:
        return False


def list_models(ollama_url: str) -> list[str]:
    """Installed model names; empty when the server is unreachable."""
    try:
        data = requests.get(f"{ollama_url}/api/tags", timeout=5).json()
    except (requests.RequestException, ValueError):
        return []
    return [m.get("name") for m in (data.get("models") or []) if m.get("name")]


def generate(
    ollama_url: str,
    model: str,
    prompt: str,
    num_ctx: int = 8192,
    num_predict: int = 1500,
    thinking: bool = False,
    timeout: Optional[int] = DEFAULT_TIMEOUT,
) -> dict:
    """One non-streaming /api/generate call. Returns the raw API dictionary."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": thinking,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    try:
        response = requests.post(
            f"{ollama_url}/api/generate", json=payload, timeout=timeout
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = (exc.response.text or "").strip()[:500]
        raise OllamaError(
            f"Nu am putut comunica cu Ollama: {exc}" + (f"; detalii: {detail}" if detail else "")
        ) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise OllamaError("Ollama a returnat un răspuns care nu este JSON valid.") from exc
    if isinstance(data, dict) and data.get("error"):
        raise OllamaError(f"Ollama a raportat o eroare: {data['error']}")
    return data


def get_response(data: dict) -> str:
    """The generated text, whatever field the model put it in."""
    if not isinstance(data, dict):
        return ""
    text = data.get("response")
    if isinstance(text, str) and text.strip():
        return text.strip()
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""
