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


def test_gemini_descubre_modelo_activo_en_lugar_del_retirado(monkeypatch):
    class Response:
        ok = True

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    monkeypatch.setenv("AI_API_KEY", "key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(A, "_gemini_model_cache", None)
    monkeypatch.setattr(A.requests, "get", lambda *_a, **_k: Response({
        "models": [{"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]}]
    }))
    called = []

    def post(url, **_kwargs):
        called.append(url)
        return Response({"candidates": [{"content": {"parts": [{"text": "respuesta"}]}}]})

    monkeypatch.setattr(A.requests, "post", post)
    result = A._gemini("hola", 100, 0.2, 10)
    assert result.model == "gemini-3.6-flash"
    assert "gemini-2.0-flash" not in called[0]
