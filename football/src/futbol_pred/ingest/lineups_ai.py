"""Onces, bajas y props de jugador con Gemini → Groq y validación estricta."""

from __future__ import annotations

import json
import re

from .ai_client import chat

_INSTR = (
    "Eres analista de fútbol experto en LaLiga y Segunda de España. Para CADA "
    "partido de la lista da: (1) el ONCE PROBABLE completo de cada equipo, "
    "exactamente 11 nombres únicos por lado; (2) bajas por lesión o sanción; "
    "y (3) de 3 a 5 jugadores clave de cada equipo con su estimación para ESE "
    "partido de goles (g), asistencias (a), remates (r), remates a puerta (rp), "
    "faltas cometidas (fc), faltas recibidas (fr) y tarjetas (t). Todas las props "
    "son números esperados, no porcentajes. Devuelve EXCLUSIVAMENTE JSON válido:\n"
    '[{"partido":"<tal cual te lo doy>","local":["11 nombres"],'
    '"visitante":["11 nombres"],"bajas_local":["nombre (motivo)"],'
    '"bajas_visitante":["nombre (motivo)"],'
    '"clave_local":[{"j":"nombre","g":0.4,"a":0.2,"r":2.5,"rp":1.1,'
    '"fc":1.2,"fr":1.5,"t":0.3}],'
    '"clave_visitante":[{"j":"nombre","g":0.3,"a":0.2,"r":2.0,"rp":0.8,'
    '"fc":1.5,"fr":1.0,"t":0.4}]}]\n'
    "Incluye TODOS los partidos. No uses null, guiones, 'por confirmar' ni listas "
    "vacías. Si no puedes completar con suficiente calidad un partido, omítelo: "
    "el sistema conservará automáticamente su último resultado bueno."
)

_PROP_LIMITS = {
    "g": (0.0, 3.0),
    "a": (0.0, 3.0),
    "r": (0.0, 12.0),
    "rp": (0.0, 8.0),
    "fc": (0.0, 8.0),
    "fr": (0.0, 8.0),
    "t": (0.0, 1.5),
}


def _name(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip(" ,;-")
    if len(value) < 2 or value.lower() in {"n/a", "null", "por confirmar", "desconocido"}:
        return None
    return value


def _unique_names(items, required: int | None = None, limit: int = 11) -> list[str] | None:
    out = []
    seen = set()
    for raw in items or []:
        value = _name(raw)
        key = value.casefold() if value else ""
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    out = out[:limit]
    if required is not None and len(out) != required:
        return None
    return out


def _number(value, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not low <= number <= high:
        return None
    return round(number, 1)


def _clave(items) -> list[dict] | None:
    out = []
    seen = set()
    for item in (items or [])[:5]:
        if not isinstance(item, dict):
            continue
        player = _name(item.get("j"))
        if not player or player.casefold() in seen:
            continue
        row = {"jugador": player}
        complete = True
        for key, (low, high) in _PROP_LIMITS.items():
            legacy_value = item.get("f") if key == "fc" and "fc" not in item else item.get(key)
            value = _number(legacy_value, low, high)
            if value is None:
                complete = False
                break
            row[key] = value
        if complete:
            seen.add(player.casefold())
            out.append(row)
    return out if len(out) >= 3 else None


def _extract_json(text: str):
    if not isinstance(text, str):
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def _match_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _validate_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    local = _unique_names(item.get("local"), required=11)
    visitor = _unique_names(item.get("visitante"), required=11)
    key_local = _clave(item.get("clave_local"))
    key_visitor = _clave(item.get("clave_visitante"))
    if not local or not visitor or not key_local or not key_visitor:
        return None
    abs_local = _unique_names(item.get("bajas_local"), limit=8) or []
    abs_visitor = _unique_names(item.get("bajas_visitante"), limit=8) or []
    return {
        "local": local,
        "visitante": visitor,
        "bajas_local": abs_local,
        "bajas_visitante": abs_visitor,
        "clave_local": key_local,
        "clave_visitante": key_visitor,
        "quality": {
            "complete": True,
            "lineup_players": len(local) + len(visitor),
            "props_players": len(key_local) + len(key_visitor),
            "score": 1.0,
        },
    }


def fetch_lineups(matches: list[dict], timeout: int = 60, retries: int = 1) -> dict:
    """Devuelve solo partidos completos; nunca publica onces o props parciales."""

    del retries
    requested = [str(match.get("partido", "")).strip() for match in matches]
    requested = [match for match in requested if match]
    if not requested:
        return {}
    prompt = _INSTR + "\n\nPartidos:\n" + "\n".join(f"- {match}" for match in requested) + "\n\nJSON:"
    response = chat(prompt, max_tokens=10000, temperature=0.2, timeout=timeout)
    if not response:
        return {}
    parsed = _extract_json(response.text)
    if not parsed:
        return {}

    requested_by_key = {_match_key(match): match for match in requested}
    out = {}
    for item in parsed:
        raw_key = _name(item.get("partido")) if isinstance(item, dict) else None
        canonical = requested_by_key.get(_match_key(raw_key or ""))
        if not canonical:
            continue
        valid = _validate_item(item)
        if not valid:
            continue
        out[canonical] = {
            **valid,
            "provider": response.provider,
            "model": response.model,
        }
    return out
