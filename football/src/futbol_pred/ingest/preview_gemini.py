"""Previa narrativa de partido (storytelling) con Google Gemini (gratis).

Redacta un análisis estilo prensa deportiva premium a partir de los NÚMEROS del
modelo (probabilidades, xG, estadísticas esperadas, forma, h2h). No inventa
datos ni da consejos de apuestas: interpreta lo que el modelo ya calculó.

Clave: AI_API_KEY o GEMINI_API_KEY (la misma cuenta gratis de Google AI Studio).
Si no hay clave o la API falla, devuelve None (el feed sigue sin previa).

Diagnóstico:  python -m futbol_pred.ingest.preview_gemini
"""

from __future__ import annotations

import json
import os

import requests

API_KEY = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_SYSTEM = (
    "Eres un redactor de prensa deportiva de primer nivel, en español de España. "
    "Escribes la PREVIA de un partido con criterio táctico, ameno pero riguroso. "
    "Usas SOLO los datos que te doy (probabilidades, goles esperados, estadísticas "
    "esperadas, forma reciente, cara a cara). No inventas alineaciones, lesiones ni "
    "fichajes concretos que no aparezcan. NO das consejos de apuestas ni mencionas "
    "cuotas. 130-180 palabras, 2 párrafos, tono de análisis, sin titulares."
)


def _prompt(m: dict) -> str:
    probs = m.get("probs") or []
    xg = m.get("xg") or []
    mk = m.get("markets") or {}
    st = m.get("stats") or {}
    def line(k, lab):
        v = st.get(k)
        return f"{lab}: {v['home']}-{v['away']}" if v else None
    stats_txt = " · ".join(filter(None, [
        line("shots", "remates"), line("corners", "córners"),
        line("fouls", "faltas"), line("yellows", "amarillas")]))
    partes = [
        f"Partido: {m.get('home')} (local) vs {m.get('away')} (visitante).",
        f"Competición: {m.get('league')}, jornada {m.get('matchday')}.",
        f"Probabilidad del modelo — victoria local {probs[0] if probs else '?'}%, "
        f"empate {probs[1] if len(probs)>1 else '?'}%, victoria visitante "
        f"{probs[2] if len(probs)>2 else '?'}%.",
        f"Goles esperados (xG): {xg[0] if xg else '?'} - {xg[1] if len(xg)>1 else '?'}.",
        f"Marcador más probable: {mk.get('marcador','?')}. "
        f"Prob. de más de 2.5 goles: {round((mk.get('over_2_5') or 0)*100)}%. "
        f"Ambos marcan: {round((mk.get('btts') or 0)*100)}%.",
    ]
    if stats_txt:
        partes.append(f"Estadísticas esperadas (local-visitante): {stats_txt}.")
    if m.get("form"):
        partes.append(f"Forma reciente: {m['form']}.")
    if m.get("h2h"):
        partes.append(f"Cara a cara reciente: {m['h2h']}.")
    return _SYSTEM + "\n\nDatos:\n" + "\n".join(partes) + "\n\nEscribe la previa:"


def generate_preview(m: dict, timeout: int = 30) -> str | None:
    if not API_KEY:
        return None
    body = {
        "contents": [{"parts": [{"text": _prompt(m)}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 500},
    }
    try:
        r = requests.post(
            _URL.format(model=MODEL),
            params={"key": API_KEY},
            json=body,
            timeout=timeout,
        )
        if not r.ok:
            return None
        data = r.json()
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _diagnose() -> None:
    demo = {
        "home": "Athletic Club", "away": "Sevilla FC", "league": "LaLiga", "matchday": 2,
        "probs": [53, 24, 23], "xg": [1.61, 0.96],
        "markets": {"marcador": "1-0", "over_2_5": 0.47, "btts": 0.49},
        "stats": {"shots": {"home": 13.6, "away": 8.4}, "corners": {"home": 4.1, "away": 4.3}},
    }
    print("clave:", "sí" if API_KEY else "NO (define AI_API_KEY)")
    print(generate_preview(demo) or "(sin previa)")


if __name__ == "__main__":
    _diagnose()
