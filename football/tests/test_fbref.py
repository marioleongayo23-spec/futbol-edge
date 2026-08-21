"""Tests del cliente FBref (sin requerir soccerdata ni red)."""

import pandas as pd
import pytest

from futbol_pred.ingest import fbref
from futbol_pred.ingest.fbref import (
    FBREF_LEAGUES,
    normalize_fbref_teams,
    soccerdata_available,
)


def test_mapeo_de_ligas():
    assert FBREF_LEAGUES["laliga"] == "ESP-La Liga"
    assert FBREF_LEAGUES["champions"] == "INT-Champions League"
    assert set(FBREF_LEAGUES) == {"laliga", "segunda", "champions"}


def test_available_devuelve_bool():
    assert isinstance(soccerdata_available(), bool)


def test_cliente_sin_soccerdata_da_error_claro(monkeypatch):
    # Forzamos "no instalado" y comprobamos el mensaje de ayuda.
    monkeypatch.setattr(fbref, "soccerdata_available", lambda: False)
    with pytest.raises(RuntimeError, match="soccerdata"):
        fbref.FBrefClient()


def test_normaliza_equipos_desde_columna():
    df = pd.DataFrame({
        "team": ["Barcelona", "Real Madrid", "Athletic Club"],
        "xG": [2.1, 1.9, 1.3],
    })
    out = normalize_fbref_teams(df)
    assert list(out["team_canonical"]) == ["Barcelona", "Real Madrid", "Ath Bilbao"]


def test_normaliza_equipos_desde_indice():
    df = pd.DataFrame({"xG": [2.1, 1.9]}, index=["Barcelona", "Valencia"])
    df.index.name = "team"
    out = normalize_fbref_teams(df)
    assert list(out["team_canonical"]) == ["Barcelona", "Valencia"]


def test_normaliza_sin_equipo_no_rompe():
    df = pd.DataFrame({"xG": [1.0, 2.0]})
    out = normalize_fbref_teams(df)
    assert "team_canonical" not in out.columns  # se devuelve tal cual
