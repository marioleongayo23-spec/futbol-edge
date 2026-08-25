"""Cliente de IA con FALLBACK entre proveedores.

Intenta Gemini primero y, si falla o se agota la cuota (429), tira del siguiente
proveedor compatible con la API de OpenAI (ChatGPT, y también gratis como Groq u
OpenRouter — solo cambia base_url y modelo). Así, si un proveedor se queda sin
cuota, otro cubre.

Claves por variables de entorno (define las que tengas):
  - Gemini:   AI_API_KEY o GEMINI_API_KEY   (modelo: GEMINI_MODEL)
  - OpenAI/compatible: OPENAI_API_KEY        (base: OPENAI_BASE_URL, modelo: OPENAI_MODEL)
      · ChatGPT:    OPENAI_BASE_URL=https://api.openai.com/v1        OPENAI_MODEL=gpt-4o-mini
      · Groq(free): OPENAI_BASE_URL=https://api.groq.com/openai/v1   OPENAI_MODEL=llama-3.3-70b-versatile
      · OpenRouter: OPENAI_BASE_URL=https://openrouter.ai/api/v1     OPENAI_MODEL=...

chat() devuelve el texto de la primera IA que responda, o None si ninguna puede.
"""

from __future__ import annotations

import os

import requests

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _gemini(prompt: str, max_tokens: int, temperature: float, timeout: int):
    key = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    r = requests.post(
        _GEMINI_URL.format(model=model), params={"key": key},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}},
        timeout=timeout,
    )
    if r.status_code == 429 or not r.ok:
        return None
    try:
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip() or None
    except (ValueError, KeyError, IndexError):
        return None


def _openai(prompt: str, max_tokens: int, temperature: float, timeout: int):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    headers = {"Authorization": f"Bearer {key}"}
    ref = os.getenv("OPENAI_HTTP_REFERER")  # OpenRouter recomienda estas cabeceras
    if ref:
        headers["HTTP-Referer"] = ref
        headers["X-Title"] = "Futbol Edge"
    r = requests.post(
        f"{base}/chat/completions", headers=headers,
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=timeout,
    )
    if not r.ok:
        return None
    try:
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or None
    except (ValueError, KeyError, IndexError):
        return None


# Orden de preferencia: Gemini primero, OpenAI/compatible de reserva.
_PROVIDERS = (_gemini, _openai)


def available() -> bool:
    """True si hay al menos un proveedor con clave configurada."""
    return bool(os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
                or os.getenv("OPENAI_API_KEY"))


def chat(prompt: str, max_tokens: int = 1200, temperature: float = 0.5,
         timeout: int = 40) -> str | None:
    """Texto de la primera IA que responda (Gemini → OpenAI/compatible)."""
    for provider in _PROVIDERS:
        try:
            text = provider(prompt, max_tokens, temperature, timeout)
        except requests.RequestException:
            text = None
        if text:
            return text
    return None
