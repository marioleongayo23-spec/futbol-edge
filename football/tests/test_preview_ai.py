"""Calidad mínima y atribución de previas narrativas."""

from futbol_pred.ingest.ai_client import AIResponse
import futbol_pred.ingest.preview_gemini as P


def _valid_text():
    sentences = [
        "Real Madrid llega con una ligera ventaja del modelo ante Osasuna, aunque el reparto obliga a mantener prudencia en la lectura del encuentro.",
        "El volumen previsto de remates y la producción esperada sugieren que el conjunto local tratará de instalarse pronto en campo contrario.",
        "Osasuna puede equilibrar el partido si protege bien el área y encuentra continuidad para atacar los espacios que aparezcan tras pérdida.",
        "El escenario central apunta a un ritmo competitivo, con fases de control local y otras en las que el visitante pueda discutir la iniciativa.",
        "La diferencia de goles esperados favorece al Real Madrid, pero no elimina un tramo final abierto si el marcador continúa ajustado.",
        "En conjunto, los números dibujan un partido de dominio local moderado y resistencia visitante, con detalles en ambas áreas como factor decisivo.",
    ]
    return " ".join(sentences[:3]) + "\n\n" + " ".join(sentences[3:])


def test_preview_valida_y_conserva_provider(monkeypatch):
    monkeypatch.setattr(P, "chat", lambda *_args, **_kwargs: AIResponse(_valid_text(), "Groq", "llama-test"))
    result = P.generate_preview({"home": "Real Madrid", "away": "Osasuna", "probs": [55, 25, 20],
                                 "xg": [1.8, 0.9], "markets": {"marcador": "2-1"}})
    assert result.provider == "Groq"
    assert result.quality >= 0.7
    assert "Real Madrid" in result.text and "Osasuna" in result.text


def test_preview_rechaza_blank_o_respuesta_corta(monkeypatch):
    monkeypatch.setattr(P, "chat", lambda *_args, **_kwargs: AIResponse("Real Madrid vs Osasuna.", "Gemini", "x"))
    assert P.generate_preview({"home": "Real Madrid", "away": "Osasuna"}) is None
