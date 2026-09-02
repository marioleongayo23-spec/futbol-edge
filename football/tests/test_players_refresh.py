"""Auto-refresco de rankings de jugadores: vivo (football-data.org) superpuesto
sobre la base estática, con fallback seguro si no hay fuente en vivo."""

from __future__ import annotations

from futbol_pred.ingest import players_football_data as pfd
from futbol_pred.dashboard import _load_players


def test_refresca_goleadores_y_rellena_champions(monkeypatch):
    def fake(season, league="laliga", top=15):
        if league == "laliga":
            return {"goles": {"label": "Goleadores",
                              "players": [{"rank": 1, "player": "Fresco", "team": "Real Madrid", "value": 9}]}}
        if league == "champions":
            return {"goles": {"label": "Goleadores",
                              "players": [{"rank": 1, "player": "CL Star", "team": "Bayern", "value": 6}]}}
        return None  # segunda: la fuente da 403

    monkeypatch.setattr(pfd, "get_top_players", fake)
    out = _load_players(2026)

    # LaLiga: los goleadores vienen del vivo (frescos)...
    assert out["laliga"]["rankings"]["goles"]["players"][0]["player"] == "Fresco"
    # ...y se conservan las categorías extra del estático (understat).
    extra = set(out["laliga"]["rankings"]) - {"goles", "asistencias"}
    assert extra, "deberían conservarse categorías del fichero estático"
    # Champions, que antes salía vacío, ahora se rellena.
    assert out["champions"]["rankings"]["goles"]["players"][0]["player"] == "CL Star"


def test_fallback_a_estatico_si_no_hay_vivo(monkeypatch):
    monkeypatch.setattr(pfd, "get_top_players", lambda *a, **k: None)
    out = _load_players(2026)
    # Sin fuente en vivo, se conserva el estático (nunca peor que antes).
    assert out and out.get("laliga", {}).get("rankings")
