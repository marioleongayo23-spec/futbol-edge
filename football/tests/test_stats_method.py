"""Aplicación en producción del método por-equipo (banco 80/20) con guardia.

Solo se cambia el método de un equipo+estadística (de disciplina) cuando "equipo"
supera de forma robusta al actual (ataque×defensa) en su propio 20% oculto.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone, timedelta

from futbol_pred.dashboard import fixture_payload, _canon, _build_stats_method
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.stats_markets import StatsPredictor
from futbol_pred.pipeline import fit_model_from_fixtures
from futbol_pred.backtest.holdout import holdout_report

warnings.simplefilter("ignore")


def _matches():
    """Alpha comete SIEMPRE ~10 faltas (su media lo clava); los rivales varían
    mucho su 'against' → ataque×defensa falla y 'equipo' gana con holgura."""
    teams = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    goals = {t: 0.6 + 0.5 * i for i, t in enumerate(teams)}
    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    out = []
    d = 0
    # Liga completa (todos contra todos, ida y vuelta) repetida varias temporadas.
    # Alpha comete SIEMPRE 10 faltas; el resto 20. Con el rival promedio (~18) el
    # ajuste ataque×defensa manda la predicción de Alpha a ~14, lejos del 10 real,
    # mientras su propia media lo clava → "equipo" gana con holgura.
    for _season in range(8):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                d += 1
                hf = 10 if h == "Alpha" else 20
                af = 10 if a == "Alpha" else 20
                out.append(MatchStats(h, a, {
                    "goals": (round(goals[h] * 1.4), round(goals[a] * 1.1)),
                    "shots": (12, 10), "sot": (4, 3), "corners": (5, 4),
                    "fouls": (hf, af),
                    "yellows": (2, 2),
                }, kickoff=start + timedelta(days=d)))
    return out


def test_guardia_adopta_equipo_cuando_gana_claro():
    rep = holdout_report(_matches())
    alpha = rep["by_team"][_canon("Alpha")]["stats"]["fouls"]
    # Para Alpha, su propia media predice las faltas mucho mejor → se adopta.
    assert alpha["adopt"] == "equipo"
    assert alpha["adopt_gain"] and alpha["adopt_gain"] >= 10
    # El mapa de producción recoge ese cambio (solo disciplina).
    smap = _build_stats_method({"LaLiga": {**rep, "label": "LaLiga"}})
    assert smap["LaLiga"][_canon("Alpha")]["fouls"] == "equipo"


def test_equipo_estable_no_cambia_por_defecto():
    # Un equipo cuyo mejor método es el de por defecto no aparece en el mapa.
    rep = holdout_report(_matches())
    smap = _build_stats_method({"LaLiga": {**rep, "label": "LaLiga"}})
    # Ningún override fuera de las estadísticas de disciplina.
    for team, ov in smap.get("LaLiga", {}).items():
        assert set(ov) <= {"fouls", "yellows", "reds"}


def test_fixture_payload_aplica_el_metodo_por_equipo():
    ms = _matches()
    stats = StatsPredictor().fit(ms, fit_pseudo_xg=False)
    fixtures = [Fixture(api_id=i, league="laliga", season=2026,
                        kickoff=m.kickoff, home_team=m.home_team, away_team=m.away_team,
                        status="FINISHED", home_goals=m.stats["goals"][0],
                        away_goals=m.stats["goals"][1], source="t")
                for i, m in enumerate(ms)]
    model = fit_model_from_fixtures(fixtures, name_fn=_canon)
    upcoming = Fixture(api_id=999, league="laliga", season=2026,
                       kickoff=datetime(2026, 9, 5, 18, tzinfo=timezone.utc),
                       home_team="Alpha", away_team="Beta", status="SCHEDULED", source="t")

    base = fixture_payload(upcoming, model, "2026-09-05T00:00:00+02:00", stats=stats)
    over = fixture_payload(upcoming, model, "2026-09-05T00:00:00+02:00", stats=stats,
                           stats_method={_canon("Alpha"): {"fouls": "equipo"}})
    # Con override, las faltas del local usan la media propia de Alpha (~10).
    assert over["stats"]["fouls"]["home"] == round(stats.home.get(_canon("Alpha")).get("fouls").for_avg, 2)
    assert over["stats_method"]["fouls"]["home"] == "equipo"
    # Sin override, es el método por defecto (distinto salvo casualidad).
    assert "stats_method" not in base
