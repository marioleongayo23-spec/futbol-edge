from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.real_market import (
    Quote,
    _asian_ev_prob,
    _extra_value_rows,
    attach_closing_snapshots,
    attach_extended_market_value,
)


class FakeStats:
    def dispersion(self, key):
        return 1.0

    def prob_over(self, mean, line, dispersion=1.0):
        from futbol_pred.model.stats_markets import StatsPredictor
        return StatsPredictor.prob_over(mean, line, dispersion)


class FakeOdds:
    available = True

    def featured(self, league):
        return [
            Quote("e1", "Real Madrid", "Valencia", "h2h", "A", "Real Madrid", 1.80),
            Quote("e1", "Real Madrid", "Valencia", "h2h", "A", "Draw", 3.60),
            Quote("e1", "Real Madrid", "Valencia", "h2h", "A", "Valencia", 4.80),
            Quote("e1", "Real Madrid", "Valencia", "h2h", "B", "Real Madrid", 1.82),
            Quote("e1", "Real Madrid", "Valencia", "h2h", "B", "Draw", 3.70),
            Quote("e1", "Real Madrid", "Valencia", "h2h", "B", "Valencia", 4.70),
            Quote("e1", "Real Madrid", "Valencia", "totals", "A", "Over", 1.95, 2.5),
            Quote("e1", "Real Madrid", "Valencia", "totals", "A", "Under", 1.90, 2.5),
        ]

    def events(self, league):
        return [{"id": "e1", "home_team": "Real Madrid", "away_team": "Valencia", "commence_time": "2026-08-25T20:00:00+00:00"}]

    def event_odds(self, league, event_id, player_props=False):
        if player_props:
            return [
                Quote(event_id, "Real Madrid", "Valencia", "player_shots", "Book", "Over", 2.20, 2.5, "Kylian Mbappe"),
                Quote(event_id, "Real Madrid", "Valencia", "player_to_receive_card", "Book", "Yes", 4.00, None, "Kylian Mbappe"),
            ]
        return [
            Quote(event_id, "Real Madrid", "Valencia", "btts", "Book", "Yes", 2.05),
            Quote(event_id, "Real Madrid", "Valencia", "alternate_totals_corners", "Book", "Over", 2.00, 9.5),
            Quote(event_id, "Real Madrid", "Valencia", "alternate_totals_cards", "Book", "Over", 1.95, 4.5),
            Quote(event_id, "Real Madrid", "Valencia", "spreads", "Book", "Real Madrid", 1.92, -0.5),
        ]


def _match(now):
    return {
        "id": "m1", "home": "Real Madrid", "away": "Valencia", "league": "LaLiga",
        "kickoff": (now + timedelta(hours=2)).isoformat(), "finished": False,
        "xg": [2.0, 0.9], "markets": {"btts": 0.48},
        "stats": {"corners": {"total": 10.2}, "yellows": {"total": 4.8}},
        "recommendation": {"decision": "eligible"},
        "alineacion": {
            "clave_local": [{"jugador": "Kylian Mbappe", "r": 3.2, "rp": 1.5, "t": 0.18, "source": "API-Football · players"}],
            "clave_visitante": [],
        },
    }


def test_snapshot_t_menos_2h_es_real_y_persistente():
    now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
    match = _match(now)
    assert attach_closing_snapshots([match], now, client=FakeOdds()) == 1
    close = match["closing_odds"]
    assert close["is_real"] is True
    assert close["capture_kind"] == "t_minus_2h"
    assert close["market_source"] == "The Odds API consensus"
    assert close["1x2"]["1"] == pytest.approx(1.81)
    assert close["ou25"]["over"] == 1.95

    rebuilt = _match(now + timedelta(minutes=15))
    rebuilt["kickoff"] = match["kickoff"]
    assert attach_closing_snapshots([rebuilt], now + timedelta(minutes=15), previous_matches=[match], client=FakeOdds()) == 0
    assert rebuilt["closing_odds"] == close


def test_no_snapshot_fuera_de_ventana():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    match = _match(now)
    match["kickoff"] = (now + timedelta(hours=6)).isoformat()
    assert attach_closing_snapshots([match], now, client=FakeOdds()) == 0
    assert "closing_odds" not in match


def test_value_secundario_usa_probabilidad_modelo_y_cuota_real():
    now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
    match = _match(now)
    quotes = FakeOdds().event_odds("LaLiga", "e1", False) + FakeOdds().event_odds("LaLiga", "e1", True)
    rows = _extra_value_rows(match, quotes, FakeStats())
    btts = next(row for row in rows if row["market"] == "btts")
    assert btts["modelProb"] == 0.48
    assert btts["edge"] == pytest.approx(-0.016, abs=0.001)
    corners = next(row for row in rows if row["market"] == "alternate_totals_corners")
    assert corners["line"] == 9.5 and corners["market_source"] == "The Odds API"
    player = next(row for row in rows if row["market"] == "player_shots")
    assert player["player"] == "Kylian Mbappe"
    assert player["modelProb"] > 0


def test_asian_handicap_modela_push_sin_forzar_binario():
    result = _asian_ev_prob([1.5, 1.0], "home", 0.0)
    assert result is not None
    win, push, loss = result
    assert win > 0 and push > 0 and loss > 0
    assert win + push + loss == pytest.approx(1.0)


def test_extended_market_persiste_y_rankea_solo_edge_positivo():
    now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
    match = _match(now)
    result = attach_extended_market_value(
        [match], now, client=FakeOdds(), stats_models={"LaLiga": FakeStats()}, max_event_requests=4
    )
    assert result["refreshed"] == 1
    assert match["extended_market"]["real"] is True
    assert all(row["edge"] > 0.02 for row in result["ranking"])

    rebuilt = _match(now + timedelta(minutes=30))
    rebuilt["kickoff"] = match["kickoff"]
    result2 = attach_extended_market_value(
        [rebuilt], now + timedelta(minutes=30), previous_matches=[match], client=FakeOdds(),
        stats_models={"LaLiga": FakeStats()}, max_event_requests=4,
    )
    assert result2["refreshed"] == 0
    assert rebuilt["extended_market"] == match["extended_market"]
