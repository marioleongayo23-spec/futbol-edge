"""Interfaz de datos y puntos de enchufe para proveedores REALES.

Contrato mínimo de un DataFrame de barras (índice temporal ascendente, sin
duplicados, alineado al calendario de mercado):
    columnas: mid, bid, ask, volume_value, sigma_bar, spread_bps

`RealVendorAdapter` documenta —sin implementarla— la integración de datos
reales. Requisitos del encargo que un adaptador real DEBE cumplir:
  - intradía con bid/ask/volumen y marcas de tiempo con latencia,
  - calendario de mercado y sesiones (festivos, medias sesiones),
  - >= 2 fuentes independientes reconciliadas (dual_source.reconcile),
  - datos NO revisados a posteriori (point-in-time), sin look-ahead ni
    supervivencia (incluir instrumentos deslistados/quebrados).
Mientras no existan, el loader solo sirve datos sintéticos etiquetados.
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

REQUIRED_COLUMNS = ("mid", "bid", "ask", "volume_value", "sigma_bar", "spread_bps")


def validate_bars(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("El índice temporal debe ser ascendente")
    if df.index.has_duplicates:
        raise ValueError("Hay marcas de tiempo duplicadas")
    if (df["ask"] < df["bid"]).any():
        raise ValueError("ask < bid en alguna barra")


class BarSource(Protocol):
    def get(self, symbol: str, start: str, end: str) -> pd.DataFrame: ...


class RealVendorAdapter:
    """Marcador de posición para un proveedor real (NO implementado).

    Implementar `get()` conectando el vendor (p.ej. Polygon, Databento, IQFeed,
    Dukascopy, LOBSTER, exchanges cripto) y devolviendo barras que pasen
    `validate_bars`. Debe ser point-in-time (sin revisiones posteriores).
    """

    name = "REAL_VENDOR_NO_IMPLEMENTADO"

    def get(self, symbol: str, start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError(
            "Adaptador de datos reales no implementado. Este entorno no tiene "
            "acceso a feeds de mercado (política de egress). Ver ESTUDIO.md."
        )
