"""Tests del cliente co.uk y del modelo de mercados estadísticos."""

from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.ingest.football_data_uk import (
    FootballDataUKClient,
    MatchStats,
    season_code,
)
from futbol_pred.model.stats_markets import StatsPredictor, validate_temporal_decay


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
    assert r.kickoff is None


def test_parsea_arbitro_y_fueras_de_juego_gratuitos():
    rows = FootballDataUKClient.parse(
        "HomeTeam,AwayTeam,HO,AO,Referee\nBarcelona,Sevilla,3,1,M. Ortiz\n"
    )
    assert rows[0].stats["offsides"] == (3.0, 1.0)
    assert rows[0].referee == "M. Ortiz"


def test_parsea_fecha_y_hora_para_validacion_temporal():
    rows = FootballDataUKClient.parse(
        "Date,Time,HomeTeam,AwayTeam,HC,AC\n24/08/2026,21:30,Barcelona,Sevilla,8,4\n"
    )
    kickoff = rows[0].kickoff
    assert kickoff is not None
    assert (kickoff.year, kickoff.month, kickoff.day) == (2026, 8, 24)
    assert (kickoff.hour, kickoff.minute) == (21, 30)
    assert kickoff.tzinfo is not None


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
    assert pred["corners"]["home"] > pred["corners"]["away"]


def test_prob_over_coherente():
    sp = _sample_fit()
    p_baja = sp.prob_over(10.0, 8.5)
    p_alta = sp.prob_over(10.0, 12.5)
    assert p_baja > p_alta
    assert 0 <= p_alta <= 1


def test_market_over_under_suman_uno():
    m = _sample_fit().market("Barcelona", "Sevilla", "corners", "total", 9.5)
    assert m["prob_over"] + m["prob_under"] == pytest.approx(1.0, abs=1e-6)


def test_equipo_desconocido_usa_media_liga():
    pred = _sample_fit().predict_fixture("EquipoNuevo", "Sevilla")
    assert "corners" in pred and pred["corners"]["home"] > 0


def test_pseudo_xg_aprende_de_remates_y_tiros_a_puerta():
    rows = []
    for i in range(30):
        rows.append(MatchStats(
            "Barcelona", "Sevilla",
            {"shots": (16 + i % 3, 8 + i % 2), "sot": (7 + i % 2, 3), "goals": (2 + i % 2, 1)},
        ))
    predictor = StatsPredictor().fit(rows)
    proxy = predictor.pseudo_xg("Barcelona", "Sevilla")
    assert proxy is not None and proxy["n"] == 60
    assert proxy["home"] > proxy["away"] > 0
    assert 0 < proxy["weight"] <= 0.25


def test_negative_binomial_se_activa_con_sobredispersion():
    rows = [MatchStats("A", "B", {"corners": (value, 1)}) for value in ([0, 1, 2, 18, 20] * 5)]
    predictor = StatsPredictor().fit(rows)
    market = predictor.market("A", "B", "corners", "total", 9.5)
    assert market["distribution"] == "negative-binomial"
    assert market["dispersion"] > 1.05


def _dated_regime_rows(changing: bool) -> list[MatchStats]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(120):
        home_corners = 3 if changing and i < 70 else 11 if changing else 6
        rows.append(MatchStats(
            "A", "B", {"corners": (home_corners, 2)},
            kickoff=start + timedelta(days=7 * i),
        ))
    return rows


def test_temporal_challenger_activa_solo_si_reduce_mae_fuera_de_muestra():
    rows = _dated_regime_rows(changing=True)
    report = validate_temporal_decay(rows)
    corners = report["validation"]["corners"]
    assert report["n_validation"] >= 20
    assert corners["temporal_mae"] < corners["baseline_mae"]
    assert corners["accepted"] is True
    assert "corners" in report["accepted_stats"]

    predictor = StatsPredictor().fit(rows)
    assert "corners" in predictor.temporal_stats
    assert predictor.temporal_validation["gate"] == "strictly_lower_mae_per_stat"


def test_temporal_challenger_no_promociona_empates():
    rows = _dated_regime_rows(changing=False)
    report = validate_temporal_decay(rows)
    corners = report["validation"]["corners"]
    assert corners["temporal_mae"] == pytest.approx(corners["baseline_mae"])
    assert corners["accepted"] is False
    assert "corners" not in report["accepted_stats"]


def _primary_league_rows() -> list[MatchStats]:
    rows = []
    for i in range(30):
        rows.append(MatchStats(
            "Primera A", "Primera B",
            {"shots": (12 + i % 2, 10), "sot": (4, 3), "goals": (1, 1), "corners": (5, 4)},
            kickoff=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=7 * i),
        ))
    return rows


def _segunda_promoted_rows() -> list[MatchStats]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        MatchStats(
            "Ascendido", f"Rival {i}",
            {"shots": (19, 8), "sot": (7, 2), "goals": (2, 1), "corners": (9, 3)},
            kickoff=start + timedelta(days=7 * i),
        )
        for i in range(20)
    ]


def test_historico_auxiliar_da_memoria_al_ascendido_sin_contaminar_media_liga():
    primary = _primary_league_rows()
    auxiliary = _segunda_promoted_rows()
    baseline = StatsPredictor().fit(primary, auto_temporal=False)
    promoted = StatsPredictor().fit(primary, auxiliary_matches=auxiliary, auto_temporal=False)

    neutral = baseline.predict_fixture("Ascendido", "Primera B")["corners"]["home"]
    inherited = promoted.predict_fixture("Ascendido", "Primera B")["corners"]["home"]
    assert inherited > neutral
    assert promoted.auxiliary_rows == len(auxiliary)
    assert "Ascendido" in promoted.auxiliary_teams

    assert promoted.league_home["corners"].for_avg == pytest.approx(baseline.league_home["corners"].for_avg)
    assert promoted.league_away["corners"].for_avg == pytest.approx(baseline.league_away["corners"].for_avg)
    assert promoted.dispersion("corners") == pytest.approx(baseline.dispersion("corners"))


def test_auxiliar_no_entra_en_pseudo_xg_ni_gate_temporal():
    primary = _dated_regime_rows(changing=True)
    auxiliary = _segunda_promoted_rows()
    baseline = StatsPredictor().fit(primary)
    enriched = StatsPredictor().fit(primary, auxiliary_matches=auxiliary)

    assert enriched.temporal_validation == baseline.temporal_validation
    assert enriched.temporal_stats == baseline.temporal_stats
    assert enriched.xg_rows == baseline.xg_rows
    assert enriched.xg_coefficients == baseline.xg_coefficients


def test_auxiliar_no_cambia_fallback_de_equipo_sin_historial():
    primary = _primary_league_rows()
    auxiliary = _segunda_promoted_rows()
    baseline = StatsPredictor().fit(primary, auto_temporal=False)
    enriched = StatsPredictor().fit(primary, auxiliary_matches=auxiliary, auto_temporal=False)

    assert enriched.predict_fixture("Otro equipo", "Primera B") == baseline.predict_fixture("Otro equipo", "Primera B")
