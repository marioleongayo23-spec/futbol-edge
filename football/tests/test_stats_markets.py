"""Tests del cliente co.uk y del modelo de mercados estadísticos."""

import pytest

from futbol_pred.ingest.football_data_uk import (
    FootballDataUKClient,
    MatchStats,
    season_code,
)
from futbol_pred.model.stats_markets import StatsPredictor


def test_season_code():
    assert season_code(2025) == "2526"
    assert season_code(2024) == "2425"


def test_parse_csv_minimo():
    csv_text = (
        "Div,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST,HC,AC,HF,AF,HY,AY,HR,AR\n"
        "SP1,Barcelona,Sevilla,3,0,18,6,8,2,9,3,10,14,1,3,0,0\n"
    )
    rows = FootballDataUKClient.parse(csv_text)
    assert len(rows) == 1
    r = rows[0]
    assert r.home_team == "Barcelona" and r.away_team == "Sevilla"
    assert r.stats["corners"] == (9.0, 3.0)
    assert r.stats["yellows"] == (1.0, 3.0)
    assert r.stats["goals"] == (3.0, 0.0)


def test_parsea_arbitro_y_fueras_de_juego_gratuitos():
    rows = FootballDataUKClient.parse(
        "HomeTeam,AwayTeam,HO,AO,Referee\nBarcelona,Sevilla,3,1,M. Ortiz\n"
    )
    assert rows[0].stats["offsides"] == (3.0, 1.0)
    assert rows[0].referee == "M. Ortiz"


def test_parse_ignora_filas_vacias():
    csv_text = (
        "HomeTeam,AwayTeam,HC,AC\n"
        "Barcelona,Sevilla,9,3\n"
        ",,,\n"
    )
    assert len(FootballDataUKClient.parse(csv_text)) == 1


def test_offline_da_ejemplo():
    rows = FootballDataUKClient().get_stats("laliga", 2025, offline=True)
    assert len(rows) > 0
    assert "corners" in rows[0].stats


def _sample_fit():
    # Barcelona dispara mucho en casa; Sevilla concede mucho fuera.
    matches = [
        MatchStats("Barcelona", "Getafe", {"corners": (10, 3), "yellows": (1, 4)}),
        MatchStats("Barcelona", "Cadiz", {"corners": (12, 2), "yellows": (2, 3)}),
        MatchStats("Elche", "Sevilla", {"corners": (4, 9), "yellows": (3, 2)}),
        MatchStats("Levante", "Sevilla", {"corners": (5, 8), "yellows": (2, 2)}),
    ]
    return StatsPredictor().fit(matches)


def test_predict_fixture_estructura():
    pred = _sample_fit().predict_fixture("Barcelona", "Sevilla")
    assert "corners" in pred
    c = pred["corners"]
    assert {"home", "away", "total", "home_std", "total_std"} <= set(c)
    assert c["total"] == pytest.approx(c["home"] + c["away"], abs=0.01)


def test_local_disparador_predice_mas_corners():
    pred = _sample_fit().predict_fixture("Barcelona", "Sevilla")
    # Barça (muchos córners en casa) vs Sevilla (concede fuera) => local alto.
    assert pred["corners"]["home"] > pred["corners"]["away"]


def test_prob_over_coherente():
    sp = _sample_fit()
    # Prob over baja con línea alta.
    p_baja = sp.prob_over(10.0, 8.5)
    p_alta = sp.prob_over(10.0, 12.5)
    assert p_baja > p_alta
    assert 0 <= p_alta <= 1


def test_market_over_under_suman_uno():
    m = _sample_fit().market("Barcelona", "Sevilla", "corners", "total", 9.5)
    assert m["prob_over"] + m["prob_under"] == pytest.approx(1.0, abs=1e-6)


def test_equipo_desconocido_usa_media_liga():
    # Un equipo sin historial cae a la media de liga, no rompe.
    pred = _sample_fit().predict_fixture("EquipoNuevo", "Sevilla")
    assert "corners" in pred and pred["corners"]["home"] > 0


def test_pseudo_xg_aprende_de_remates_y_tiros_a_puerta():
    rows = []
    for i in range(30):
        rows.append(MatchStats(
            "Barcelona", "Sevilla",
            {
                "shots": (16 + i % 3, 8 + i % 2),
                "sot": (7 + i % 2, 3),
                "goals": (2 + i % 2, 1),
            },
        ))
    predictor = StatsPredictor().fit(rows)
    proxy = predictor.pseudo_xg("Barcelona", "Sevilla")
    assert proxy is not None and proxy["n"] == 60
    assert proxy["home"] > proxy["away"] > 0
    assert 0 < proxy["weight"] <= 0.25


def test_negative_binomial_se_activa_con_sobredispersion():
    rows = [
        MatchStats("A", "B", {"corners": (value, 1)})
        for value in ([0, 1, 2, 18, 20] * 5)
    ]
    predictor = StatsPredictor().fit(rows)
    market = predictor.market("A", "B", "corners", "total", 9.5)
    assert market["distribution"] == "negative-binomial"
    assert market["dispersion"] > 1.05
