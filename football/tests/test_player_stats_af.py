"""Stats de jugadores desde API-Football (fuente primaria) + efecto cascada
API-Football -> football-data -> estático, con caché por TTL en el feed."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from futbol_pred.ingest.api_football import ApiFootballClient
from futbol_pred.ingest import players_api_football as paf
from futbol_pred.ingest import players_football_data as pfd
from futbol_pred.dashboard import _cascade_rankings, _load_players


class FakeAF(ApiFootballClient):
    """Cliente con respuestas canónicas de API-Football (no toca la red)."""

    def __init__(self, payloads):
        super().__init__(api_key="x")  # con clave -> no offline
        self._payloads = payloads

    def _get(self, path, params):
        return self._payloads.get(path, {"response": []})


def test_player_leaderboard_parsea_topscorers():
    client = FakeAF({"players/topscorers": {"response": [
        {"player": {"name": "Lewandowski"},
         "statistics": [{"team": {"name": "Barcelona"}, "goals": {"total": 12, "assists": 3}}]},
        {"player": {"name": "Vinicius"},
         "statistics": [{"team": {"name": "Real Madrid"}, "goals": {"total": 9}}]},
    ]}})
    rows = client.player_leaderboard("topscorers", "laliga", 2026)
    assert rows[0] == {"rank": 1, "player": "Lewandowski", "team": "Barcelona", "value": 12.0}
    assert rows[1]["player"] == "Vinicius" and rows[1]["value"] == 9.0


def test_player_leaderboard_offline_o_liga_desconocida():
    assert ApiFootballClient(api_key=None).player_leaderboard("topscorers", "laliga") == []
    assert FakeAF({}).player_leaderboard("topscorers", "liga_inexistente") == []


def test_players_api_football_shape():
    client = FakeAF({
        "players/topscorers": {"response": [
            {"player": {"name": "G"}, "statistics": [{"team": {"name": "A"}, "goals": {"total": 5}}]}]},
        "players/topassists": {"response": [
            {"player": {"name": "A1"}, "statistics": [{"team": {"name": "B"}, "goals": {"assists": 7}}]}]},
        "players/topyellowcards": {"response": []},
    })
    out = paf.get_top_players(2026, league="laliga", client=client)
    assert out["goles"]["players"][0]["player"] == "G"
    assert out["asistencias"]["label"] == "Asistencias"
    assert "tarjetas" not in out  # sin filas no se inventa la categoría


def test_cascade_rankings_prioridad_y_relleno():
    af = {"goles": {"label": "Goleadores", "players": [{"player": "AF"}]}}
    fd = {"goles": {"label": "Goleadores", "players": [{"player": "FD"}]},
          "asistencias": {"label": "Asistencias", "players": [{"player": "FDa"}]}}
    static = {"minutos": {"label": "Minutos", "players": [{"player": "S"}]},
              "asistencias": {"label": "Asistencias", "players": [{"player": "Sa"}]}}
    merged = _cascade_rankings(af, fd, static)
    assert merged["goles"]["players"][0]["player"] == "AF"        # API-Football manda
    assert merged["asistencias"]["players"][0]["player"] == "FDa"  # football-data rellena
    assert merged["minutos"]["players"][0]["player"] == "S"        # el estático rellena el resto


def test_load_players_ttl_reusa_cache_sin_llamar_api(monkeypatch):
    # Con caché fresca en el feed, NO se debe volver a llamar a API-Football.
    called = {"af": 0}

    def boom(*a, **k):
        called["af"] += 1
        return {"goles": {"label": "Goleadores",
                          "players": [{"rank": 1, "player": "NUEVO", "team": "X", "value": 1}]}}

    monkeypatch.setattr(paf, "get_top_players", boom)
    monkeypatch.setattr(pfd, "get_top_players", lambda *a, **k: None)  # sin red
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    previous = {"player_rankings_meta": {
        "af_fetched_at": (now - timedelta(hours=2)).isoformat(),
        "af": {"laliga": {"goles": {"label": "Goleadores",
                                    "players": [{"rank": 1, "player": "CACHED", "team": "Y", "value": 3}]}}},
    }}
    meta_out: dict = {}
    out = _load_players(2026, previous=previous, now=now, _meta_out=meta_out)
    assert called["af"] == 0                                              # presupuesto respetado
    assert out["laliga"]["rankings"]["goles"]["players"][0]["player"] == "CACHED"
    assert meta_out["player_rankings_meta"]["af"]["laliga"]               # conserva la caché


def test_load_players_ttl_refresca_completo_si_caduca(monkeypatch):
    called = {"af": 0}

    def fresh(season, league="laliga", top=15, **k):
        called["af"] += 1
        return {"goles": {"label": "Goleadores",
                          "players": [{"rank": 1, "player": f"FRESCO-{league}", "team": "X", "value": 1}]}}

    monkeypatch.setattr(paf, "get_top_players", fresh)
    monkeypatch.setattr(pfd, "get_top_players", lambda *a, **k: None)
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    previous = {"player_rankings_meta": {
        "af_fetched_at": (now - timedelta(hours=40)).isoformat(), "af": {}}}
    meta_out: dict = {}
    out = _load_players(2026, previous=previous, now=now, _meta_out=meta_out)
    assert called["af"] == 3                                              # las 3 ligas
    assert out["laliga"]["rankings"]["goles"]["players"][0]["player"] == "FRESCO-laliga"
    m = meta_out["player_rankings_meta"]
    assert m["af_fetched_at"] == now.isoformat()      # refresco COMPLETO -> fresco ahora
    assert m["af_attempted_at"] == now.isoformat()


def test_load_players_backoff_tras_refresco_vacio(monkeypatch):
    # P1: un refresco caducado que vuelve VACÍO no debe reintentar en cada build.
    called = {"af": 0}

    def empty(season, league="laliga", top=15, **k):
        called["af"] += 1
        return None

    monkeypatch.setattr(paf, "get_top_players", empty)
    monkeypatch.setattr(pfd, "get_top_players", lambda *a, **k: None)
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    cached = {"laliga": {"goles": {"label": "Goleadores",
                                   "players": [{"rank": 1, "player": "OLD", "team": "Y", "value": 2}]}}}
    previous = {"player_rankings_meta": {
        "af_fetched_at": (now - timedelta(hours=40)).isoformat(), "af": cached}}
    meta_out: dict = {}
    out = _load_players(2026, previous=previous, now=now, _meta_out=meta_out)
    assert called["af"] == 3                                    # intentó (caducado)...
    assert out["laliga"]["rankings"]["goles"]["players"][0]["player"] == "OLD"  # ...pero no se pierde
    m = meta_out["player_rankings_meta"]
    assert m["af_attempted_at"] == now.isoformat()             # backoff registrado
    assert m["af"]["laliga"]                                   # caché conservada

    # Segundo build 1h después: dentro del backoff -> NO vuelve a intentar.
    called["af"] = 0
    out2 = _load_players(2026, previous={"player_rankings_meta": m},
                         now=now + timedelta(hours=1), _meta_out={})
    assert called["af"] == 0                                    # presupuesto respetado
    assert out2["laliga"]["rankings"]["goles"]["players"][0]["player"] == "OLD"


def test_load_players_parcial_conserva_ligas(monkeypatch):
    # P2: si hoy solo responde laliga, champions cacheado NO se pierde y NO se
    # marca como refresco completo (se reintentará champions tras el backoff).
    def partial(season, league="laliga", top=15, **k):
        if league == "laliga":
            return {"goles": {"label": "Goleadores",
                              "players": [{"rank": 1, "player": "LA-NEW", "team": "X", "value": 9}]}}
        return None

    monkeypatch.setattr(paf, "get_top_players", partial)
    monkeypatch.setattr(pfd, "get_top_players", lambda *a, **k: None)
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    cached = {"champions": {"goles": {"label": "Goleadores",
                                      "players": [{"rank": 1, "player": "CL-OLD", "team": "Bayern", "value": 6}]}}}
    previous = {"player_rankings_meta": {
        "af_fetched_at": (now - timedelta(hours=40)).isoformat(), "af": cached}}
    meta_out: dict = {}
    out = _load_players(2026, previous=previous, now=now, _meta_out=meta_out)
    assert out["laliga"]["rankings"]["goles"]["players"][0]["player"] == "LA-NEW"      # nuevo
    assert out["champions"]["rankings"]["goles"]["players"][0]["player"] == "CL-OLD"   # conservado
    m = meta_out["player_rankings_meta"]
    assert m["af"]["champions"]                                # champions no se pierde
    assert m["af_fetched_at"] == previous["player_rankings_meta"]["af_fetched_at"]  # parcial != completo
