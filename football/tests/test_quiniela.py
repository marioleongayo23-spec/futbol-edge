"""Tests del generador de quiniela."""

import pytest

from futbol_pred.quiniela import (
    MatchForecast,
    PlenoForecast,
    generate_quiniela,
)


def _forecasts(n=14):
    out = []
    for i in range(n):
        # Variamos la certeza: unos claros, otros ajustados.
        if i % 3 == 0:
            probs = {"1": 0.7, "X": 0.2, "2": 0.1}
        elif i % 3 == 1:
            probs = {"1": 0.34, "X": 0.34, "2": 0.32}  # muy incierto
        else:
            probs = {"1": 0.25, "X": 0.3, "2": 0.45}
        out.append(MatchForecast(f"Local{i}", f"Visit{i}", probs))
    return out


def test_requiere_14_partidos():
    with pytest.raises(ValueError):
        generate_quiniela(_forecasts(10))


def test_columna_base_es_signo_mas_probable():
    fc = _forecasts()
    bet = generate_quiniela(fc)
    assert bet.base[0] == "1"   # 0.7
    assert bet.base[2] == "2"   # 0.45
    assert bet.cost_columns == 1


def test_dobles_y_triples_suben_coste():
    fc = _forecasts()
    bet = generate_quiniela(fc, triples=2, doubles=3)
    assert bet.cost_columns == 3**2 * 2**3
    assert len(bet.columns()) == bet.cost_columns


def test_multiples_van_a_los_mas_inciertos():
    fc = _forecasts()
    bet = generate_quiniela(fc, triples=1)
    # El triple debe caer en un partido de máxima entropía (i%3==1).
    idx = next(iter(bet.multiples))
    assert idx % 3 == 1


def test_boleto_con_mas_columnas_sube_prob_acierto():
    fc = _forecasts()
    simple = generate_quiniela(fc)
    multiple = generate_quiniela(fc, triples=3, doubles=4)
    assert multiple.prob_all_correct(fc) > simple.prob_all_correct(fc)


def test_pleno():
    fc = _forecasts()
    pleno = PlenoForecast(
        home_goals={"0": 0.2, "1": 0.4, "2": 0.3, "M": 0.1},
        away_goals={"0": 0.5, "1": 0.3, "2": 0.15, "M": 0.05},
    )
    bet = generate_quiniela(fc, pleno=pleno)
    assert bet.pleno == ("1", "0")


def test_expected_hits_en_rango():
    fc = _forecasts()
    bet = generate_quiniela(fc)
    hits = bet.expected_hits(fc)
    assert 0 <= hits <= 14
