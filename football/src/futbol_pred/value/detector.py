"""Detección de value bets: compara probabilidad del modelo vs. cuota."""

from __future__ import annotations

from dataclasses import dataclass

from .bankroll import BankrollPolicy


@dataclass
class ValueBet:
    market: str
    selection: str
    model_prob: float
    odds: float
    edge: float          # prob*odds - 1  (valor esperado por unidad apostada)
    fair_odds: float     # cuota justa según el modelo
    stake: float = 0.0

    @property
    def is_value(self) -> bool:
        return self.edge > 0


def find_value(
    model_prob: float,
    odds: float,
    market: str,
    selection: str,
    bankroll: float | None = None,
    policy: BankrollPolicy | None = None,
) -> ValueBet:
    edge = model_prob * odds - 1.0
    fair = 1.0 / model_prob if model_prob > 0 else float("inf")
    bet = ValueBet(
        market=market,
        selection=selection,
        model_prob=model_prob,
        odds=odds,
        edge=edge,
        fair_odds=fair,
    )
    if bankroll is not None:
        pol = policy or BankrollPolicy()
        bet.stake = pol.stake(bankroll, model_prob, odds)
    return bet


def scan_market(
    probs: dict[str, float],
    market_odds: dict[str, float],
    market: str,
    bankroll: float | None = None,
    policy: BankrollPolicy | None = None,
    min_edge: float = 0.0,
) -> list[ValueBet]:
    """Escanea todas las selecciones de un mercado y devuelve las de value.

    ``probs`` y ``market_odds`` comparten claves (p. ej. {'1','X','2'}).
    """
    bets: list[ValueBet] = []
    for sel, p in probs.items():
        if sel not in market_odds:
            continue
        bet = find_value(
            p, market_odds[sel], market, sel, bankroll=bankroll, policy=policy
        )
        if bet.edge > min_edge:
            bets.append(bet)
    bets.sort(key=lambda b: b.edge, reverse=True)
    return bets
