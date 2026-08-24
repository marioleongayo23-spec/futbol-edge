"""Onces, bajas y props de jugador con Gemini → Groq y validación estricta."""

from __future__ import annotations

import json
import re
import unicodedata

from .ai_client import chat

_INSTR = (
    "Eres analista de fútbol experto en LaLiga y Segunda de España. Para CADA "
    "partido de la lista da: (1) el ONCE PROBABLE completo de cada equipo, "
    "exactamente 11 nombres únicos por lado; (2) bajas por lesión o sanción; "
    "y (3) de 3 a 5 jugadores clave de cada equipo con su estimación para ESE "
    "partido de goles (g), asistencias (a), remates (r), remates a puerta (rp), "
    "faltas cometidas (fc), faltas recibidas (fr) y tarjetas (t). Todas las props "
    "son números esperados, no porcentajes. Devuelve EXCLUSIVAMENTE JSON válido:\n"
    '[{"partido":"<tal cual te lo doy>",'
    '"local":[{"j":"nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
    '"visitante":[{"j":"nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
    '"bajas_local":["nombre (motivo)"],'
    '"bajas_visitante":["nombre (motivo)"],'
    '"clave_local":[{"j":"nombre","g":0.4,"a":0.2,"r":2.5,"rp":1.1,'
    '"fc":1.2,"fr":1.5,"t":0.3}],'
    '"clave_visitante":[{"j":"nombre","g":0.3,"a":0.2,"r":2.0,"rp":0.8,'
    '"fc":1.5,"fr":1.0,"t":0.4}]}]\n'
    "Los 11 jugadores deben ir en su demarcación habitual REAL y pos debe ser la "
    "posición táctica concreta, no solo defensa/medio/delantero. Ordénalos desde "
    "el portero hasta el delantero, y de izquierda a derecha dentro de cada línea. "
    "Incluye TODOS los partidos. No uses null, guiones, 'por confirmar' ni listas "
    "vacías. Si no puedes completar con suficiente calidad un partido, omítelo: "
    "el sistema conservará automáticamente su último resultado bueno."
)

_DEFAULT_FORMATION = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
_VALID_POSITIONS = {"POR", "LI", "DFC", "LD", "CAI", "CAD", "MCD", "MC", "MI", "MD", "MP", "EI", "ED", "DC"}


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).strip().upper()


def _position(value: object) -> str | None:
    """Normaliza posiciones españolas/inglesas al vocabulario táctico del feed."""

    raw = _plain(value).replace("_", " ").replace("-", " ")
    compact = re.sub(r"[^A-Z]", "", raw)
    aliases = {
        "GK": "POR", "POR": "POR", "PORTERO": "POR", "GOALKEEPER": "POR",
        "LB": "LI", "LI": "LI", "LEFTBACK": "LI", "LATERALIZQUIERDO": "LI",
        "RB": "LD", "LD": "LD", "RIGHTBACK": "LD", "LATERALDERECHO": "LD",
        "CB": "DFC", "DFC": "DFC", "CENTREBACK": "DFC", "CENTERBACK": "DFC",
        "DEFENSACENTRAL": "DFC",
        "LWB": "CAI", "CAI": "CAI", "CARRILEROIZQUIERDO": "CAI",
        "RWB": "CAD", "CAD": "CAD", "CARRILERODERECHO": "CAD",
        "DM": "MCD", "CDM": "MCD", "MCD": "MCD", "PIVOTE": "MCD",
        "CM": "MC", "MC": "MC", "CENTREMIDFIELD": "MC", "CENTERMIDFIELD": "MC",
        "LM": "MI", "MI": "MI", "LEFTMIDFIELD": "MI",
        "RM": "MD", "MD": "MD", "RIGHTMIDFIELD": "MD",
        "AM": "MP", "CAM": "MP", "MP": "MP", "MCO": "MP", "MEDIAPUNTA": "MP",
        "LW": "EI", "EI": "EI", "LEFTWINGER": "EI", "EXTREMOIZQUIERDO": "EI",
        "RW": "ED", "ED": "ED", "RIGHTWINGER": "ED", "EXTREMODERECHO": "ED",
        "ST": "DC", "CF": "DC", "FW": "DC", "DC": "DC", "STRIKER": "DC",
        "CENTREFORWARD": "DC", "CENTERFORWARD": "DC", "DELANTEROCENTRO": "DC",
    }
    result = aliases.get(compact)
    return result if result in _VALID_POSITIONS else None


