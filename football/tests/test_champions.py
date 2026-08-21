"""Tests de las piezas específicas del sistema Champions/multi-liga."""

import warnings

import pytest

from futbol_pred.elo import EloRatings, compute_pre_match_elo
from futbol_pred.form import matches_to_long, rolling_form
from futbol_pred.normalize import UnknownTeamWarning, canonical_team, known_teams
from futbol_pred.scheduling import (
    last_complete_matchday,
    next_fixtures,
    next_league_matchday,
)


# ---- Normalización de nombres ----------------------------------------
def test_alias_laliga_a_canonico():
    assert canonical_team("Athletic Club") == "Ath Bilbao"
    assert canonical_team("Ath Bilbao") == "Ath Bilbao"
    assert canonical_team("Club Atlético de Madrid") == "Ath Madrid"
    assert canonical_team("Atletico Madrid") == "Ath Madrid"


def test_alias_ignora_acentos_y_puntuacion():
    assert canonical_team("Deportivo Alavés") == "Alaves"
    assert canonical_team("Real Betis Balompié") == "Betis"


def test_equipo_europeo():
    assert canonical_team("Manchester City FC") == "Man City"
    assert canonical_team("FC Bayern München") == "Bayern Munich"


def test_desconocido_avisa_y_no_inventa():
    with pytest.warns(UnknownTeamWarning):
        assert canonical_team("Equipo Inexistente CF") == "Equipo Inexistente CF"


def test_desconocido_strict_lanza():
    with pytest.raises(KeyError):
        canonical_team("Equipo Inexistente CF", strict=True)


def test_known_teams_incluye_laliga():
    kt = known_teams()
    assert "Barcelona" in kt and "Real Madrid" in kt


# ---- Elo ---------------------------------------------------------------
def test_elo_favorito_local_gana_puntos():
    elo = EloRatings()
    elo.ratings = {"A": 1600, "B": 1400}
    pre_h, pre_a = elo.update("A", "B", 2, 0)
    assert pre_h == 1600 and pre_a == 1400
    # Gana el favorito: sube A, baja B, pero poco (era esperado).
    assert elo.get("A") > 1600
    assert elo.get("B") < 1400


def test_elo_sorpresa_mueve_mas():
    elo1 = EloRatings()
    elo1.ratings = {"A": 1600, "B": 1400}
    elo1.update("A", "B", 1, 0)  # esperado
    fav_gain = elo1.get("A") - 1600

    elo2 = EloRatings()
    elo2.ratings = {"A": 1400, "B": 1600}
    elo2.update("A", "B", 1, 0)  # sorpresa (gana el débil)
    dog_gain = elo2.get("A") - 1400
    assert dog_gain > fav_gain


def test_elo_probabilidades_suman_uno():
    elo = EloRatings()
    p = elo.match_probabilities("A", "B")
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-9)
    # Con ratings iguales y ventaja local, el 1 supera al 2.
    assert p["1"] > p["2"]


def test_compute_pre_match_elo_sin_leakage():
    matches = [
        {"home": "A", "away": "B", "home_goals": 3, "away_goals": 0, "kickoff": 1},
        {"home": "A", "away": "C", "home_goals": 1, "away_goals": 0, "kickoff": 2},
    ]
    out = compute_pre_match_elo(matches)
    # El primer partido se predice con Elo base (nadie ha jugado aún).
    assert out[0]["elo_home_pre"] == out[0]["elo_away_pre"]
    # En el segundo, A ya llega reforzado por su goleada previa.
    assert out[1]["elo_home_pre"] > out[0]["elo_home_pre"]


