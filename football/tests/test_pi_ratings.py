"""Pi-ratings: reproduce el algoritmo de referencia y produce 1X2 sensato."""

import math

import pytest

from futbol_pred.backtest.pi_ratings import PiRatings, goal_diff_to_1x2
from futbol_pred.backtest.predictors import PiRatingsPredictor


def test_reproduce_ejemplo_de_referencia():
    # Ejemplo del paquete R `piratings`: dos partidos, lambda=0.035, gamma=0.7.
    #   m1: A(local) 1-2 B ; m2: B(local) 3-1 A
    r = PiRatings()
    r.update("A", "B", 1, 2)
    # weighted = 3*log10(1+1)=0.90309 ; *lambda=0.031608 ; A local baja, B visitante sube.
    w = 3 * math.log10(2) * 0.035
    assert r.home["A"] == pytest.approx(-w, abs=1e-6)
    assert r.away["A"] == pytest.approx(-w * 0.7, abs=1e-6)
    assert r.away["B"] == pytest.approx(+w, abs=1e-6)
    assert r.home["B"] == pytest.approx(+w * 0.7, abs=1e-6)

    # Antes del 2º partido, la diferencia esperada usa B local (+) y A visitante (-).
    diff = r.expected_goal_diff("B", "A")
    e = 10 ** (abs(w * 0.7) / 3) - 1
    assert diff == pytest.approx(e - (-e), abs=1e-6)


def test_equipo_nuevo_parte_de_cero():
    r = PiRatings()
    assert r.expected_goal_diff("Nuevo1", "Nuevo2") == pytest.approx(0.0)


def test_goal_diff_a_1x2_coherente():
    # Diferencia positiva -> local favorito; suma 1; empate con masa razonable.
    p = goal_diff_to_1x2(1.2, total_goals=2.6)
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-9)
    assert p["1"] > p["2"] and p["1"] > p["X"]
    # Simétrico: diferencia 0 -> local y visitante casi iguales (con ventaja nula).
    q = goal_diff_to_1x2(0.0, total_goals=2.6)
    assert q["1"] == pytest.approx(q["2"], abs=1e-6)
    assert 0.20 < q["X"] < 0.40


def test_predictor_fit_predict():
    matches = []
    teams = ["A", "B", "C", "D"]
    fid = 0
    for rnd in range(4):
        for i in range(len(teams)):
            for j in range(len(teams)):
                if i == j:
                    continue
                fid += 1
                hg = 2 if i < j else 1
                ag = 0 if i < j else 1
                matches.append({"home": teams[i], "away": teams[j],
                                "home_goals": hg, "away_goals": ag,
                                "kickoff": fid, "status": "FINISHED"})
    pred = PiRatingsPredictor().fit(matches)
    probs = pred.predict("A", "D")
    assert probs is not None
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
    assert set(probs) == {"1", "X", "2"}
    # El total medio de goles se aprende de la muestra.
    assert pred.total_goals is not None and pred.total_goals > 0
