"""Proveedor Binance (cripto, sin clave). Fuente A para el par dual cripto.

Klines públicos: https://api.binance.com/api/v3/klines
Cada kline: [openTime, open, high, low, close, volume, closeTime,
             quoteAssetVolume, ...]. `quoteAssetVolume` ya está en la divisa de
cotización -> volume_value directo.
"""
from __future__ import annotations

import pandas as pd

from .base import HttpClient, bars_from_ohlcv

BASE = "https://api.binance.com"
_INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}


class BinanceProvider:
    name = "binance"
    asset_classes = ("crypto",)

    def __init__(self, client: HttpClient | None = None, est_spread_bps: float = 2.0):
        self.client = client or HttpClient()
        self.est_spread_bps = est_spread_bps

    def check(self) -> tuple[bool, str]:
        return self.client.check_connectivity(f"{BASE}/api/v3/ping")

    def get_bars(self, symbol: str, interval: str = "1d", start: str | None = None,
                 end: str | None = None, max_bars: int = 5000) -> pd.DataFrame:
        step = _INTERVAL_MS[interval]
        start_ms = int(pd.Timestamp(start or "2018-01-01", tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) if end else None
        rows: list[list] = []
        cursor = start_ms
        while len(rows) < max_bars:
            url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={interval}&startTime={cursor}&limit=1000"
            if end_ms:
                url += f"&endTime={end_ms}"
            key = f"binance/{symbol}/{interval}/{cursor}"
            batch = self.client.get_json(url, cache_key=key)
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1][0] + step
            if len(batch) < 1000 or (end_ms and cursor > end_ms):
                break
        rows = rows[:max_bars]
        if not rows:
            return pd.DataFrame()
        ts = [r[0] for r in rows]
        o = [float(r[1]) for r in rows]
        h = [float(r[2]) for r in rows]
        low = [float(r[3]) for r in rows]
        c = [float(r[4]) for r in rows]
        qv = [float(r[7]) for r in rows]  # quoteAssetVolume
        return bars_from_ohlcv(ts, o, h, low, c, qv, self.est_spread_bps)
