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


# --------------------------------------------------------------------------
# Registro de proveedores reales + carga dual-source con reconciliación.
# --------------------------------------------------------------------------

def build_default_providers(cache_dir: str = "quant-edge/data_cache", csv_root: str | None = None) -> dict:
    """Instancia los proveedores disponibles. Import perezoso para no exigir red."""
    from .providers.base import HttpClient
    from .providers.binance import BinanceProvider
    from .providers.coinbase import CoinbaseProvider
    from .providers.polygon import PolygonProvider

    client = HttpClient(cache_dir=cache_dir)
    providers: dict = {
        "binance": BinanceProvider(client),
        "coinbase": CoinbaseProvider(client),
        "polygon": PolygonProvider(client),
    }
    if csv_root:
        from .providers.csv_provider import CsvProvider

        providers["csv"] = CsvProvider(csv_root)
    return providers


def providers_status(providers: dict) -> list[dict]:
    """Comprueba conectividad/credenciales de cada proveedor (honesto ante bloqueos)."""
    out = []
    for name, p in providers.items():
        try:
            ok, detail = p.check()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"ERROR: {e}"
        out.append({"provider": name, "ok": bool(ok), "detail": detail})
    return out


# Emparejamiento por defecto de dos fuentes independientes por clase de activo.
DUAL_SOURCE_MAP = {
    "crypto": ("binance", "coinbase"),
    "equity": ("polygon", "csv"),
    "etf": ("polygon", "csv"),
    "fx": ("polygon", "csv"),
    "commodity": ("polygon", "csv"),
}


def load_dual_source(providers: dict, asset_class: str, symbols: dict[str, str],
                     interval: str = "1d", start: str | None = None, end: str | None = None,
                     threshold_bps: float = 20.0):
    """Carga desde DOS proveedores y reconcilia.

    `symbols` mapea nombre_de_proveedor -> símbolo en ese proveedor
    (p. ej. {"binance": "BTCUSDT", "coinbase": "BTC-USD"}). Devuelve
    (df_limpio, informe_reconciliación). Requiere que ambas fuentes respondan.
    """
    from .dual_source import reconcile

    a_name, b_name = DUAL_SOURCE_MAP.get(asset_class, (None, None))
    frames = {}
    for vendor in (a_name, b_name):
        if vendor is None or vendor not in providers or vendor not in symbols:
            continue
        df = providers[vendor].get_bars(symbols[vendor], interval=interval, start=start, end=end)
        if not df.empty:
            validate_bars(df)
            frames[vendor] = df
    if len(frames) < 2:
        raise RuntimeError(
            f"Se necesitan 2 fuentes para {asset_class}; disponibles: {list(frames)}. "
            "En este entorno los proveedores están bloqueados (403)."
        )
    (a_df, b_df) = list(frames.values())[:2]
    idx = a_df.index.intersection(b_df.index)
    return reconcile(a_df.loc[idx], b_df.loc[idx], threshold_bps=threshold_bps)
