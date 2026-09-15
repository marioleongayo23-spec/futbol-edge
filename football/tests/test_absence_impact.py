"""Impacto cuantificado de las bajas (informativo, no altera la predicción)."""

from futbol_pred.matchday_absence_impact import attach_absence_impact, _side_impact, _build_lookup


def _players():
    return {"laliga": {"players": [
        {"player": "Robert Lewandowski", "team": "FC Barcelona", "goals": 12, "assists": 3},
        {"player": "Lamine Yamal", "team": "FC Barcelona", "goals": 4, "assists": 8},
        {"player": "Iñaki Peña", "team": "FC Barcelona", "goals": 0, "assists": 0},
        {"player": "Jugador Rival", "team": "Levante UD", "goals": 1, "assists": 0},
    ]}}


def test_impacto_alto_por_goleador_ausente():
    matches = [{
        "home": "FC Barcelona", "away": "Levante UD",
        "alineacion": {
            "bajas_local": ["Robert Lewandowski (Lesión muscular)"],
            "bajas_visitante": ["Jugador Rival (Sanción)"],
        },
    }]
    n = attach_absence_impact(matches, _players())
    assert n == 1
    imp = matches[0]["alineacion"]["impacto_bajas"]
    # Local pierde a un goleador (12 goles) -> impacto alto.
    assert imp["local"]["nivel"] == "alto"
    assert imp["local"]["clave"][0]["jugador"] == "Robert Lewandowski"
    # Visitante pierde a un jugador menor -> impacto bajo.
    assert imp["visitante"]["nivel"] == "bajo"


def test_baja_de_suplente_sin_aportacion_es_bajo():
    lookup = _build_lookup(_players())
    imp = _side_impact("FC Barcelona", ["Iñaki Peña (Molestias)"], lookup)
    assert imp["nivel"] == "bajo" and imp["score"] == 0.0 and imp["clave"] == []


def test_sin_jugadores_es_no_op():
    matches = [{"home": "A", "away": "B", "alineacion": {"bajas_local": ["X"]}}]
    assert attach_absence_impact(matches, None) == 0
    assert "impacto_bajas" not in matches[0]["alineacion"]


def test_normaliza_acentos_y_motivo():
    # El nombre en la baja lleva acento y motivo; debe cruzar igual.
    players = {"laliga": {"players": [
        {"player": "Iñaki Williams", "team": "Athletic Club", "goals": 6, "assists": 2}]}}
    lookup = _build_lookup(players)
    imp = _side_impact("Athletic Club", ["Inaki Williams (Convocatoria selección)"], lookup)
    assert imp["nivel"] in ("medio", "alto") and imp["clave"][0]["goles"] == 6
