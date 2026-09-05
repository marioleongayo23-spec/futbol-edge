"""Rankings de jugadores desde API-Football (fuente PRIMARIA del efecto cascada).

Devuelve la MISMA forma que fbref_players/players_as/players_football_data
(``{slug: {label, players[]}}``) para encajar en ``_load_players`` sin tocar el
resto del pipeline. API-Football da leaderboards por categoría con una llamada
cada uno; el presupuesto se respeta cacheando en el feed (TTL en _load_players),
no llamando en cada ejecución.

Uso diagnóstico:  python -m futbol_pred.ingest.players_api_football
"""

from __future__ import annotations

from .api_football import ApiFootballClient
from ..config import settings

# slug interno (igual que as.com/fbref) -> (endpoint API-Football, etiqueta UI).
_CATEGORIES = {
    "goles": ("topscorers", "Goleadores"),
    "asistencias": ("topassists", "Asistencias"),
    "tarjetas": ("topyellowcards", "Tarjetas"),
}


def get_top_players(season: int | None = None, league: str = "laliga",
                    top: int = 15, *, client: ApiFootballClient | None = None) -> dict | None:
    """Rankings de jugadores de API-Football por categoría. ``None`` si no hay dato."""

    season = season or settings.season
    client = client or ApiFootballClient()
    if client.offline:
        return None
    out: dict = {}
    for slug, (kind, label) in _CATEGORIES.items():
        rows = client.player_leaderboard(kind, league, season, top=top)
        if rows:
            out[slug] = {"label": label, "players": rows}
    return out or None


def _diagnose() -> None:
    for league in ("laliga", "segunda", "champions"):
        res = get_top_players(league=league) or {}
        cats = {slug: len(block.get("players") or []) for slug, block in res.items()}
        print(f"[players_api_football] {league}: {cats}")


if __name__ == "__main__":
    _diagnose()
