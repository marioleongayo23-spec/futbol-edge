from datetime import datetime, timedelta

from futbol_pred.hot_refresh import MADRID
from futbol_pred.matchday_player_props_fill import MODEL_SOURCE, refresh_payload


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MCD", "MC", "MP", "EI", "DC", "ED"]


def _match(now):
    kickoff = now + timedelta(minutes=45)
    return {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "xg": [1.8, 1.1],
        "stats": {
            "shots": {"home": 14.0, "away": 9.0},
            "sot": {"home": 5.2, "away": 3.3},
            "fouls": {"home": 11.0, "away": 13.0},
            "yellows": {"home": 2.0, "away": 2.6},
        },
        "alineacion": {
            "status": "probable",
            "local": [f"Local {i}" for i in range(11)],
            "visitante": [f"Visitante {i}" for i in range(11)],
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
            "clave_local": [],
            "clave_visitante": [],
        },
    }


def test_matchday_props_fill_guarantees_22_predictive_rows_without_real_sample():
    now = datetime(2026, 8, 27, 20, 0, tzinfo=MADRID)
    payload = {"matches": [_match(now)]}

    changed, stats = refresh_payload(payload, now=now)
    lineup = payload["matches"][0]["alineacion"]

    assert changed is True
    assert len(lineup["clave_local"]) == 11
    assert len(lineup["clave_visitante"]) == 11
    assert stats["covered_players"] == 22
    assert stats["real_players"] == 0
    assert stats["model_players"] == 22
    assert lineup["quality"]["predicted_player_props"] == 22
    assert lineup["quality"]["real_player_props"] == 0
    assert all(row["source"] == MODEL_SOURCE for row in lineup["clave_local"] + lineup["clave_visitante"])
    assert all(row["r"] >= 0 and row["rp"] >= 0 and row["fc"] >= 0 and row["fr"] >= 0 for row in lineup["clave_local"] + lineup["clave_visitante"])

    # Sin muestra real, las expectativas individuales deben cuadrar con el total de equipo.
    assert abs(sum(row["r"] for row in lineup["clave_local"]) - 14.0) <= 0.08
    assert abs(sum(row["rp"] for row in lineup["clave_local"]) - 5.2) <= 0.08
    assert abs(sum(row["fc"] for row in lineup["clave_local"]) - 11.0) <= 0.08


def test_matchday_props_fill_preserves_real_projection_and_fills_other_players():
    now = datetime(2026, 8, 27, 20, 0, tzinfo=MADRID)
    match = _match(now)
    real = {
        "jugador": "Local 9",
        "g": .52, "a": .10, "r": 3.1, "rp": 1.45,
        "fc": .7, "fr": 1.2, "t": .16,
        "min": 84, "tit": .96,
        "sample_minutes": 720,
        "source": "API-Football · players",
    }
    match["alineacion"]["clave_local"] = [real]
    payload = {"matches": [match]}

    changed, stats = refresh_payload(payload, now=now)
    local = payload["matches"][0]["alineacion"]["clave_local"]
    by_name = {row["jugador"]: row for row in local}

    assert changed is True
    assert len(local) == 11
    assert stats["real_players"] == 1
    assert stats["model_players"] == 21
    assert by_name["Local 9"]["source"] == "API-Football · players"
    assert by_name["Local 9"]["sample_minutes"] == 720
    assert by_name["Local 0"]["source"] == MODEL_SOURCE
    assert payload["matches"][0]["alineacion"]["player_props_source"].startswith("Predictivo híbrido · 1/22")


def test_matchday_props_fill_skips_non_critical_or_incomplete_lineup():
    now = datetime(2026, 8, 27, 10, 0, tzinfo=MADRID)
    match = _match(now)
    match["kickoff"] = (now + timedelta(hours=5)).isoformat()
    payload = {"matches": [match]}

    changed, stats = refresh_payload(payload, now=now)

    # Los PROPS de día de partido siguen SIN rellenarse fuera del momento crítico
    # (clave_local vacío, ningún partido crítico procesado)...
    assert stats["matches"] == 0
    assert payload["matches"][0]["alineacion"]["clave_local"] == []
    # ...pero el Top-5 por jugador SÍ se refresca desde el once vigente (ventana de
    # 10 días) para no quedarse con una foto antigua de la plantilla.
    assert stats.get("player_markets_refreshed", 0) == 1
    assert changed is True


def test_refresh_payload_sobrevive_entorno_ligero_sin_scipy(monkeypatch):
    # El hot-refresh instala solo 'requests' (sin numpy/scipy). Si el import del
    # modelo del Top-5 falla, refresh_payload debe OMITIRLO sin tumbar el feed;
    # el pipeline pesado (futbol-pred) ya lo refresca.
    import futbol_pred.matchday_player_props_fill as mod

    def _boom(*args, **kwargs):
        raise ImportError("No module named 'scipy'")

    monkeypatch.setattr(mod, "attach_player_markets", _boom)
    now = datetime(2026, 8, 27, 10, 0, tzinfo=MADRID)
    match = _match(now)
    match["kickoff"] = (now + timedelta(hours=5)).isoformat()
    changed, stats = mod.refresh_payload({"matches": [match]}, now=now)  # no debe lanzar
    assert "player_markets_refreshed" not in stats
