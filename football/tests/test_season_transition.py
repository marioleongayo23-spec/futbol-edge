"""Transición temporada anterior -> temporada en curso.

Con 5-6 jornadas jugadas ya hay base propia: el modelo debe migrar del
histórico (sembrado) a la forma reciente. Se cubren las tres palancas acopladas
al progreso de la liga:

  * Dixon-Coles: los partidos de sembrado entran con peso < 1 que decae.
  * Elo: regresión a la media al cruzar cada cambio de temporada.
  * Peso modelo↔mercado: el seed de temporada anterior no congela la mezcla.
"""

from datetime import datetime, timedelta

import pytest

from futbol_pred import dashboard
from futbol_pred.elo import EloRatings
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.model import DixonColesModel
from futbol_pred.pipeline import (
    SEED_WEIGHT_FLOOR,
    _season_progress,
    _seed_weight,
    fit_model_from_fixtures,
)


def _fx(fid, home, away, hg, ag, kickoff, season, league="laliga"):
    return Fixture(
        api_id=fid,
        league=league,
        season=season,
        kickoff=kickoff,
        home_team=home,
        away_team=away,
        status="FT",
        home_goals=hg,
        away_goals=ag,
        source="test",
    )


# --- Bloques puros del progreso de temporada -------------------------------

def test_season_progress_monotono_y_acotado():
    assert _season_progress(0) == 0.0
    assert _season_progress(6) == pytest.approx(0.5, abs=1e-9)
    assert _season_progress(12) == 1.0
    assert _season_progress(40) == 1.0  # nunca pasa de 1


def test_seed_weight_arranca_en_uno_y_cae_al_suelo():
    # Jornada 0: el sembrado manda al 100% (comportamiento histórico intacto).
    assert _seed_weight(0.0) == pytest.approx(1.0)
    # Temporada madura: el sembrado nunca desaparece, se queda en el suelo.
    assert _seed_weight(1.0) == pytest.approx(SEED_WEIGHT_FLOOR)
    # Es estrictamente decreciente en el tramo de transición.
    assert _seed_weight(0.2) > _seed_weight(0.5) > _seed_weight(0.9)


# --- Elo: regresión a la media ---------------------------------------------

def test_regress_to_mean_revierte_hacia_base():
    elo = EloRatings(base=1500.0)
    elo.ratings = {"A": 1900.0, "B": 1100.0}
    elo.regress_to_mean(0.25)
    assert elo.ratings["A"] == pytest.approx(1800.0)  # 1900 - 0.25*400
    assert elo.ratings["B"] == pytest.approx(1200.0)  # 1100 + 0.25*400


def test_regress_to_mean_extremos():
    elo = EloRatings(base=1500.0)
    elo.ratings = {"A": 1900.0}
    elo.regress_to_mean(0.0)          # no-op
    assert elo.ratings["A"] == pytest.approx(1900.0)
    elo.regress_to_mean(1.0)          # reinicio total
    assert elo.ratings["A"] == pytest.approx(1500.0)


def test_fit_elo_regresa_en_cambio_de_temporada():
    # "A" arrasa la temporada anterior; en la nueva aún no ha jugado. Con la
    # regresión su Elo de arranque de la nueva temporada baja respecto a no
    # regresar en absoluto.
    base = datetime(2025, 9, 1)
    prev = [
        _fx(i, "A", "B", 5, 0, base + timedelta(days=i), season=2025)
        for i in range(10)
    ]
    # Un partido de la temporada nueva (dispara el cruce de temporada al ordenar).
    curr = [_fx(100, "C", "D", 1, 1, datetime(2026, 8, 20), season=2026)]

    elo = dashboard._fit_elo_from_fixtures(prev + curr)
    # Referencia sin regresión: mismo Elo continuo.
    ref = EloRatings()
    for f in sorted(prev + curr, key=lambda x: x.kickoff):
        ref.update(f.home_team, f.away_team, f.home_goals, f.away_goals)

    a_reg = elo.get(dashboard._canon("A"))
    a_ref = ref.get(dashboard._canon("A"))
    assert a_reg < a_ref                       # el dominador revierte hacia la media
    assert a_reg > elo.base                     # pero sigue por encima de la base


# --- Dixon-Coles: el sembrado cede a la forma actual -----------------------