# ---- Scheduling --------------------------------------------------------
def _liga_con_adelanto():
    """15 jornadas completas (10 partidos) + 2 partidos adelantados de la J19."""
    matches = []
    mid = 0
    for md in range(1, 16):
        for _ in range(10):
            matches.append({"matchday": md, "status": "FINISHED",
                            "home_goals": 1, "away_goals": 0, "kickoff": mid})
            mid += 1
    # J16: programada (no jugada)
    for _ in range(10):
        matches.append({"matchday": 16, "status": "SCHEDULED", "kickoff": 1000 + mid})
        mid += 1
    # J19 adelantada: 2 partidos ya jugados
    for _ in range(2):
        matches.append({"matchday": 19, "status": "FINISHED",
                        "home_goals": 2, "away_goals": 2, "kickoff": mid})
        mid += 1
    return matches


def test_ultima_jornada_completa_ignora_adelantos():
    m = _liga_con_adelanto()
    assert last_complete_matchday(m, teams_per_round=10) == 15
    assert next_league_matchday(m, teams_per_round=10) == 16


def test_next_fixtures_liga_devuelve_j16():
    m = _liga_con_adelanto()
    nxt = next_fixtures(m, teams_per_round=10)
    assert len(nxt) == 10
    assert all(f["matchday"] == 16 for f in nxt)


def test_next_fixtures_champions_eliminatoria_por_fecha():
    matches = [
        # Fase de liga terminada
        {"stage": "LEAGUE", "matchday": 8, "status": "FINISHED",
         "home_goals": 1, "away_goals": 1, "kickoff": 1},
        # Octavos: pendientes, fecha próxima
        {"stage": "ROUND_16", "matchday": None, "status": "SCHEDULED", "kickoff": 100},
        {"stage": "ROUND_16", "matchday": None, "status": "SCHEDULED", "kickoff": 101},
        # Cuartos: pendientes, más lejos
        {"stage": "QUARTER", "matchday": None, "status": "SCHEDULED", "kickoff": 200},
    ]
    nxt = next_fixtures(matches)
    assert len(nxt) == 2
    assert all(f["stage"] == "ROUND_16" for f in nxt)


# ---- Forma multi-competición ------------------------------------------
def test_matches_to_long_duplica_filas():
    matches = [{"home": "A", "away": "B", "home_goals": 2, "away_goals": 1,
                "kickoff": 1}]
    long = matches_to_long(matches)
    assert len(long) == 2
    home = next(r for r in long if r["is_home"])
    assert home["team"] == "A" and home["goals_for"] == 2 and home["goals_against"] == 1


def test_rolling_form_sin_leakage():
    # A juega 3 partidos; su forma en el 3º solo ve los 2 primeros.
    matches = [
        {"home": "A", "away": "B", "home_goals": 3, "away_goals": 0, "kickoff": 1},
        {"home": "A", "away": "C", "home_goals": 2, "away_goals": 0, "kickoff": 2},
        {"home": "A", "away": "D", "home_goals": 0, "away_goals": 0, "kickoff": 3},
    ]
    long = matches_to_long(matches)
    formed = rolling_form(long, windows=(2,))
    a_rows = sorted(
        [r for r in formed if r["team"] == "A"], key=lambda x: x["kickoff"]
    )
    # Primer partido: sin historial previo.
    assert a_rows[0]["gf_avg_last2"] is None
    # Tercer partido: media de goles a favor de los 2 previos = (3+2)/2 = 2.5.
    assert a_rows[2]["gf_avg_last2"] == pytest.approx(2.5)


def test_rolling_form_multicompeticion():
    # La forma en Champions se nutre también de partidos de liga.
    matches = [
        {"home": "A", "away": "X", "home_goals": 4, "away_goals": 0,
         "kickoff": 1, "competition": "league"},
        {"home": "A", "away": "Y", "home_goals": 0, "away_goals": 0,
         "kickoff": 2, "competition": "champions"},
    ]
    long = matches_to_long(matches)
    formed = rolling_form(long, windows=(5,), competition_filter=None)
    champ = next(
        r for r in formed
        if r["team"] == "A" and r["competition"] == "champions"
    )
    # Al predecir el partido de Champions, ve la goleada previa de liga.
    assert champ["gf_avg_last5"] == pytest.approx(4.0)
