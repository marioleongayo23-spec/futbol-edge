"""Interfaz común de estrategias. Fase 1: SOLO largo/plano, sin apalancamiento.

Una estrategia produce un peso objetivo en [0, 1] por barra, calculado usando
EXCLUSIVAMENTE información disponible hasta esa barra (backward-looking). El
retardo de ejecución (latencia) lo aplica el motor de backtest, no la señal.
"""
from __future__ import annotations

from typing import Iterator

import pandas as pd


class Strategy:
    name = "base"

    def __init__(self, **params):
        self.params = params

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """Peso objetivo en [0,1] por barra (info hasta t, sin look-ahead)."""
        raise NotImplementedError

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        """Rejilla de hiperparámetros para la selección anidada."""
        yield {}

    def __repr__(self) -> str:
        return f"{self.name}({self.params})"

    def key(self) -> str:
        parts = ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.name}[{parts}]"
