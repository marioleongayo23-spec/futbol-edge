"""La CLI trata una competición sin partidos jugados como estado válido."""

import json

import pytest

from futbol_pred import cli


def test_run_sin_partidos_no_falla(monkeypatch, capsys):
    def _raise(**_kwargs):
        raise ValueError("No hay partidos jugados para ajustar el modelo")

    monkeypatch.setattr(cli, "run_pipeline", _raise)
    # No debe propagar: fuera de temporada es un estado válido, no un error.
    cli.main(["run", "--league", "champions"])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "sin_datos"
    assert out["league"] == "champions"


def test_backtest_sin_partidos_no_falla(monkeypatch, capsys):
    def _raise(**_kwargs):
        raise ValueError("No hay partidos jugados para ajustar el modelo")

    monkeypatch.setattr(cli, "run_backtest", _raise)
    cli.main(["backtest", "--league", "champions"])
    assert json.loads(capsys.readouterr().out)["status"] == "sin_datos"


def test_otro_valueerror_si_propaga(monkeypatch):
    def _raise(**_kwargs):
        raise ValueError("error real de datos")

    monkeypatch.setattr(cli, "run_pipeline", _raise)
    with pytest.raises(ValueError, match="error real"):
        cli.main(["run", "--league", "laliga"])