def _lineup(items, positions=None) -> tuple[list[str] | None, list[str] | None]:
    """Devuelve nombres y posiciones alineados; admite el formato antiguo."""

    names, supplied_positions, seen = [], [], set()
    for index, raw in enumerate(items or []):
        if isinstance(raw, dict):
            name = _name(raw.get("j") or raw.get("jugador") or raw.get("name"))
            pos = _position(raw.get("pos") or raw.get("posicion") or raw.get("position"))
        else:
            name = _name(raw)
            pos = _position((positions or [])[index] if index < len(positions or []) else None)
        key = name.casefold() if name else ""
        if name and key not in seen:
            seen.add(key)
            names.append(name)
            supplied_positions.append(pos)
    if len(names) != 11:
        return None, None
    normalized = [pos or _DEFAULT_FORMATION[index] for index, pos in enumerate(supplied_positions)]
    if "POR" not in normalized:
        normalized[0] = "POR"
    return names, normalized


def _formation(positions: list[str]) -> str:
    defenders = sum(pos in {"LI", "DFC", "LD", "CAI", "CAD"} for pos in positions)
    midfielders = sum(pos in {"MCD", "MC", "MI", "MD", "MP"} for pos in positions)
    attackers = sum(pos in {"EI", "ED", "DC"} for pos in positions)
    return f"{defenders}-{midfielders}-{attackers}"


