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


def test_metrica_de_baja_varianza_aun_discrimina():
    """Faltas apenas varían entre partidos: con umbral fijo (6%) el
    emparejamiento más faltero salía 'flat'. Con el umbral adaptado a la
    dispersión de la métrica, ese cruce marca '↑' aunque su desvío sea pequeño,
    y un cruce medio sigue 'flat'."""
    base = [f"B{i}" for i in range(10)]
    rows = []
    # Liga: casi todos cometen 10 faltas en casa y fuera (baja varianza).
    for h in base:
        for a in base:
            if h != a:
                rows.append(MatchStats(h, a, {"fouls": (10, 10)}))
    # Nervio comete algo más EN CASA; Áspero, algo más FUERA (desvío ~4%).
    for a in base:
        rows.append(MatchStats("Nervio", a, {"fouls": (11, 10)}))
    for h in base:
        rows.append(MatchStats(h, "Aspero", {"fouls": (10, 11)}))
    tm = TrendModel().fit([], rows, _id)
    faltas = tm.trend("Nervio", "Aspero")["fouls"]
    assert faltas["dir"] == "up"
    assert 0 < faltas["pct"] < 6            # habría sido 'flat' con el 6% fijo
    assert tm._threshold("fouls") < 0.06    # umbral adaptado por debajo del fijo
    # Un emparejamiento medio de la liga sigue plano (no marcamos ruido).
    assert tm.trend("B1", "B2")["fouls"]["dir"] == "flat"


def test_fit_no_rompe_con_kickoffs_mezclados_tz():
    """El sembrado multi-temporada mezcla kickoffs con y sin zona horaria. Antes
    `fit` los ordenaba en crudo y lanzaba TypeError, así que `_fit_trends` lo
    tragaba y dejaba el modelo sin construir (tendencias congeladas/planas)."""
    aware = datetime(2026, 8, 1, tzinfo=timezone.utc)
    naive = datetime(2025, 1, 1)  # sembrado de temporada anterior, sin tz
    fixtures = [
        _Fx("A", "B", 3, 0, naive),
        _Fx("B", "A", 1, 1, aware),
        _Fx("A", "C", 2, 0, naive),
        _Fx("C", "B", 0, 2, aware),
    ]
    tm = TrendModel().fit(fixtures, [], _id)          # no debe lanzar
    assert tm.totals                                   # se construyó con datos
    t = tm.trend("A", "B", kickoff=aware)
    assert set(t) == {"goals", "shots", "corners", "fouls", "yellows"}


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