def _liga_ronda(teams, scorer, fid_start, kickoff, season):
    """Todos contra todos (ida) con un marcador dictado por ``scorer``."""
    out, fid = [], fid_start
    for i, home in enumerate(teams):
        for j, away in enumerate(teams):
            if i == j:
                continue
            hg, ag = scorer(home, away)
            out.append(_fx(fid, home, away, hg, ag, kickoff, season))
            fid += 1
    return out


def test_forma_actual_desplaza_al_sembrado():
    teams = ["A", "B", "C", "D", "E"]

    # Temporada anterior (sembrado): A es un vendaval, marca 4 y no encaja.
    def prev_scorer(home, away):
        if home == "A":
            return 4, 0
        if away == "A":
            return 0, 3
        return 1, 1
    seed = []
    for r in range(4):  # varias vueltas -> muestra amplia del histórico
        seed += _liga_ronda(teams, prev_scorer, 1000 + r * 100,
                             datetime(2025, 9, 1) + timedelta(days=r * 7), 2025)

    # Temporada actual: A se hunde (0 goles, encaja 3); el resto igual.
    def curr_scorer(home, away):
        if home == "A":
            return 0, 3
        if away == "A":
            return 3, 0
        return 1, 1
    current = _liga_ronda(teams, curr_scorer, 5000,
                          datetime(2026, 9, 1), 2026)

    as_of = datetime(2026, 9, 8)
    # Con muchas jornadas actuales el ataque de A cae frente al ajuste con una
    # sola jornada. La forma reciente empuja la fuerza estimada.
    model_poca = fit_model_from_fixtures(
        seed + current[:5], as_of=as_of, current_season=2026
    )
    model_mucha = fit_model_from_fixtures(
        seed + current, as_of=as_of, current_season=2026
    )
    assert model_mucha.attack["A"] < model_poca.attack["A"]


def test_una_sola_temporada_no_aplica_rebaja():
    # Sin sembrado (todo la misma temporada) el ajuste es idéntico con y sin la
    # ruta de sample_weight: no debe cambiar nada del comportamiento histórico.
    teams = ["A", "B", "C", "D"]
    matches = _liga_ronda(teams, lambda h, a: (2, 1), 1,
                          datetime(2026, 9, 1), 2026)
    as_of = datetime(2026, 9, 8)
    model = fit_model_from_fixtures(matches, as_of=as_of, current_season=2026)
    ref = DixonColesModel()
    # mismo orden que fit_model_from_fixtures
    played = [f for f in matches]
    ref.fit(
        [f.home_team for f in played], [f.away_team for f in played],
        [f.home_goals for f in played], [f.away_goals for f in played],
        days_ago=[max(0.0, (as_of - f.kickoff).total_seconds() / 86400) for f in played],
    )
    for t in teams:
        assert model.attack[t] == pytest.approx(ref.attack[t], abs=1e-6)


# --- Peso modelo↔mercado ----------------------------------------------------

def test_seed_de_mercado_no_congela_la_mezcla():
    seed_cal = {
        "accepted": True,
        "scope": "historical_seed",
        "production": {"model_weight": 0.05, "temperature": 0.9},
    }
    w0, _ = dashboard._model_market_weight(0.0, seed_cal)
    w5, _ = dashboard._model_market_weight(5.0, seed_cal)
    w12, _ = dashboard._model_market_weight(12.0, seed_cal)
    # Jornada 0: ancla en el seed. Luego sube con las jornadas.
    assert w0 == pytest.approx(0.05, abs=1e-6)
    assert w5 > w0
    assert w12 > w5
    assert w12 == pytest.approx(0.9, abs=1e-6)   # temporada madura -> rampa plena


def test_calibracion_de_temporada_actual_se_respeta():
    cur_cal = {
        "accepted": True,
        "scope": "current_season",
        "production": {"model_weight": 0.7, "temperature": 1.1},
    }
    w, temp = dashboard._model_market_weight(5.0, cur_cal)
    assert w == pytest.approx(0.7)    # ganada con datos propios: se usa tal cual
    assert temp == pytest.approx(1.1)


def test_sin_calibracion_usa_la_rampa():
    w0, temp0 = dashboard._model_market_weight(0.0, None)
    w6, _ = dashboard._model_market_weight(6.0, None)
    assert w0 == pytest.approx(0.2)   # suelo de la rampa
    assert temp0 == pytest.approx(1.0)
    assert w6 == pytest.approx(0.5)
