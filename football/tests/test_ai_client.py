"""Orden de proveedores y atribución real de la capa IA."""

import futbol_pred.ingest.ai_client as A


def test_fallback_gemini_a_groq(monkeypatch):
    calls = []

    def gemini(*_args):
        calls.append("Gemini")
        return None

    def groq(*_args):
        calls.append("Groq")
        return A.AIResponse("respuesta útil", "Groq", "llama-test")

    monkeypatch.setattr(A, "_PROVIDERS", (gemini, groq))
    result = A.chat("hola")
    assert calls == ["Gemini", "Groq"]
    assert result.provider == "Groq" and result.model == "llama-test"


def test_no_llama_fallback_si_gemini_responde(monkeypatch):
    calls = []

    def gemini(*_args):
        calls.append("Gemini")
        return A.AIResponse("respuesta", "Gemini", "gemini-test")

    def groq(*_args):
        calls.append("Groq")
        raise AssertionError("Groq no debe llamarse")

    monkeypatch.setattr(A, "_PROVIDERS", (gemini, groq))
    assert A.chat("hola").provider == "Gemini"
    assert calls == ["Gemini"]


def test_compatibilidad_openai_solo_si_es_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "legacy")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert A._groq_key() is None
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    assert A._groq_key() == "legacy"
