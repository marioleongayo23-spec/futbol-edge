from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.referee_adjustment import RefereeAdjustmentModel, validate_referee_adjustment


def _rows(with_effect: bool = True) -> list[MatchStats]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(120):
        strict = i % 2 == 0
        referee = "J Alberola Rojas" if strict else "M Ortiz Arias"
        if with_effect:
            fouls = (16, 15) if strict else (8, 8)
            yellows = (4, 3) if strict else (1, 1)
        else:
            fouls = (12, 12)
            yellows = (2, 2)
        rows.append(MatchStats(
            "Equipo A",
            "Equipo B",
            {"fouls": fouls, "yellows": yellows, "corners": (5, 4)},
            referee=referee,
            kickoff=start + timedelta(days=7 * i),
        ))
    return rows


def test_challenger_arbitral_solo_promociona_si_reduce_mae_fuera_de_muestra():
    report = validate_referee_adjustment(_rows(with_effect=True))

    assert report["n_validation"] >= 20
    assert report["validation"]["fouls"]["referee_mae"] < report["validation"]["fouls"]["baseline_mae"]
    assert report["validation"]["yellows"]["referee_mae"] < report["validation"]["yellows"]["baseline_mae"]
    assert set(report["accepted_stats"]) == {"fouls", "yellows"}


def test_challenger_arbitral_bloquea_empate_sin_efecto():
    report = validate_referee_adjustment(_rows(with_effect=False))

    assert report["accepted"] is False
    assert report["accepted_stats"] == []
    assert report["validation"]["fouls"]["referee_mae"] == pytest.approx(report["validation"]["fouls"]["baseline_mae"])
    assert report["validation"]["yellows"]["referee_mae"] == pytest.approx(report["validation"]["yellows"]["baseline_mae"])


def test_resuelve_inicial_historica_con_nombre_completo_api_football_y_aplica_solo_stats_validadas():
    model = RefereeAdjustmentModel().fit(_rows(with_effect=True))
    context = model.context("Javier Alberola Rojas, Spain")

    assert context is not None
    assert set(context["accepted_stats"]) == {"fouls", "yellows"}
    assert context["metrics"]["fouls"]["n"] >= 50
    assert context["metrics"]["fouls"]["factor"] > 1
    assert context["metrics"]["yellows"]["factor"] > 1

    original = {
        "fouls": {"home": 11.0, "away": 12.0, "total": 23.0},
        "yellows": {"home": 2.0, "away": 2.0, "total": 4.0},
        "corners": {"home": 5.0, "away": 4.0, "total": 9.0},
    }
    adjusted, applied = model.adjust_stats(original, "Javier Alberola Rojas, Spain")

    assert set(applied) == {"fouls", "yellows"}
    assert adjusted["fouls"]["total"] > original["fouls"]["total"]
    assert adjusted["yellows"]["total"] > original["yellows"]["total"]
    assert adjusted["corners"] == original["corners"]
    assert original["fouls"]["total"] == 23.0


def test_arbitro_desconocido_no_modifica_lineas():
    model = RefereeAdjustmentModel().fit(_rows(with_effect=True))
    stats = {"fouls": {"home": 10.0, "away": 10.0, "total": 20.0}}

    adjusted, applied = model.adjust_stats(stats, "Árbitro Sin Histórico")

    assert applied == []
    assert adjusted == stats
