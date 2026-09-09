"""Modelo de fricción de ejecución por instrumento.

Toda métrica se juzga sobre retornos NETOS. Componentes:
  - Comisión: bps sobre el nocional ejecutado.
  - Diferencial (bid/ask): medio diferencial por lado, en bps.
  - Deslizamiento: proporcional a la volatilidad del bar.
  - Impacto de mercado: ley de la raíz cuadrada  ~ coef · sigma · sqrt(Q/ADV).
  - Fills parciales: la ejecución se limita a `max_participation · volumen`.
  - Latencia: retardo de `latency_bars` (lo aplica el motor de backtest).
  - Impuestos: tasa sobre la ganancia neta positiva (anual).

Los parámetros son deliberadamente conservadores y configurables por instrumento
(config/costs.yaml). Se prueban además escenarios peores (x1.5, x2) en la puerta.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class InstrumentCosts:
    commission_bps: float = 1.0      # 0,01% del nocional
    half_spread_bps: float = 2.0     # medio diferencial por lado
    slippage_coef: float = 0.05      # fracción de la sigma del bar
    impact_coef: float = 0.5         # coeficiente de la ley raíz cuadrada
    adv_value: float = 5.0e8         # volumen medio diario (moneda)
    tax_rate: float = 0.19           # impuesto sobre ganancia neta positiva
    latency_bars: int = 1            # retardo de ejecución (nº de barras)
    max_participation: float = 0.05  # fracción máx del volumen del bar

    def scaled(self, factor: float) -> "InstrumentCosts":
        """Escenario de estrés multiplicando los costes por `factor`."""
        return InstrumentCosts(
            commission_bps=self.commission_bps * factor,
            half_spread_bps=self.half_spread_bps * factor,
            slippage_coef=self.slippage_coef * factor,
            impact_coef=self.impact_coef * factor,
            adv_value=self.adv_value,
            tax_rate=self.tax_rate,
            latency_bars=self.latency_bars,
            max_participation=self.max_participation,
        )


@dataclass
class TradeCost:
    commission: float
    spread: float
    slippage: float
    impact: float
    total: float
    executed_notional: float
    unfilled_notional: float


def cost_of_trade(
    ic: InstrumentCosts,
    trade_notional: float,
    sigma_bar: float,
    bar_volume_value: float,
) -> TradeCost:
    """Coste (en moneda) de intentar mover `trade_notional`.

    sigma_bar es la volatilidad del bar en fracción (p.ej. 0,015 = 1,5%).
    Aplica primero el tope de participación (fill parcial).
    """
    q = abs(float(trade_notional))
    if bar_volume_value and bar_volume_value > 0:
        cap = ic.max_participation * bar_volume_value
        executed = min(q, cap)
    else:
        executed = q
    unfilled = q - executed
    commission = ic.commission_bps / 1e4 * executed
    spread = ic.half_spread_bps / 1e4 * executed
    slippage = ic.slippage_coef * max(sigma_bar, 0.0) * executed
    if ic.adv_value and ic.adv_value > 0 and executed > 0:
        participation = executed / ic.adv_value
        impact = ic.impact_coef * max(sigma_bar, 0.0) * np.sqrt(participation) * executed
    else:
        impact = 0.0
    total = commission + spread + slippage + impact
    return TradeCost(
        commission=commission,
        spread=spread,
        slippage=slippage,
        impact=impact,
        total=float(total),
        executed_notional=float(executed),
        unfilled_notional=float(unfilled),
    )


def apply_annual_taxes(returns, dates, tax_rate: float):
    """Impuesto a la ganancia neta positiva por año natural (aproximación).

    Recibe una serie de retornos simples diarios y devuelve otra en la que, el
    último día de cada año con crecimiento > 1, se inyecta un retorno negativo
    equivalente a tax_rate · (crecimiento_anual - 1). Conservador: grava el bruto
    anual sin compensar pérdidas entre años.
    """
    import pandas as pd

    r = pd.Series(np.asarray(returns, dtype=float), index=pd.DatetimeIndex(dates)).fillna(0.0)
    out = r.copy()
    for _, seg in r.groupby(r.index.year):
        growth = float(np.prod(1.0 + seg.to_numpy()))
        if growth > 1.0:
            tax_drag = tax_rate * (growth - 1.0)  # fracción del capital de inicio de año
            # convertir el impuesto a un retorno del último día del año
            last_idx = seg.index[-1]
            out.loc[last_idx] = (1.0 + out.loc[last_idx]) * (1.0 - tax_drag / growth) - 1.0
    return out
