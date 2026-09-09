import json

import numpy as np
import pandas as pd

from quantedge.data.loader import validate_bars
from quantedge.data.providers.base import HttpClient, bars_from_ohlcv, parkinson_sigma
from quantedge.data.providers.binance import BinanceProvider
from quantedge.data.providers.csv_provider import CsvProvider


def test_parkinson_positive_and_zero():
    s = parkinson_sigma(np.array([101.0, 100.0]), np.array([99.0, 100.0]))
    assert s[0] > 0
    assert s[1] == 0.0  # high==low -> vol 0


def test_bars_from_ohlcv_valid():
    ts = pd.date_range("2022-01-01", periods=5, freq="D").view("int64") // 10**6
    df = bars_from_ohlcv(ts, [1]*5, [1.1]*5, [0.9]*5, [1.05]*5, [1e6]*5, est_spread_bps=4.0)
    validate_bars(df)
    assert (df["ask"] >= df["bid"]).all()
    assert df.attrs["bidask_estimated"] is True


def test_http_cache_hit_no_network(tmp_path):
    client = HttpClient(cache_dir=tmp_path)
    (tmp_path / "k.json").write_text(json.dumps({"hola": 1}), encoding="utf-8")
    # Con caché presente NO toca la red aunque la URL sea inválida.
    assert client.get_json("https://host.invalido.tld/x", cache_key="k") == {"hola": 1}


def test_csv_provider_roundtrip(tmp_path):
    p = tmp_path / "SYM.csv"
    idx = pd.date_range("2022-01-01", periods=10, freq="D")
    pd.DataFrame({
        "time": idx, "open": np.linspace(100, 110, 10), "high": np.linspace(101, 111, 10),
        "low": np.linspace(99, 109, 10), "close": np.linspace(100, 110, 10),
        "volume": np.full(10, 1e5),
    }).to_csv(p, index=False)
    prov = CsvProvider(tmp_path)
    df = prov.get_bars("SYM")
    validate_bars(df)
    assert len(df) == 10


class _FakeClient:
    def __init__(self, klines):
        self._k = klines
        self.calls = 0

    def get_json(self, url, cache_key=None, force=False):
        self.calls += 1
        return self._k if self.calls == 1 else []


def test_binance_parsing_offline():
    # kline: [openTime,o,h,l,c,vol,closeTime,quoteVol,...]
    base = 1_640_995_200_000
    klines = [[base + i * 86_400_000, "100", "101", "99", "100.5", "10", 0, "1000000", 0, 0, 0, 0]
              for i in range(5)]
    prov = BinanceProvider(client=_FakeClient(klines))
    df = prov.get_bars("BTCUSDT", interval="1d", max_bars=5)
    validate_bars(df)
    assert len(df) == 5
    assert np.isclose(df["volume_value"].iloc[0], 1_000_000.0)