def ensure_position_metadata(lineup: dict) -> bool:
    """Migra en memoria un once legado sin perderlo ni dejarlo en blanco."""

    if not isinstance(lineup, dict):
        return False
    had_positions = (
        len(lineup.get("posiciones_local") or []) == 11
        and len(lineup.get("posiciones_visitante") or []) == 11
    )
    local, positions_local = _lineup(lineup.get("local"), lineup.get("posiciones_local"))
    visitor, positions_visitor = _lineup(lineup.get("visitante"), lineup.get("posiciones_visitante"))
    if not local or not visitor:
        return False
    lineup["local"] = local
    lineup["visitante"] = visitor
    lineup["posiciones_local"] = positions_local
    lineup["posiciones_visitante"] = positions_visitor
    lineup["formacion_local"] = _formation(positions_local)
    lineup["formacion_visitante"] = _formation(positions_visitor)
    lineup["positions_inferred"] = bool(lineup.get("positions_inferred") or not had_positions)
    quality = dict(lineup.get("quality") or {})
    quality["positions_players"] = 22
    lineup["quality"] = quality
    return True

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
    local, positions_local = _lineup(item.get("local"), item.get("posiciones_local"))
    visitor, positions_visitor = _lineup(item.get("visitante"), item.get("posiciones_visitante"))
    key_local = _clave(item.get("clave_local"))
    key_visitor = _clave(item.get("clave_visitante"))
    if not local or not visitor or not key_local or not key_visitor:
        return None
    abs_local = _unique_names(item.get("bajas_local"), limit=8) or []
    abs_visitor = _unique_names(item.get("bajas_visitante"), limit=8) or []
    return {
        "local": local,
        "visitante": visitor,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_visitor,
        "formacion_local": _formation(positions_local),
        "formacion_visitante": _formation(positions_visitor),
        "positions_inferred": False,
        "bajas_local": abs_local,
        "bajas_visitante": abs_visitor,
        "clave_local": key_local,
        "clave_visitante": key_visitor,
        "quality": {
            "complete": True,
            "lineup_players": len(local) + len(visitor),
            "props_players": len(key_local) + len(key_visitor),
            "positions_players": len(positions_local) + len(positions_visitor),
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


def _ordered_squad(squad: list[dict]) -> list[dict]:
    order = {"goalkeeper": 0, "defence": 1, "defender": 1,
             "midfield": 2, "midfielder": 2, "offence": 3, "attacker": 3}
    unique = {}
    for raw in squad or []:
        if isinstance(raw, str):
            raw = {"name": raw, "position": ""}
        if not isinstance(raw, dict):
            continue
        name = _name(raw.get("name") or raw.get("player"))
        if name:
            unique.setdefault(name.casefold(), {"name": name, "position": raw.get("position") or ""})
    return sorted(unique.values(), key=lambda player: order.get(str(player["position"]).casefold(), 4))


def _probable_xi(squad: list[dict]) -> list[str] | None:
    players = _ordered_squad(squad)
    if len(players) < 11:
        return None
    groups = {index: [] for index in range(5)}
    for player in players:
        position = str(player["position"]).casefold()
        group = (0 if "goal" in position else 1 if "def" in position else
                 2 if "mid" in position else 3 if any(x in position for x in ("off", "attack", "forward")) else 4)
        groups[group].append(player["name"])
    selected = groups[0][:1] + groups[1][:4] + groups[2][:3] + groups[3][:3]
    for player in players:
        if len(selected) >= 11:
            break
        if player["name"] not in selected:
            selected.append(player["name"])
    return selected[:11] if len(selected) >= 11 else None


def _probable_positions(squad: list[dict], selected: list[str]) -> list[str]:
    """Conserva los grupos reales de la fuente y asigna carriles en un 4-3-3."""

    by_name = {player["name"].casefold(): _plain(player["position"]) for player in _ordered_squad(squad)}
    counters = {"def": 0, "mid": 0, "att": 0}
    slots = {
        "def": ["LI", "DFC", "DFC", "LD"],
        "mid": ["MC", "MCD", "MC"],
        "att": ["EI", "DC", "ED"],
    }
    out = []
    for index, name in enumerate(selected):
        raw = by_name.get(name.casefold(), "")
        if "GOAL" in raw or "PORT" in raw:
            out.append("POR")
            continue
        group = "def" if "DEF" in raw else "mid" if "MID" in raw else "att" if any(
            value in raw for value in ("OFF", "ATT", "FORWARD", "DELANT")
        ) else None
        if group:
            pos = slots[group][min(counters[group], len(slots[group]) - 1)]
            counters[group] += 1
            out.append(pos)
        else:
            out.append(_DEFAULT_FORMATION[index])
    return out


def _fallback_props(names: list[str], side: str, match: dict) -> list[dict]:
    stats, xg = match.get("stats") or {}, match.get("xg") or [1.0, 1.0]
    idx = 0 if side == "home" else 1
    side_key = "home" if side == "home" else "away"
    shots = float((stats.get("shots") or {}).get(side_key) or 10)
    sot = float((stats.get("sot") or {}).get(side_key) or shots * 0.34)
    fouls = float((stats.get("fouls") or {}).get(side_key) or 12)
    cards = float((stats.get("yellows") or {}).get(side_key) or 2)
    goals = float(xg[idx]) if len(xg) > idx else 1.0
    weights = (0.42, 0.30, 0.20)
    out = []
    for name, weight in zip(names[-3:][::-1], weights):
        out.append({
            "jugador": name,
            "g": round(goals * weight, 1),
            "a": round(goals * weight * 0.55, 1),
            "r": round(shots * weight, 1),
            "rp": round(sot * weight, 1),
            "fc": round(fouls / 11, 1),
            "fr": round(fouls / 11, 1),
            "t": round(min(1.5, cards / 11), 1),
        })
    return out


def build_statistical_lineup(match: dict, home_squad: list[dict], away_squad: list[dict]) -> dict | None:
    """Once completo gratuito basado en la plantilla real de football-data.org."""

    local, visitor = _probable_xi(home_squad), _probable_xi(away_squad)
    if not local or not visitor:
        return None
    positions_local = _probable_positions(home_squad, local)
    positions_visitor = _probable_positions(away_squad, visitor)
    return {
        "local": local,
        "visitante": visitor,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_visitor,
        "formacion_local": _formation(positions_local),
        "formacion_visitante": _formation(positions_visitor),
        "positions_inferred": True,
        "bajas_local": [],
        "bajas_visitante": [],
        "clave_local": _fallback_props(local, "home", match),
        "clave_visitante": _fallback_props(visitor, "away", match),
        "provider": "Motor estadístico local",
        "model": "squad-stats-v1",
        "quality": {
            "complete": True,
            "lineup_players": 22,
            "props_players": 6,
            "positions_players": 22,
            "score": 0.78,
            "provisional": True,
        },
    }
