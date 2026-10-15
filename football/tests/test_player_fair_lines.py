import pytest

from futbol_pred.player_fair_lines import fair_lines_for_prop, poisson_over


def test_poisson_over_es_monotono_y_acotado():
    p05 = poisson_over(2.0, 0.5)
    p15 = poisson_over(2.0, 1.5)
    p25 = poisson_over(2.0, 2.5)
    assert 0 < p25 < p15 < p05 < 1


def test_fair_lines_generan_probabilidades_y_cuotas_reciprocas():
    prop = {"r": 2.0, "rp": 0.9, "fc": 1.4, "fr": 1.1, "t": 0.2}
    fair = fair_lines_for_prop(prop)

    assert [row["line"] for row in fair["r"]] == [0.5, 1.5, 2.5, 3.5, 4.5]
    assert [row["line"] for row in fair["t"]] == [0.5]
    row = fair["r"][1]
    assert row["over"] + row["under"] == pytest.approx(1.0, abs=0.002)
    assert row["fair_over_odds"] == pytest.approx(1 / row["over"], abs=0.01)
    assert row["fair_under_odds"] == pytest.approx(1 / row["under"], abs=0.01)


def test_media_cero_falla_cerrado_sin_cuota_over_infinita():
    fair = fair_lines_for_prop({"r": 0, "rp": 0, "fc": 0, "fr": 0, "t": 0})
    row = fair["r"][0]
    assert row["over"] == 0.0
    assert row["under"] == 1.0
    assert row["fair_over_odds"] is None
    assert row["fair_under_odds"] == 1.0
