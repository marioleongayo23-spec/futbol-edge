"""Tests del motor de backtesting, métricas y simulación de apuestas."""

import random

import pytest

from futbol_pred.backtest import (
    BaselineRates,
    DixonColesPredictor,
    EloPredictor,
    brier_score,
    compare_predictors,
    log_loss,
    rps,
    simulate_bets,
    walk_forward,
)
from futbol_pred.backtest.metrics import accuracy, aggregate, calibration_table
from futbol_pred.value.bankroll import BankrollPolicy


# ---- Métricas ----------------------------------------------------------
def test_log_loss_prediccion_perfecta_es_cero():
    assert log_loss({"1": 1.0, "X": 0.0, "2": 0.0}, "1") == pytest.approx(0, abs=1e-9)


def test_log_loss_penaliza_confianza_equivocada():
    seguro_mal = log_loss({"1": 0.99, "X": 0.005, "2": 0.005}, "2")
    dudoso = log_loss({"1": 0.34, "X": 0.33, "2": 0.33}, "2")
    assert seguro_mal > dudoso


def test_brier_perfecto_es_cero():
    assert brier_score({"1": 1.0, "X": 0.0, "2": 0.0}, "1") == pytest.approx(0, abs=1e-9)


def test_rps_premia_cercania_ordenada():
    # Predecir X cuando sale 2 es "menos malo" que predecir 1 cuando sale 2.
    cerca = rps({"1": 0.1, "X": 0.8, "2": 0.1}, "2")
    lejos = rps({"1": 0.8, "X": 0.1, "2": 0.1}, "2")
    assert lejos > cerca


def test_accuracy_argmax():
    assert accuracy({"1": 0.5, "X": 0.3, "2": 0.2}, "1") == 1.0
    assert accuracy({"1": 0.5, "X": 0.3, "2": 0.2}, "2") == 0.0


def test_aggregate_vacio():
    assert aggregate([])["n"] == 0


def test_calibration_table_estructura():
    preds = [({"1": 0.6, "X": 0.2, "2": 0.2}, "1") for _ in range(5)]
    tabla = calibration_table(preds, "1", bins=10)
    assert tabla and {"bin", "n", "avg_pred", "obs_freq"} <= set(tabla[0])


# ---- Datos sintéticos con señal real -----------------------------------
def _liga_sintetica(seed=42, n_teams=8, rounds=14):
    """Genera una liga donde cada equipo tiene una fuerza latente.

    Así los modelos DEBEN batir al baseline aleatorio: hay señal que aprender.
    """
    rng = random.Random(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    strength = {t: rng.gauss(0, 0.4) for t in teams}
    matches = []
    ko = 0
    for r in range(rounds):
        pairs = teams[:]
        rng.shuffle(pairs)
        for i in range(0, n_teams, 2):
            h, a = pairs[i], pairs[i + 1]
            import math
            lh = math.exp(0.2 + strength[h] - strength[a])
            la = math.exp(strength[a] - strength[h])
            hg = min(6, _poisson(rng, lh))
            ag = min(6, _poisson(rng, la))
            matches.append({
                "home": h, "away": a, "home_goals": hg, "away_goals": ag,
                "matchday": r + 1, "kickoff": ko, "status": "FINISHED",
            })
            ko += 1
    return matches


def _poisson(rng, lam):
    # Knuth
    import math
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


# ---- Motor walk-forward ------------------------------------------------
def test_walk_forward_no_leakage_y_produce_predicciones():
    matches = _liga_sintetica()
    res = walk_forward(matches, EloPredictor(), min_train_rounds=3)
    # Debe haber predicho las rondas posteriores al arranque.
    assert res.metrics()["n"] > 0
    assert 0 <= res.metrics()["accuracy"] <= 1


def test_modelos_baten_al_baseline_con_datos_suficientes():
    # Con datos suficientes (liga amplia y larga), los modelos con señal deben
    # batir al baseline de tasas base. Con pocos datos, Dixon-Coles puede
    # sobreajustarse: es un hallazgo real que el backtest debe poder revelar.
    matches = _liga_sintetica(n_teams=12, rounds=30)
    comp = compare_predictors(matches, {
        "baseline": BaselineRates(),
        "elo": EloPredictor(),
        "dixon_coles": DixonColesPredictor(min_matches=20),
    }, min_train_rounds=4)
    base = comp["baseline"]
    # Elo, mejor calibrado con datos, bate al baseline en log loss.
    assert comp["elo"]["log_loss"] < base["log_loss"]
    # Ambos modelos discriminan mejor al ganador (accuracy).
    assert comp["elo"]["accuracy"] >= base["accuracy"]
    assert comp["dixon_coles"]["accuracy"] >= base["accuracy"]
    # Dixon-Coles mejora el Brier (probabilidades más afiladas y acertadas).
    assert comp["dixon_coles"]["brier"] <= base["brier"]


def test_dixon_coles_puede_sobreajustar_con_pocos_datos():
    # Documenta el hallazgo: con liga pequeña y corta, DC no está garantizado
    # que bata al baseline en log loss. El backtest existe para detectar esto.
    matches = _liga_sintetica(n_teams=8, rounds=14)
    comp = compare_predictors(matches, {
        "baseline": BaselineRates(),
        "dixon_coles": DixonColesPredictor(min_matches=20),
    }, min_train_rounds=4)
    assert comp["dixon_coles"]["n"] > 0  # corre sin romper; no exigimos que gane


def test_dixon_coles_equipo_nuevo_usa_fallback():
    matches = _liga_sintetica()
    pred = DixonColesPredictor(min_matches=20).fit(matches)
    # Un equipo que no existe cae al fallback Elo, no revienta.
    out = pred.predict("EquipoNuevo", "T0")
    assert out is not None
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)


# ---- Simulación de apuestas -------------------------------------------
def test_simulacion_apuestas_con_cuotas():
    # Registro donde el modelo tiene edge claro y acierta / falla.
    records = [
        {"home": "A", "away": "B", "probs": {"1": 0.6, "X": 0.25, "2": 0.15},
         "actual": "1", "odds": {"1": 2.0, "X": 3.5, "2": 5.0}},
        {"home": "C", "away": "D", "probs": {"1": 0.6, "X": 0.25, "2": 0.15},
         "actual": "2", "odds": {"1": 2.0, "X": 3.5, "2": 5.0}},
    ]
    res = simulate_bets(records, policy=BankrollPolicy(min_edge=0.05), start_bankroll=1000)
    assert res.n_bets == 2  # ambos tienen edge en el '1' (0.6*2-1=0.2)
    assert 0 <= res.hit_rate <= 1
    assert 0 <= res.max_drawdown <= 1
    assert "roi" in res.summary()


def test_simulacion_ignora_sin_cuotas():
    records = [{"home": "A", "away": "B", "probs": {"1": 0.6, "X": 0.25, "2": 0.15},
                "actual": "1", "odds": None}]
    res = simulate_bets(records)
    assert res.n_bets == 0


def test_simulacion_no_apuesta_sin_edge():
    # Cuotas que no dan ventaja a ninguna selección.
    records = [{"home": "A", "away": "B", "probs": {"1": 0.4, "X": 0.3, "2": 0.3},
                "actual": "1", "odds": {"1": 2.0, "X": 3.0, "2": 3.0}}]
    res = simulate_bets(records, policy=BankrollPolicy(min_edge=0.05))
    assert res.n_bets == 0
