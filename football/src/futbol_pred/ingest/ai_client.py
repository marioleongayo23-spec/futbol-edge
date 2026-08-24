"""Cliente de IA resiliente: Gemini primero y Groq como fallback.

El módulo no conoce el feed ni escribe cachés. Su única responsabilidad es
devolver texto junto con el proveedor/modelo reales que lo generaron. La capa
de dashboard valida la calidad y conserva el último resultado bueno.

Variables de entorno:
  - Gemini: ``AI_API_KEY`` o ``GEMINI_API_KEY``; ``GEMINI_MODEL`` opcional.
  - Groq: ``GROQ_API_KEY``; ``GROQ_MODEL`` opcional.

Compatibilidad: si ya se configuró Groq mediante las variables genéricas
``OPENAI_API_KEY`` + ``OPENAI_BASE_URL=https://api.groq.com/openai/v1``, también
se reconoce. No se usa ese par para ningún host que no sea Groq: el fallback
de producción es explícito y el proveedor mostrado en la UI siempre es real.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

import requests

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class AIResponse:
    """Respuesta aceptada de un proveedor concreto."""

    text: str
    provider: str
    model: str


def _gemini_key() -> str | None:
    return os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")


def _groq_key() -> str | None:
    direct = os.getenv("GROQ_API_KEY")
    if direct:
        return direct
    base = os.getenv("OPENAI_BASE_URL", "").lower()
    if "api.groq.com" in base:
        return os.getenv("OPENAI_API_KEY")
    return None


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _gemini(prompt: str, max_tokens: int, temperature: float, timeout: int) -> AIResponse | None:
    key = _gemini_key()
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    response = requests.post(
        _GEMINI_URL.format(model=model),
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        },
        timeout=timeout,
    )
    if not response.ok:
        return None
    try:
        parts = (response.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = _clean_text("".join(part.get("text", "") for part in parts))
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None
    return AIResponse(text=text, provider="Gemini", model=model) if text else None


def _groq(prompt: str, max_tokens: int, temperature: float, timeout: int) -> AIResponse | None:
    key = _groq_key()
    if not key:
        return None
    base = os.getenv("GROQ_BASE_URL", _GROQ_BASE_URL).rstrip("/")
    model = os.getenv("GROQ_MODEL") or os.getenv("OPENAI_MODEL") or "llama-3.3-70b-versatile"
    response = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    if not response.ok:
        return None
    try:
        text = _clean_text(response.json()["choices"][0]["message"]["content"])
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None
    return AIResponse(text=text, provider="Groq", model=model) if text else None


Provider = Callable[[str, int, float, int], AIResponse | None]
_PROVIDERS: tuple[Provider, ...] = (_gemini, _groq)


def available() -> bool:
    """Indica si hay al menos uno de los dos proveedores configurado."""

    return bool(_gemini_key() or _groq_key())


def configured_providers() -> list[str]:
    """Nombres públicos de los proveedores configurados, en orden de uso."""

    providers = []
    if _gemini_key():
        providers.append("Gemini")
    if _groq_key():
        providers.append("Groq")
    return providers


def chat(
    prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.5,
    timeout: int = 40,
) -> AIResponse | None:
    """Devuelve la primera respuesta válida siguiendo Gemini → Groq."""

    for provider in _PROVIDERS:
        try:
            result = provider(prompt, max_tokens, temperature, timeout)
        except (requests.RequestException, TypeError, ValueError):
            result = None
        if result and _clean_text(result.text):
            return result
    return None
