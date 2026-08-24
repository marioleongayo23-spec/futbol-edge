"""Estadísticas individuales de temporada desde API-Football.

Se usa como fuente de evidencia para props cuando existe un once oficial. Si el
endpoint no está cubierto por el plan, falla cerrado y el sistema conserva su
fallback estadístico/IA anterior.
"""

from __future__ import annotations

import math
import re
import unicodedata

from .api_football import ApiFootballClient

MIN_PLAYER_MINUTES = 270


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _team_id(client: ApiFootballClient, team_name: str) -> int | None:
    if client.offline or not str(team_name).strip():
        return None
    try:
        rows = client._get("teams", {"search": team_name}).get("response") or []
    except Exception:
        return None
    if not rows:
        return None
    wanted = _key(team_name)
    chosen = min(
        rows,
        key=lambda item: 0 if _key((item.get("team") or {}).get("name")) == wanted else 1,
    )
    value = (chosen.get("team") or {}).get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _choose_stat_block(blocks: list[dict], league_id: int | None) -> dict | None:
    if league_id is not None:
        exact = [
            block for block in blocks
            if int(((block.get("league") or {}).get("id") or -1)) == int(league_id)
        ]
        if exact:
            blocks = exact
    if not blocks:
        return None
    return max(
        blocks,
        key=lambda block: _number((block.get("games") or {}).get("appearences")),
    )


def _rate_per90(total, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return round(90.0 * _number(total) / minutes, 3)


def _normalise_player(item: dict, league_id: int | None) -> dict | None:
    player = item.get("player") or {}
    block = _choose_stat_block(item.get("statistics") or [], league_id)
    if not block:
        return None
    games = block.get("games") or {}
    minutes = _number(games.get("minutes"))
    appearances = int(_number(games.get("appearences")))
    starts = int(_number(games.get("lineups")))
    if minutes < MIN_PLAYER_MINUTES or appearances <= 0:
        return None

    shots = block.get("shots") or {}
    goals = block.get("goals") or {}
    fouls = block.get("fouls") or {}
    cards = block.get("cards") or {}
    name = str(player.get("name") or "").strip()
    if not name:
        return None

    substitute_appearances = max(0, appearances - starts)
    start_equivalents = starts + 0.35 * substitute_appearances
    expected_start_minutes = (
        minutes / start_equivalents if start_equivalents > 0 else minutes / appearances
    )
    expected_start_minutes = round(max(55.0, min(90.0, expected_start_minutes)), 1)

    return {
        "player": name,
        "player_id": player.get("id"),
        "minutes": int(round(minutes)),
        "appearances": appearances,
        "starts": starts,
        "starter_rate": round(max(0.0, min(1.0, starts / appearances)), 3),
        "expected_start_minutes": expected_start_minutes,
        "per90": {
            "g": _rate_per90(goals.get("total"), minutes),
            "a": _rate_per90(goals.get("assists"), minutes),
            "r": _rate_per90(shots.get("total"), minutes),
            "rp": _rate_per90(shots.get("on"), minutes),
            "fc": _rate_per90(fouls.get("committed"), minutes),
            "fr": _rate_per90(fouls.get("drawn"), minutes),
            "t": _rate_per90(cards.get("yellow"), minutes),
        },
        "source": "API-Football · players",
        "league_id": (block.get("league") or {}).get("id"),
    }


def fetch_team_player_rates(
    client: ApiFootballClient,
    team_name: str,
    season: int,
    league_id: int | None = None,
    max_pages: int = 2,
) -> list[dict]:
    """Devuelve tasas per-90 reales de la plantilla con paginación acotada.

    El límite de páginas mantiene controlado el consumo de cuota. Una plantilla
    estándar cabe en una o dos páginas. Cualquier error devuelve [] para dejar
    actuar al fallback existente.
    """

    team_id = _team_id(client, team_name)
    if team_id is None:
        return []

    out: list[dict] = []
    for page in range(1, max(1, int(max_pages)) + 1):
        params = {"team": team_id, "season": int(season), "page": page}
        if league_id is not None:
            params["league"] = int(league_id)
        try:
            data = client._get("players", params)
        except Exception:
            return out
        for item in data.get("response") or []:
            row = _normalise_player(item, league_id)
            if row:
                out.append(row)
        paging = data.get("paging") or {}
        try:
            total_pages = int(paging.get("total") or 1)
        except (TypeError, ValueError):
            total_pages = 1
        if page >= total_pages:
            break

    unique = {}
    for row in out:
        unique[_key(row["player"])] = row
    return list(unique.values())


def props_for_official_starters(
    starters: list[str],
    rates: list[dict],
    limit: int = 5,
) -> list[dict]:
    """Convierte tasas históricas en expectativas del partido para titulares oficiales."""

    by_name = {_key(row.get("player")): row for row in rates if row.get("player")}
    candidates = []
    for starter in starters:
        history = by_name.get(_key(starter))
        if not history:
            continue
        expected_minutes = float(history["expected_start_minutes"])
        factor = expected_minutes / 90.0
        per90 = history["per90"]
        prop = {
            "jugador": starter,
            "g": round(per90["g"] * factor, 2),
            "a": round(per90["a"] * factor, 2),
            "r": round(per90["r"] * factor, 2),
            "rp": round(per90["rp"] * factor, 2),
            "fc": round(per90["fc"] * factor, 2),
            "fr": round(per90["fr"] * factor, 2),
            "t": round(per90["t"] * factor, 2),
            "min": expected_minutes,
            "tit": 1.0,
            "sample_minutes": history["minutes"],
            "source": history["source"],
        }
        # Combina señal ofensiva y contacto para no sesgar el top solo a delanteros.
        prop["evidence_score"] = round(
            3.0 * prop["g"] + 2.0 * prop["a"] + prop["r"] + 1.5 * prop["rp"]
            + 0.6 * prop["fc"] + 0.6 * prop["fr"] + prop["t"],
            3,
        )
        candidates.append(prop)

    candidates.sort(key=lambda row: row["evidence_score"], reverse=True)
    return candidates[: max(0, int(limit))]
