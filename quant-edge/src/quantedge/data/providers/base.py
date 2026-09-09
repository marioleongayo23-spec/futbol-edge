"""Cliente HTTP base para proveedores de datos + caché + normalización.

Diseño *cache-first*: toda respuesta cruda se guarda en disco
(`data_cache/<vendor>/...`) y en ejecuciones posteriores se lee de ahí. Esto da
reproducibilidad y permite trabajar **sin red** una vez descargados los datos.

En ESTE entorno los hosts de datos están bloqueados por política (403 en el
CONNECT del proxy). Por eso cada proveedor expone `check_connectivity()` que
informa con claridad del bloqueo en lugar de fallar en silencio. El código de
red es real y funciona en un entorno con acceso/credenciales.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_CACHE = Path(os.environ.get("QUANTEDGE_CACHE", "quant-edge/data_cache"))
LN2 = np.log(2.0)


class ProviderError(RuntimeError):
    pass


class ProviderBlocked(ProviderError):
    """La red denegó el acceso al host (p. ej. 403 de la política de egress)."""


@dataclass
class HttpClient:
    cache_dir: Path = DEFAULT_CACHE
    timeout: float = 20.0
    max_retries: int = 3
    user_agent: str = "quant-edge/0.1 (research)"
    _ctx: ssl.SSLContext = field(init=False, repr=False)

    def __post_init__(self):
        self.cache_dir = Path(self.cache_dir)
        self._ctx = ssl.create_default_context()
        ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"
        try:
            if ca and Path(ca).exists():
                self._ctx.load_verify_locations(ca)
        except Exception:
            pass  # se queda con el trust por defecto del sistema

    def _opener(self):
        handlers = [urllib.request.HTTPSHandler(context=self._ctx)]
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
        return urllib.request.build_opener(*handlers)

    def get_json(self, url: str, cache_key: str | None = None, force: bool = False) -> Any:
        """GET JSON con caché en disco. Si hay caché y no `force`, no toca la red."""
        cache_path = None
        if cache_key:
            cache_path = self.cache_dir / f"{cache_key}.json"
            if cache_path.exists() and not force:
                return json.loads(cache_path.read_text(encoding="utf-8"))
        opener = self._opener()
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with opener.open(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except urllib.error.HTTPError as e:  # respuesta HTTP con código
                if e.code in (401, 403, 407):
                    raise ProviderBlocked(f"{url} -> HTTP {e.code} (denegado/credenciales)") from e
                last = e
            except urllib.error.URLError as e:  # túnel/DNS/TLS; incluye 403 del CONNECT
                reason = str(getattr(e, "reason", e))
                if "403" in reason or "407" in reason or "tunnel" in reason.lower():
                    raise ProviderBlocked(f"{url} -> bloqueado por proxy ({reason})") from e
                last = e
            time.sleep(2 ** attempt)
        raise ProviderError(f"Fallo al obtener {url}: {last}")

    def check_connectivity(self, ping_url: str) -> tuple[bool, str]:
        try:
            self.get_json(ping_url, cache_key=None, force=True)
            return True, "OK"
        except ProviderBlocked as e:
            return False, f"BLOQUEADO: {e}"
        except Exception as e:  # noqa: BLE001
            return False, f"ERROR: {e}"


# --- utilidades de normalización de barras ---

def parkinson_sigma(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Volatilidad por barra (estimador de Parkinson) a partir de high/low."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        val = np.sqrt(np.square(np.log(high / low)) / (4.0 * LN2))
    return np.nan_to_num(val, nan=0.0, posinf=0.0, neginf=0.0)


def bars_from_ohlcv(
    ts, open_, high, low, close, volume_value, est_spread_bps: float
) -> pd.DataFrame:
    """Construye el DataFrame de barras estándar desde OHLCV.

    bid/ask se ESTIMAN a partir de `est_spread_bps` cuando la fuente no da L1
    real (klines/aggregates). Para bid/ask reales, usar el endpoint de quotes del
    proveedor (Polygon /v3/quotes, Binance @bookTicker). Queda documentado.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).tz_convert(None)
    mid = np.asarray(close, float)
    sigma = parkinson_sigma(high, low)
    spread_bps = np.full(len(mid), float(est_spread_bps))
    half = mid * (spread_bps / 1e4) / 2.0
    df = pd.DataFrame(
        {
            "mid": mid,
            "bid": mid - half,
            "ask": mid + half,
            "volume_value": np.asarray(volume_value, float),
            "sigma_bar": sigma,
            "spread_bps": spread_bps,
        },
        index=idx,
    ).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs["bidask_estimated"] = True
    return df
