from futbol_pred.ingest.lineups_ai import _validate_item, build_statistical_lineup, ensure_position_metadata


def _xi(prefix):
    positions = ["Goalkeeper"] + ["Defence"] * 4 + ["Midfield"] * 3 + ["Offence"] * 3
    return [{"name": f"{prefix} {i + 1}", "position": positions[i]} for i in range(11)]


def test_ai_valida_once_y_bajas_pero_descarta_props_numericas_no_reales():
    item = {
        "local": [{"j": f"Local {i + 1}", "pos": "POR" if i == 0 else "DFC"} for i in range(11)],
        "visitante": [{"j": f"Away {i + 1}", "pos": "POR" if i == 0 else "DFC"} for i in range(11)],
        "bajas_local": ["Local lesionado (lesión)"],
        "bajas_visitante": [],
        "clave_local": [{"j": "Local 11", "g": 1.2, "a": 1, "r": 7, "rp": 4, "fc": 2, "fr": 2, "t": .2, "min": 90, "tit": 1}],
        "clave_visitante": [{"j": "Away 11", "g": 1, "a": .5, "r": 6, "rp": 3, "fc": 2, "fr": 2, "t": .2, "min": 90, "tit": 1}],
    }
    valid = _validate_item(item)
    assert valid is not None
    assert valid["clave_local"] == []
    assert valid["clave_visitante"] == []
    assert valid["best_props"] == []
    assert valid["quality"]["props_players"] == 0
    assert valid["numeric_props_source"] == "pending_real_data"


def test_once_estadistico_no_inventa_props_de_jugador():
    match = {"stats": {"shots": {"home": 15, "away": 9}}, "xg": [1.8, 0.9]}
    lineup = build_statistical_lineup(match, _xi("Local"), _xi("Away"))
    assert lineup is not None
    assert lineup["clave_local"] == [] and lineup["clave_visitante"] == []
    assert lineup["best_props"] == []
    assert lineup["quality"]["props_players"] == 0
    assert lineup["numeric_props_source"] == "pending_real_data"


def test_migracion_cache_elimina_props_no_verificados_y_conserva_reales():
    lineup = {
        "local": [f"Local {i + 1}" for i in range(11)],
        "visitante": [f"Away {i + 1}" for i in range(11)],
        "posiciones_local": ["POR"] + ["DFC"] * 10,
        "posiciones_visitante": ["POR"] + ["DFC"] * 10,
        "clave_local": [
            {"jugador": "Local 11", "r": 5, "rp": 2, "g": .5, "a": .2, "fc": 1, "fr": 1, "t": .2, "min": 80, "tit": .9},
            {"jugador": "Local 10", "r": 2.5, "rp": 1, "g": .2, "a": .2, "fc": 1, "fr": 1, "t": .1, "min": 78, "tit": 1, "source": "API-Football · players", "sample_minutes": 900},
        ],
        "clave_visitante": [],
    }
    assert ensure_position_metadata(lineup)
    assert [row["jugador"] for row in lineup["clave_local"]] == ["Local 10"]
    assert lineup["clave_visitante"] == []
