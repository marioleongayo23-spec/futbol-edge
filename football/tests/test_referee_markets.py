"""Cuando el árbitro asignado mueve las tarjetas/faltas, el mercado de esa
estadística (P encima/debajo/exacto) se recalcula con la línea del árbitro."""

from futbol_pred.operational import _recompute_referee_markets
from futbol_pred.model.market_lines import count_market


class _FakeModel:
    def dispersion(self, stat):
        return 1.3


def test_recompute_referee_markets_actualiza_tarjetas():
    base = count_market("yellows", 4.4, 1.3, mean_home=2.2, mean_away=2.2)
    match = {
        "markets_detail": [count_market("goals", 2.5, 1.0), base],
        # El árbitro estricto ya subió las tarjetas a 5.5 en match["stats"].
        "stats": {"yellows": {"home": 2.75, "away": 2.75, "total": 5.5}},
        "tendencias": {"yellows": {"dir": "up", "pct": 10, "reason": "árbitro estricto"}},
    }
    _recompute_referee_markets(match, _FakeModel(), ["yellows"])
    row = next(r for r in match["markets_detail"] if r["stat"] == "yellows")
    assert row["referee_moved"] is True
    assert row["expected"]["total"] == 5.5           # línea del árbitro
    assert row["main_line"] >= base["main_line"] + 0.5  # se desplaza hacia arriba
    # El mercado de goles (no arbitral) queda intacto.
    goals = next(r for r in match["markets_detail"] if r["stat"] == "goals")
    assert "referee_moved" not in goals


def test_recompute_no_hace_nada_sin_modelo_o_sin_markets():
    match = {"stats": {"yellows": {"home": 2, "away": 2, "total": 4}}}
    _recompute_referee_markets(match, None, ["yellows"])  # sin markets_detail
    assert "markets_detail" not in match
