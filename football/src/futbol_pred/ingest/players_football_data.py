"""Rankings de jugadores desde football-data.org (endpoint /scorers).

Alternativa fiable a FBref (que bloquea a los scripts con 403). Usa la misma
clave que los fixtures y da goleadores y asistentes de la temporada en curso.
Cobertura = plan gratis: LaLiga (PD) y Champions (CL). Segunda (SD) da 403.

Devuelve la MISMA forma que fbref_players.get_top_players, para encajar sin
cambios en dashboard.build_players:
    {"goles": {"label": ..., "players": [{"rank","player","team","value"}]}, ...}

Diagnóstico:  python -m futbol_pred.ingest.players_football_data
"""

from __future__ import annotations

from ..config import LEAGUE_META
from .football_data import FootballDataClient


def _ranking(scorers: list, key: str, top: int) -> list:
    rows = []
    for s in scorers:
        v = s.get(key)
        if v:  # descarta None y 0
            rows.append((s.get("player", {}).get("name", ""),
                         s.get("team", {}).get("name", ""), int(v)))
    rows.sort(key=lambda r: r[2], reverse=True)
    return [
        {"rank": i + 1, "player": p, "team": t, "value": v}
        for i, (p, t, v) in enumerate(rows[:top]) if p
    ]


def get_top_players(season: int = 2026, league: str = "laliga", top: int = 15) -> dict | None:
    client = FootballDataClient()
    if client.offline or league not in LEAGUE_META:
        return None
    code = LEAGUE_META[league]["fd_code"]
    try:
        data = client._get(f"competitions/{code}/scorers",
                           {"limit": max(top, 20), "season": season})
    except Exception:
        return None
    scorers = data.get("scorers") or []
    if not scorers:
        return None
    out = {}
    goles = _ranking(scorers, "goals", top)
    asis = _ranking(scorers, "assists", top)
    if goles:
        out["goles"] = {"label": "Goleadores", "players": goles}
    if asis:
        out["asistencias"] = {"label": "Asistencias", "players": asis}
    return out or None


if __name__ == "__main__":
    for lg in ("laliga", "champions", "segunda"):
        res = get_top_players(league=lg)
        if res:
            cats = ", ".join(res)
            first = next(iter(res.values()))["players"][:3]
            print(f"{lg}: OK ({cats}) top3={[(p['rank'], p['player'], p['value']) for p in first]}")
        else:
            print(f"{lg}: None")
