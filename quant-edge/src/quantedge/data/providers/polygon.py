"""Proveedor Polygon.io (acciones, ETF, FX, cripto). Requiere POLYGON_API_KEY.

Aggregates: /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}
Cada resultado: {o,h,l,c,v,vw,t}. `vw` = VWAP -> volume_value = v*vw.
Para bid/ask reales (NBBO) existe /v3/quotes; aquí se estiman salvo que se
extienda. Símbolos: acciones 'AAPL'; FX 'C:EURUSD'; cripto 'X:BTCUSD'.
"""
from __future__ import annotations

import os

import pandas as pd

from .base import HttpClient, ProviderError, bars_from_ohlcv

BASE = "https://api.polygon.io"
_TIMESPAN = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"),
             "1h": (1, "hour"), "1d": (1, "day")}


class PolygonProvider:
    name = "polygon"
    asset_classes = ("equity", "etf", "fx", "crypto")

    def __init__(self, client: HttpClient | None = None, api_key: str | None = None,
                 est_spread_bps: float = 2.0):
        self.client = client or HttpClient()
        self.api_key = api_key or os.environ.get("POLYGON_API_KEY")
        self.est_spread_bps = est_spread_bps

    def check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Falta POLYGON_API_KEY"
        return self.client.check_connectivity(f"{BASE}/v1/marketstatus/now?apiKey={self.api_key}")

    def get_bars(self, ticker: str, interval: str = "1d", start: str = "2018-01-01",
                 end: str | None = None, max_bars: int = 50000) -> pd.DataFrame:
        if not self.api_key:
            raise ProviderError("Falta POLYGON_API_KEY")
        mult, span = _TIMESPAN[interval]
        end = end or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
        url = (f"{BASE}/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{start}/{end}"
               f"?adjusted=true&sort=asc&limit=50000&apiKey={self.api_key}")
        results: list[dict] = []
        page = 0
        while url and len(results) < max_bars:
            key = f"polygon/{ticker}/{interval}/{start}_{end}_p{page}"
            payload = self.client.get_json(url, cache_key=key)
            results.extend(payload.get("results", []))
            nxt = payload.get("next_url")
            url = f"{nxt}&apiKey={self.api_key}" if nxt else None
            page += 1
        results = results[:max_bars]
        if not results:
            return pd.DataFrame()
        ts = [r["t"] for r in results]
        o = [r["o"] for r in results]
        h = [r["h"] for r in results]
        low = [r["l"] for r in results]
        c = [r["c"] for r in results]
        vv = [r.get("v", 0.0) * r.get("vw", r["c"]) for r in results]
        return bars_from_ohlcv(ts, o, h, low, c, vv, self.est_spread_bps)
