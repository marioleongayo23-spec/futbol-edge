"""P3.4: una sola autoridad de producción para el método estadístico.

El banco 80/20 legacy sigue comparando algoritmos y mostrando qué método habría
funcionado mejor, pero ya no puede mutar producción. La promoción real vive en
``StatsPredictor.validate_regression_champions``. El override manual de
``fixture_payload`` se conserva únicamente por compatibilidad.
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
    """Alpha comete SIEMPRE ~10 faltas; su media propia gana analíticamente."""
    teams = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    goals = {t: 0.6 + 0.5 * i for i, t in enumerate(teams)}
    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    out = []
    d = 0
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


def test_holdout_detecta_equipo_pero_no_lo_promociona_a_produccion():
    rep = holdout_report(_matches())
    alpha = rep["by_team"][_canon("Alpha")]["stats"]["fouls"]

    # El banco sigue diciendo la verdad analítica.
    assert alpha["best"] == "equipo"
    assert alpha["analytic_gain"] is not None and alpha["analytic_gain"] >= 10

    # P3.4: el banco legacy ya no tiene autoridad de producción.
    assert alpha["adopt"] == "ataque_defensa"
    assert alpha["adopt_gain"] is None
    assert alpha["production_selector"] == "StatsPredictor.validate_regression_champions"

    # Por tanto el antiguo mapa de overrides queda vacío.
    smap = _build_stats_method({"LaLiga": {**rep, "label": "LaLiga"}})
    assert smap == {}


def test_holdout_no_puede_crear_overrides_para_ninguna_estadistica():
    rep = holdout_report(_matches())
    smap = _build_stats_method({"LaLiga": {**rep, "label": "LaLiga"}})
    assert smap == {}
    for info in rep["by_team"].values():
        for stat in (info.get("stats") or {}).values():
            assert stat["adopt"] == "ataque_defensa"


def test_fixture_payload_mantiene_override_manual_solo_por_compatibilidad():
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

    assert over["stats"]["fouls"]["home"] == round(
        stats.home.get(_canon("Alpha")).get("fouls").for_avg, 2
    )
    assert over["stats_method"]["fouls"]["home"] == "equipo"
    assert "stats_method" not in base
