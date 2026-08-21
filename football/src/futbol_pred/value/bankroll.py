"""Gestión de bankroll: criterio de Kelly (con fracción de seguridad)."""

from __future__ import annotations

from dataclasses import dataclass


def kelly_fraction(prob: float, odds: float) -> float:
    """Fracción de Kelly óptima para una apuesta.

    prob = probabilidad estimada de ganar (nuestra), odds = cuota decimal.
    Devuelve 0 si no hay ventaja (nunca negativo: no apostamos en contra).
    """
    b = odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - prob
    f = (b * prob - q) / b
    return max(0.0, f)


@dataclass
class BankrollPolicy:
    """Política de staking sobre un bankroll.

    ``kelly_multiplier``: fracción de Kelly (0.25 = "quarter Kelly", habitual
    para reducir varianza). ``max_stake_pct``: tope duro por apuesta.
    """

    kelly_multiplier: float = 0.25
    max_stake_pct: float = 0.05
    min_edge: float = 0.02

    def stake(self, bankroll: float, prob: float, odds: float) -> float:
        edge = prob * odds - 1.0
        if edge < self.min_edge:
            return 0.0
        f = kelly_fraction(prob, odds) * self.kelly_multiplier
        f = min(f, self.max_stake_pct)
        return round(bankroll * f, 2)
