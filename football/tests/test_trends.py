"""Tendencias ↑/↓ de las estadísticas esperadas."""

from datetime import datetime, timedelta, timezone

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.trends import TrendModel


class _Fx:
    def __init__(self, home, away, hg, ag, kickoff):
        self.home_team, self.away_team = home, away
        self.home_goals, self.away_goals = hg, ag
        self.kickoff = kickoff


def _id(x):  # canon identidad
    return x


def test_tendencia_al_alza_en_goles():
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    # A empieza flojo en goles y termina goleando: forma reciente > media -> ↑.
    fixtures = []
    for i, tot in enumerate([0, 1, 1, 4, 5, 5]):
        fixtures.append(_Fx("A", "Rival%d" % i, tot, 0, base + timedelta(days=7 * i)))
    tm = TrendModel().fit(fixtures, [], _id)
    t = tm.trend("A", "A", kickoff=base + timedelta(days=60))
    assert t["goals"]["dir"] == "up"
    assert t["goals"]["pct"] > 0


def test_poco_descanso_sube_tarjetas():
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [MatchStats("A", "B", {"yellows": (3, 3)}) for _ in range(5)]
    fixtures = [_Fx("A", "B", 1, 1, base + timedelta(days=3))]
    tm = TrendModel().fit(fixtures, rows, _id)
    # Fija el último partido y pide uno 2 días después (poco descanso).
    tm.last_played["A"] = base + timedelta(days=3)
    tm.last_played["B"] = base + timedelta(days=3)
    t = tm.trend("A", "B", kickoff=base + timedelta(days=5))
    assert "yellows" in t
    assert "descanso" in t["yellows"]["reason"]


def test_sin_datos_no_tendencia():
    tm = TrendModel().fit([], [], _id)
    assert tm.trend("X", "Y", kickoff=datetime(2026, 8, 1, tzinfo=timezone.utc)) == {}
