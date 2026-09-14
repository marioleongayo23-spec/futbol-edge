"""Tests del cliente co.uk y del modelo de mercados estadísticos."""

from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.ingest.football_data_uk import (
    FootballDataUKClient,
    MatchStats,
    season_code,
)
from futbol_pred.model.stats_markets import (
    StatsPredictor,
    apply_stat_calibration,
    calibrate_stat_markets,
    validate_temporal_decay,
)
from futbol_pred.model.market_lines import count_market


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


def test_encogido_evita_que_una_racha_dispare_la_prediccion():
    # Liga estable a ~5 córners de local. Un equipo con UN solo partido de 15
    # córners no debe proyectarse como equipo de 15: el prior de liga tira hacia
    # abajo hasta que haya muestra. Sin encogido saldría ~ (15 + rival)/2 >= 9.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        MatchStats(f"H{i % 8}", f"A{i % 8}", {"corners": (5, 4)},
                   kickoff=base + timedelta(days=i))
        for i in range(48)
    ]
    rows.append(MatchStats("Racha", "A0", {"corners": (15, 3)},
                           kickoff=base + timedelta(days=200)))
    pred = StatsPredictor().fit(
        rows, auto_temporal=False, auto_regression=False
    ).predict_fixture("Racha", "A1")
    home = pred["corners"]["home"]
    assert home < 8.0        # no dominado por la racha
    assert home > 5.0        # pero sí por encima de la media pura (el 15 pesa algo)


def test_encogido_converge_a_la_tasa_real_con_muestra():
    # Con muchos partidos del mismo signo, el encogido cede: la predicción se
    # acerca a la tasa real del equipo (9 de local) y no se queda en la liga (5).
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        MatchStats(f"H{i % 8}", f"A{i % 8}", {"corners": (5, 4)},
                   kickoff=base + timedelta(days=i))
        for i in range(48)
    ]
    rows += [
        MatchStats("Fuerte", f"A{i % 8}", {"corners": (9, 3)},
                   kickoff=base + timedelta(days=300 + 3 * i))
        for i in range(25)
    ]
    pred = StatsPredictor().fit(
        rows, auto_temporal=False, auto_regression=False
    ).predict_fixture("Fuerte", "A1")
    # 25 partidos de local a 9: el propio término tira claramente por encima de 5.
    assert pred["corners"]["home"] > 6.8


def test_combine_multiplicativo_compone_y_acota():
    # liga=5, ataque 1.5x y defensa 1.5x -> 5*1.5*1.5=11.25 (compone),
    # más que la media aritmética (7.5) que se quedaba a medio camino.
    assert StatsPredictor._combine(7.5, 7.5, 5.0) == pytest.approx(11.25)
    # Multiplicador extremo (5x) se corta al tope de la banda (2x).
    assert StatsPredictor._combine(25.0, 5.0, 5.0) == pytest.approx(5.0 * 2.0 * 1.0)
    # Sin media de liga válida cae a la media aritmética clásica.
    assert StatsPredictor._combine(6.0, 4.0, 0.0) == pytest.approx(5.0)


def test_recency_all_stats_pondera_lo_reciente_en_todas_las_stats():
    # Un equipo que pasó de 3 córners de local (histórico) a 11 (reciente).
    # 'flat' promedia todo; con recency_all_stats lo reciente manda, aunque el
    # gate temporal no promocione el stat.
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        MatchStats("A", "B", {"corners": (3 if i < 40 else 11, 2)},
                   kickoff=base + timedelta(days=7 * i))
        for i in range(60)
    ]
    flat = StatsPredictor().fit(rows, auto_temporal=False, auto_regression=False)
    recent = StatsPredictor().fit(
        rows, auto_temporal=False, auto_regression=False,
        recency_all_stats=True, half_life_days=120,
    )
    flat_home = flat.predict_fixture("A", "B")["corners"]["home"]
    recent_home = recent.predict_fixture("A", "B")["corners"]["home"]
    assert recent_home > flat_home        # la forma reciente pesa más
    assert recent_home > 7.0              # claramente tirado hacia el 11 reciente


def test_apply_stat_calibration_identidad_y_acotada():
    assert apply_stat_calibration(0.6, None) == pytest.approx(0.6)   # sin cal -> identidad
    # Empuje fuerte hacia arriba, pero acotado a +0.15.
    assert apply_stat_calibration(0.6, (3.0, 2.0)) == pytest.approx(0.75)
    # Empuje fuerte hacia abajo, acotado a -0.15.
    assert apply_stat_calibration(0.6, (3.0, -2.0)) == pytest.approx(0.45)


def test_count_market_aplica_calibracion():
    base = count_market("corners", 9.0, 1.0)
    bajado = count_market("corners", 9.0, 1.0, calibration=(3.0, -2.0))
    # La calibración a la baja reduce la P(over) de la línea principal.
    b_over = next(l for l in base["lines"] if l["main"])["over"]
    c_over = next(l for l in bajado["lines"] if l["main"])["over"]
    assert c_over < b_over


def test_calibracion_detecta_y_corrige_sesgo_fuera_de_muestra():
    # Datos con córners casi constantes (~9): el modelo Poisson/NB predice ~30%
    # de over en la línea 9.5, pero el over real es ~0. La calibración debe
    # detectarlo, aprender una corrección y reducir el log-loss.
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        MatchStats("A", "B", {"corners": (5, 4)}, kickoff=base + timedelta(days=4 * i))
        for i in range(180)
    ]
    report = calibrate_stat_markets(rows)
    corners = report["by_stat"]["corners"]
    assert corners["n"] >= 40
    assert "platt" in corners
    assert corners["calibrated_log_loss"] < corners["base_log_loss"]
    assert corners["accepted"] is True
    assert "corners" in report["calibration"]


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
