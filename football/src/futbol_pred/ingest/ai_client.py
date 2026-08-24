"""Cliente de IA resiliente: Gemini → Groq → endpoint local compatible.

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
from datetime import datetime, timezone
import os
from typing import Callable

import requests

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_gemini_model_cache: list[str] | None = None
_events: list[dict] = []
_usage: dict | None = None


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


def _local_base() -> str | None:
    return _clean_text(os.getenv("LOCAL_AI_BASE_URL") or os.getenv("OLLAMA_OPENAI_BASE_URL"))


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _gemini_models(key: str, timeout: int) -> list[str]:
    """Descubre modelos activos y evita quedar atado a un modelo retirado."""

    global _gemini_model_cache
    configured = _clean_text(os.getenv("GEMINI_MODEL"))
    if configured:
        configured = configured.removeprefix("models/")
    if _gemini_model_cache is None:
        discovered: list[str] = []
        try:
            response = requests.get(_GEMINI_MODELS_URL, params={"key": key}, timeout=timeout)
            if response.ok:
                for item in response.json().get("models", []):
                    methods = item.get("supportedGenerationMethods") or []
                    name = str(item.get("name") or "").removeprefix("models/")
                    if name and "generateContent" in methods:
                        discovered.append(name)
        except (requests.RequestException, AttributeError, TypeError, ValueError):
            discovered = []
        preferred = [
            "gemini-3.6-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
        ordered = [name for name in preferred if name in discovered]
        ordered.extend(name for name in discovered if "flash" in name and name not in ordered)
        ordered.extend(name for name in discovered if name not in ordered)
        _gemini_model_cache = ordered or preferred
    return ([configured] if configured else []) + [
        name for name in _gemini_model_cache if name != configured
    ]


def _gemini(prompt: str, max_tokens: int, temperature: float, timeout: int) -> AIResponse | None:
    key = _gemini_key()
    if not key:
        return None
    for model in _gemini_models(key, min(timeout, 20)):
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
            continue
        try:
            parts = (response.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            text = _clean_text("".join(part.get("text", "") for part in parts))
        except (AttributeError, TypeError, ValueError, KeyError, IndexError):
            text = None
        if text:
            return AIResponse(text=text, provider="Gemini", model=model)
    return None


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


def _local(prompt: str, max_tokens: int, temperature: float, timeout: int) -> AIResponse | None:
    """Tercer nivel opcional: Ollama/vLLM/LM Studio con API OpenAI compatible."""

    base = _local_base()
    if not base:
        return None
    model = os.getenv("LOCAL_AI_MODEL") or "llama3.1:8b"
    key = os.getenv("LOCAL_AI_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers=headers,
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
    return AIResponse(text=text, provider="Modelo local", model=model) if text else None


Provider = Callable[[str, int, float, int], AIResponse | None]
_PROVIDERS: tuple[Provider, ...] = (_gemini, _groq, _local)


def available() -> bool:
    """Indica si hay al menos uno de los dos proveedores configurado."""

    return bool(_gemini_key() or _groq_key() or _local_base())


def configured_providers() -> list[str]:
    """Nombres públicos de los proveedores configurados, en orden de uso."""

    providers = []
    if _gemini_key():
        providers.append("Gemini")
    if _groq_key():
        providers.append("Groq")
    if _local_base():
        providers.append("Modelo local")
    return providers


def configure_daily_budget(previous: dict | None, now: datetime, limit: int | None = None) -> None:
    """Restaura el contador persistido del feed y limita generaciones diarias.

    El límite cuenta solicitudes lógicas (una solicitud puede probar Gemini y
    después Groq). No se guardan prompts ni respuestas en la telemetría.
    """

    global _usage, _events
    day = now.date().isoformat()
    configured = limit if limit is not None else int(os.getenv("AI_DAILY_CALL_BUDGET", "16"))
    old = previous or {}
    used = int(old.get("requests", 0)) if old.get("date") == day else 0
    _usage = {
        "date": day,
        "requests": max(0, used),
        "budget": max(0, configured),
        "remaining": max(0, configured - used),
    }
    _events = []


def usage_snapshot() -> dict | None:
    if _usage is None:
        return None
    snapshot = dict(_usage)
    snapshot["remaining"] = max(0, snapshot["budget"] - snapshot["requests"])
    return snapshot


def diagnostics() -> list[dict]:
    """Eventos sanitizados de la ejecución actual para alertas y UI."""

    return [dict(event) for event in _events]


def _event(provider: str, status: str, model: str | None = None) -> None:
    _events.append({
        "provider": provider,
        "model": model,
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
    })


def chat(
    prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.5,
    timeout: int = 40,
) -> AIResponse | None:
    """Devuelve la primera respuesta válida siguiendo Gemini → Groq."""

    if _usage is not None:
        if _usage["requests"] >= _usage["budget"]:
            _event("Sistema", "budget_exhausted")
            return None
        _usage["requests"] += 1
        _usage["remaining"] = max(0, _usage["budget"] - _usage["requests"])

    for provider in _PROVIDERS:
        name = "Gemini" if provider is _gemini else "Groq" if provider is _groq else "Modelo local"
        try:
            result = provider(prompt, max_tokens, temperature, timeout)
        except (requests.RequestException, TypeError, ValueError):
            result = None
        if result and _clean_text(result.text):
            _event(result.provider, "success", result.model)
            return result
        if name in configured_providers():
            _event(name, "failed")
    return None
