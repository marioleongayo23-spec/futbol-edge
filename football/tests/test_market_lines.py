"""Mercados over/under/exacto: coherentes entre sí y con la matriz de goles."""

import math

import numpy as np

from futbol_pred.model.market_lines import (
    committed_scoreline,
    count_market,
    goals_market,
    prob_exact,
    prob_over,
)
from futbol_pred.model.score_matrix import ScoreMatrix


def test_poisson_over_y_exacto_conocidos():
    # Poisson(2.5): P(>2) ≈ 0.4562; P(=2) ≈ 0.2565.
    assert abs(prob_over(2.5, 2.5) - 0.4562) < 1e-3
    assert abs(prob_exact(2.5, 2) - 0.2565) < 1e-3


def test_over_mas_under_mas_push_suman_uno():
    m = count_market("corners", 9.7, dispersion=1.4)
    for row in m["lines"]:
        assert abs(row["over"] + row["under"] + row["push"] - 1.0) < 1e-6
    # La línea principal es la .5 más próxima a la media.
    assert m["main_line"] == 9.5
    assert m["pick"]["side"] in ("over", "under")


def test_sobredispersion_ensancha_la_cola():
    # Con más varianza, la probabilidad de superar una línea alta sube.
    base = prob_over(4.5, 7.5, dispersion=1.0)
    disp = prob_over(4.5, 7.5, dispersion=1.8)
    assert disp > base


def test_most_likely_es_el_maximo_de_la_pmf():
    m = count_market("yellows", 4.3, dispersion=1.2)
    k = m["most_likely"]["value"]
    assert prob_exact(4.3, k, 1.2) >= prob_exact(4.3, k + 1, 1.2)
    assert prob_exact(4.3, k, 1.2) >= prob_exact(4.3, k - 1, 1.2)


def test_goals_market_coherente_con_la_matriz():
    lam_h, lam_a = 1.6, 1.1
    mx = ScoreMatrix(np.outer(
        [np.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(8)],
        [np.exp(-lam_a) * lam_a ** j / math.factorial(j) for j in range(8)],
    ))
    gm = goals_market(mx, lam_h, lam_a, trend={"dir": "up", "pct": 8, "reason": "x"})
    over_row = next(r for r in gm["lines"] if r["line"] == 2.5)
    assert abs(over_row["over"] - mx.over(2.5)) < 1e-3  # se publica redondeado a 3 dec.
    assert gm["pick"]["side"] in ("over", "under")
    # La tendencia al alza que coincide con over se marca como coherente.
    assert "trend_agrees" in gm["pick"]


def test_committed_scoreline_elige_el_top_y_signo_coherente():
    lam_h, lam_a = 2.1, 0.7  # local claramente favorito
    mx = ScoreMatrix(np.outer(
        [np.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(8)],
        [np.exp(-lam_a) * lam_a ** j / math.factorial(j) for j in range(8)],
    ))
    probs = mx.one_x_two()
    c = committed_scoreline(mx, probs, "Local", "Visitante")
    top = mx.top_correct_scores(1)[0]
    assert c["scoreline"] == f"{top[0]}-{top[1]}"
    assert c["home_goals"] >= c["away_goals"]  # el favorito local no pierde en el pick
    assert c["sign"] == "1"
    assert c["favourite_sign"] == "1" and c["sign_aligned"] is True  # 1X2 apoya el pick
    assert c["confidence"] in ("alta", "media", "baja")


def test_committed_scoreline_honesto_cuando_el_signo_no_es_el_favorito():
    # Partido igualado: el exacto más probable es un empate corto aunque el 1X2
    # no tenga favorito claro. El texto no debe afirmar que X es el más apoyado.
    lam_h, lam_a = 1.25, 1.30
    mx = ScoreMatrix(np.outer(
        [np.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(8)],
        [np.exp(-lam_a) * lam_a ** j / math.factorial(j) for j in range(8)],
    ))
    probs = mx.one_x_two()
    c = committed_scoreline(mx, probs, "Local", "Visitante")
    if c["sign"] == "X" and c["favourite_sign"] != "X":
        assert "más apoyo" not in c["why"]
        assert c["sign_aligned"] is False
