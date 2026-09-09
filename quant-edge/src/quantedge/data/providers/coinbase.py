"""Proveedor Coinbase (cripto, sin clave). Fuente B para el par dual cripto.

Candles públicos: https://api.exchange.coinbase.com/products/<PID>/candles
granularity en segundos; máx 300 velas por petición. Cada vela:
[time, low, high, open, close, volume] (volume en moneda base).
"""
from __future__ import annotations

import pandas as pd

from .base import HttpClient, bars_from_ohlcv

BASE = "https://api.exchange.coinbase.com"
_GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


class CoinbaseProvider:
    name = "coinbase"
    asset_classes = ("crypto",)

    def __init__(self, client: HttpClient | None = None, est_spread_bps: float = 2.5):
        self.client = client or HttpClient()
        self.est_spread_bps = est_spread_bps

    def check(self) -> tuple[bool, str]:
        return self.client.check_connectivity(f"{BASE}/products/BTC-USD/ticker")

    def get_bars(self, product_id: str, interval: str = "1d", start: str | None = None,
                 end: str | None = None, max_bars: int = 5000) -> pd.DataFrame:
        gran = _GRAN[interval]
        start_ts = pd.Timestamp(start or "2018-01-01", tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.utcnow()
        rows: list[list] = []
        window = gran * 300
        cursor = start_ts
        while cursor < end_ts and len(rows) < max_bars:
            w_end = min(cursor + pd.Timedelta(seconds=window), end_ts)
            url = (f"{BASE}/products/{product_id}/candles?granularity={gran}"
                   f"&start={cursor.isoformat()}&end={w_end.isoformat()}")
            key = f"coinbase/{product_id}/{interval}/{int(cursor.timestamp())}"
            batch = self.client.get_json(url, cache_key=key)
            if batch:
                rows.extend(batch)
            cursor = w_end
        if not rows:
            return pd.DataFrame()
        rows = sorted(rows, key=lambda r: r[0])[:max_bars]
        ts = [int(r[0]) * 1000 for r in rows]     # segundos -> ms
        low = [float(r[1]) for r in rows]
        h = [float(r[2]) for r in rows]
        o = [float(r[3]) for r in rows]
        c = [float(r[4]) for r in rows]
        vv = [float(r[5]) * float(r[4]) for r in rows]  # base vol * close = valor
        return bars_from_ohlcv(ts, o, h, low, c, vv, self.est_spread_bps)
