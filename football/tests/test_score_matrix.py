"""Tests del núcleo de mercados: la ScoreMatrix debe ser coherente."""

import numpy as np
import pytest

from futbol_pred.model import DixonColesModel, ScoreMatrix


@pytest.fixture
def sm() -> ScoreMatrix:
    # Lambdas típicos de un partido con ligera ventaja local.
    return DixonColesModel.matrix_from_lambdas(1.5, 1.1, rho=-0.03, max_goals=12)


def test_normaliza_a_uno(sm):
    assert sm.matrix.sum() == pytest.approx(1.0, abs=1e-9)


def test_1x2_suma_uno(sm):
    p = sm.one_x_two()
    assert set(p) == {"1", "X", "2"}
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-6)
    # Con ventaja local, el 1 debe ser más probable que el 2.
    assert p["1"] > p["2"]


def test_doble_oportunidad_coherente(sm):
    p = sm.one_x_two()
    dc = sm.double_chance()
    assert dc["1X"] == pytest.approx(p["1"] + p["X"], abs=1e-9)


def test_over_under_complementarios(sm):
    # Con línea .5 no hay push: over + under = 1.
    assert sm.over(2.5) + sm.under(2.5) == pytest.approx(1.0, abs=1e-6)
    assert sm.over(1.5) > sm.over(3.5)


def test_over_under_con_push_entero(sm):
    # Línea entera => over + under + push = 1.
    push = sm._push_total(2.0)
    assert sm.over(2.0) + sm.under(2.0) + push == pytest.approx(1.0, abs=1e-6)
    assert push > 0


def test_btts(sm):
    b = sm.btts()
    assert b["yes"] + b["no"] == pytest.approx(1.0, abs=1e-9)


def test_handicap_asiatico_entero(sm):
    ah = sm.asian_handicap(0.0, "home")
    assert set(ah) == {"win", "push", "lose"}
    assert sum(ah.values()) == pytest.approx(1.0, abs=1e-6)
    # AH 0 para el local = win coincide con prob de victoria local.
    assert ah["win"] == pytest.approx(sm.one_x_two()["1"], abs=1e-6)


def test_handicap_cuartos(sm):
    # Línea de cuarto: media de las dos contiguas, sin push neto.
    ah = sm.asian_handicap(-0.25, "home")
    assert sum(ah.values()) == pytest.approx(1.0, abs=1e-6)


def test_handicap_simetria(sm):
    # win del local con -0.5 == lose del visitante con +0.5.
    home = sm.asian_handicap(-0.5, "home")
    away = sm.asian_handicap(0.5, "away")
    assert home["win"] == pytest.approx(away["lose"], abs=1e-6)


def test_expected_goals_positivos(sm):
    eh, ea = sm.expected_goals()
    assert eh > ea > 0


def test_resumen_distribucion_da_rango_y_masa_auditable(sm):
    summary = sm.distribution_summary()
    low, median, high = summary["total_goals_p10_p50_p90"]
    assert low <= median <= high
    assert len(summary["top_scores"]) == 6
    assert 0 < summary["top_six_probability"] < 1


def test_matriz_invalida():
    with pytest.raises(ValueError):
        ScoreMatrix(np.zeros((3, 3)))
