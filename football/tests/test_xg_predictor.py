"""Retador Dixon-Coles ajustado sobre goles mezclados con xG."""

import pytest

from futbol_pred.backtest.predictors import (
    DixonColesPredictor,
    XgDixonColesPredictor,
    _match_xg,
)


def test_match_xg_lee_stats_o_top_level():
    assert _match_xg({"stats": {"xg": [1.2, 0.8]}}) == (1.2, 0.8)
    assert _match_xg({"xg": [2.0, 1.0]}) == (2.0, 1.0)
    assert _match_xg({"stats": {"corners": [5, 4]}}) is None
    assert _match_xg({}) is None


def _liga(scorer, xg=None):
    teams = ["A", "B", "C", "D"]
    out, fid = [], 0
    for rnd in range(8):
        for i, home in enumerate(teams):
            for j, away in enumerate(teams):
                if i == j:
                    continue
                fid += 1
                hg, ag = scorer(home, away, rnd)
                m = {"home": home, "away": away, "home_goals": hg, "away_goals": ag,
                     "kickoff": fid, "status": "FINISHED"}
                if xg is not None:
                    m["stats"] = {"xg": list(xg(home, away, rnd))}
                out.append(m)
    return out


def test_xg_corrige_al_sobrerrendidor():
    # "A" marca de más en casa (3-4) pero su xG es ~1 (suerte/definición).
    def goals(home, away, rnd):
        if home == "A":
            return 3 + rnd % 2, rnd % 2
        if away == "A":
            return 1 + rnd % 2, 1
        return 1 + rnd % 2, 1 - rnd % 2

    def xg(home, away, rnd):
        if home == "A":
            return 1.0, 0.9   # xG muy por debajo de sus goles
        return 1.1, 1.0

    matches = _liga(goals, xg)
    goles_model = DixonColesPredictor(min_matches=10).fit(matches).model
    xg_model = XgDixonColesPredictor(min_matches=10).fit(matches).model
    # El modelo xG estima el ataque de A por debajo del modelo de goles puros.
    assert xg_model.attack["A"] < goles_model.attack["A"]


def test_sin_xg_equivale_a_dixon_coles():
    def goals(home, away, rnd):
        return (2, rnd % 2) if home < away else (1, 1 - rnd % 2)

    matches = _liga(goals, xg=None)  # sin xG en ninguna
    xg_pred = XgDixonColesPredictor(min_matches=10).fit(matches)
    dc_pred = DixonColesPredictor(min_matches=10).fit(matches)
    assert xg_pred.xg_coverage == 0
    for team in ("A", "B", "C", "D"):
        assert xg_pred.model.attack[team] == pytest.approx(dc_pred.model.attack[team], abs=1e-6)


def test_predice_1x2_valido():
    matches = _liga(lambda h, a, rnd: (2, rnd % 2), xg=lambda h, a, rnd: (1.6, 0.7 + 0.1 * (rnd % 2)))
    probs = XgDixonColesPredictor(min_matches=10).fit(matches).predict("A", "B")
    assert probs is not None and sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
