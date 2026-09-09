"""Proveedor CSV: datos offline o aportados por el usuario.

Lee ficheros `<dir>/<symbol>.csv` con, al menos, columnas de tiempo y OHLCV.
Si el CSV ya trae `bid`/`ask` reales, se respetan; si no, se estiman. Sirve para
trabajar sin red y para tests deterministas.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .base import bars_from_ohlcv


class CsvProvider:
    name = "csv"
    asset_classes = ("equity", "etf", "fx", "commodity", "crypto")

    def __init__(self, root: str | Path, est_spread_bps: float = 2.0):
        self.root = Path(root)
        self.est_spread_bps = est_spread_bps

    def check(self) -> tuple[bool, str]:
        return (self.root.exists(), f"root={'existe' if self.root.exists() else 'no existe'}")

    def get_bars(self, symbol: str, interval: str = "1d", **_) -> pd.DataFrame:
        path = self.root / f"{symbol}.csv"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        tcol = cols.get("time") or cols.get("timestamp") or cols.get("date") or df.columns[0]
        ts = df[tcol]
        o = df[cols.get("open", "open")]
        h = df[cols.get("high", "high")]
        low = df[cols.get("low", "low")]
        c = df[cols.get("close", "close")]
        if "volume_value" in cols:
            vv = df[cols["volume_value"]]
        elif "volume" in cols:
            vv = df[cols["volume"]] * c
        else:
            vv = np.full(len(df), np.nan)
        bars = bars_from_ohlcv(ts, o, h, low, c, vv, self.est_spread_bps)
        # Si el CSV traía bid/ask reales, respetarlos.
        if "bid" in cols and "ask" in cols:
            bars = bars.copy()
            bars["bid"] = pd.to_numeric(df[cols["bid"]]).to_numpy()
            bars["ask"] = pd.to_numeric(df[cols["ask"]]).to_numpy()
            bars.attrs["bidask_estimated"] = False
        return bars
