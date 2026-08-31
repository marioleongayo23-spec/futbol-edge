"""Tendencias por estilo local/visitante (histórico multi-temporada)."""

from datetime import datetime, timedelta, timezone

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.trends import TrendModel


class _Fx:
    def __init__(self, home, away, hg, ag, kickoff):
        self.home_team, self.away_team = home, away
        self.home_goals, self.away_goals = hg, ag
        self.kickoff = kickoff


def _id(x):
    return x


def test_estilo_local_dominador_sube_y_reparte():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    # ATLETI genera muchos córners EN CASA (10 a favor, 2 en contra).
    for i in range(6):
        rows.append(MatchStats("Atleti", f"X{i}", {"corners": (10, 2)}))
    # ELCHE concede muchos córners FUERA (rival 9, Elche 2).
    for i in range(6):
        rows.append(MatchStats(f"Y{i}", "Elche", {"corners": (9, 2)}))
    # Muestra "normal" para fijar la referencia propia de cada equipo.
    for i in range(4):
        rows.append(MatchStats(f"Z{i}", "Atleti", {"corners": (5, 4)}))
        rows.append(MatchStats("Elche", f"W{i}", {"corners": (5, 4)}))

    tm = TrendModel().fit([], rows, _id)
    t = tm.trend("Atleti", "Elche", kickoff=base)
    assert "corners" in t
    # Con local dominador y visitante que concede fuera, la señal es al alza
    # y el reparto favorece al local.
    assert t["corners"]["dir"] == "up"
    assert "Atleti" in t["corners"]["reason"]


def test_cruce_ofensivo_sube_vs_media_de_liga():
    """Dos equipos muy goleadores frente a una liga baja: antes salía 'flat'
    (se comparaba con su propia media, alta); ahora sube vs la media de la liga."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fixtures = []
    # A y B: partidos suyos de 4 goles (muy por encima de la media de liga).
    for i in range(6):
        fixtures.append(_Fx("A", f"L{i}", 3, 1, base))   # A marca mucho
        fixtures.append(_Fx(f"M{i}", "B", 1, 3, base))    # B marca mucho fuera
    # Resto de la liga: partidos de pocos goles (1-0) para bajar la media.
    for i in range(10):
        fixtures.append(_Fx(f"P{i}", f"Q{i}", 1, 0, base))
    tm = TrendModel().fit(fixtures, [], _id)
    t = tm.trend("A", "B", kickoff=base)
    assert t["goals"]["dir"] == "up"
    assert t["goals"]["pct"] > 0


def test_siempre_devuelve_las_metricas():
    tm = TrendModel().fit([], [], _id)
    t = tm.trend("X", "Y", kickoff=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert set(t) == {"goals", "shots", "corners", "fouls", "yellows"}
    assert all(v["dir"] == "flat" for v in t.values())


def test_poco_descanso_empuja_tarjetas():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [MatchStats("A", "B", {"yellows": (3, 3)}) for _ in range(5)]
    rows += [MatchStats("B", "A", {"yellows": (3, 3)}) for _ in range(5)]
    tm = TrendModel().fit([], rows, _id)
    tm.last_played["A"] = base
    tm.last_played["B"] = base
    t = tm.trend("A", "B", kickoff=base + timedelta(days=2))
    assert "descanso" in t["yellows"]["reason"]
