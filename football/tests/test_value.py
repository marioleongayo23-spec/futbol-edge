"""Tests de cuotas, Kelly y detección de value."""

import pytest

from futbol_pred.value import (
    BankrollPolicy,
    booksum_margin,
    find_value,
    kelly_fraction,
    remove_vig,
    scan_market,
)


def test_remove_vig_suma_uno():
    fair = remove_vig([2.1, 3.6, 3.4])
    assert sum(fair) == pytest.approx(1.0, abs=1e-9)


def test_margen_positivo():
    # La casa siempre cobra margen => booksum > 1.
    assert booksum_margin([2.1, 3.6, 3.4]) > 0


def test_remove_vig_power_tambien_normaliza():
    fair = remove_vig([1.5, 4.0, 7.0], method="power")
    assert sum(fair) == pytest.approx(1.0, abs=1e-6)


def test_kelly_sin_ventaja_es_cero():
    # prob justa = 1/odds => sin ventaja => stake 0.
    assert kelly_fraction(1 / 2.0, 2.0) == pytest.approx(0.0, abs=1e-9)


def test_kelly_con_ventaja_positivo():
    assert kelly_fraction(0.6, 2.0) > 0


def test_kelly_nunca_negativo():
    assert kelly_fraction(0.1, 2.0) == 0.0


def test_find_value_detecta_edge():
    # Modelo dice 55%, cuota 2.1 => edge = 0.155.
    bet = find_value(0.55, 2.1, "1x2", "1")
    assert bet.is_value
    assert bet.edge == pytest.approx(0.155, abs=1e-6)
    assert bet.fair_odds == pytest.approx(1 / 0.55, abs=1e-6)


def test_find_value_sin_edge():
    bet = find_value(0.40, 2.1, "1x2", "1")
    assert not bet.is_value


def test_scan_market_ordena_por_edge():
    probs = {"1": 0.55, "X": 0.25, "2": 0.20}
    odds = {"1": 2.1, "X": 3.6, "2": 3.4}
    bets = scan_market(probs, odds, "1x2", bankroll=1000,
                       policy=BankrollPolicy(min_edge=0.0))
    assert bets[0].edge >= bets[-1].edge
    # El '1' tiene value (0.55*2.1=1.155).
    assert any(b.selection == "1" and b.stake > 0 for b in bets)


def test_stake_respeta_tope():
    pol = BankrollPolicy(kelly_multiplier=1.0, max_stake_pct=0.05, min_edge=0.0)
    stake = pol.stake(1000, 0.9, 2.0)  # Kelly enorme, debe capar al 5%.
    assert stake <= 50.0
