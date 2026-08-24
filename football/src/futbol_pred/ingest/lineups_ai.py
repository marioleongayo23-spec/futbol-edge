"""Alineaciones probables + bajas (lesiones/sanciones) con Gemini (API normal).

Hace UNA sola llamada en bloque para TODOS los partidos de los próximos días
(consulta normal a la API de Gemini, sin grounding), así consume pocos tokens y
se queda de sobra en la capa gratuita. El cacheo temporal (12 h) lo controla
quien llama (dashboard._attach_lineups). Sin clave o ante cualquier fallo,
devuelve {} y el feed sigue igual.

Honestidad: son alineaciones PROBABLES según el conocimiento del modelo; se
marcan como tal en la app. No son datos oficiales — conviene verificarlas.

Diagnóstico:  python -m futbol_pred.ingest.lineups_ai
"""

from __future__ import annotations

import json
import os
import re
import time

import requests

API_KEY = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
# Consulta normal a la API (sin grounding): flash-lite, gratis y estable.
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_INSTR = (
    "Eres analista de fútbol experto en LaLiga y Segunda de España. Para CADA "
    "partido de la lista da el ONCE PROBABLE de cada equipo (11 jugadores, con tu "
    "mejor criterio) y las posibles BAJAS por lesión o sanción que conozcas. "
    "Devuelve EXCLUSIVAMENTE un JSON válido, sin texto alrededor, con esta forma:\n"
    '[{"partido":"<tal cual te lo doy>","local":["11 nombres"],'
    '"visitante":["11 nombres"],"bajas_local":["nombre (motivo)"],'
    '"bajas_visitante":["nombre (motivo)"]}]\n'
    "Da SIEMPRE tu mejor estimación de los onces (aunque no sea segura). Si de "
    "algún equipo no tienes ni idea, deja su lista vacía, pero incluye el partido."
)


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def fetch_lineups(matches: list[dict], timeout: int = 60, retries: int = 2) -> dict:
    """matches: [{'partido': 'Local vs Visitante'}]. Devuelve {partido: {...}}.

    Una única llamada groundada para toda la lista."""
    if not API_KEY or not matches:
        return {}
    lista = "\n".join(f"- {m['partido']}" for m in matches)
    prompt = _INSTR + "\n\nPartidos:\n" + lista + "\n\nJSON:"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000},
    }
    for attempt in range(retries):
        try:
            r = requests.post(_URL.format(model=MODEL), params={"key": API_KEY},
                              json=body, timeout=timeout)
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 503):
            time.sleep(5 * (attempt + 1))
            continue
        if not r.ok:
            return {}
        try:
            data = r.json()
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
        except (ValueError, KeyError, IndexError):
            return {}
        arr = _extract_json(text)
        if not arr:
            time.sleep(2)
            continue
        out: dict = {}
        for item in arr:
            key = str(item.get("partido", "")).strip()
            loc, vis = item.get("local") or [], item.get("visitante") or []
            if key and (loc or vis):
                out[key] = {
                    "local": [str(x) for x in loc][:11],
                    "visitante": [str(x) for x in vis][:11],
                    "bajas_local": [str(x) for x in (item.get("bajas_local") or [])][:8],
                    "bajas_visitante": [str(x) for x in (item.get("bajas_visitante") or [])][:8],
                }
        return out
    return {}


def _diagnose() -> None:
    print("clave:", "sí" if API_KEY else "NO (define AI_API_KEY/GEMINI_API_KEY)")
    demo = [{"partido": "Real Madrid vs Osasuna"}, {"partido": "Athletic Club vs Sevilla FC"}]
    res = fetch_lineups(demo)
    print(json.dumps(res, ensure_ascii=False, indent=1) if res else "(sin datos)")


if __name__ == "__main__":
    _diagnose()
