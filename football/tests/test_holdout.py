"""Backtest 80/20 (hold-out): entrena con el 80% y valida en el 20% real."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.backtest.holdout import chronological_split, holdout_report


def _matches(rounds: int = 40, noise: float = 0.0) -> list[MatchStats]:
    """Liga sintética con fuerza y disciplina latentes por equipo, determinista.

    Sin ruido: el modelo por equipo DEBE batir a la media de liga (skill > 0).
    """
    teams = [f"Team{i}" for i in range(8)]
    strength = {t: 0.5 + i for i, t in enumerate(teams)}   # goles/remates
    discipline = {t: 1 + (i % 4) for i, t in enumerate(teams)}  # faltas/tarjetas
    start = datetime(2024, 8, 15, tzinfo=timezone.utc)
    out: list[MatchStats] = []
    d = 0
    for rnd in range(rounds):
        rot = teams[rnd % 8:] + teams[:rnd % 8]
        for k in range(0, 8, 2):
            h, a = rot[k], rot[k + 1]
            d += 3
            hg = round(strength[h] * 0.5)
            ag = round(strength[a] * 0.4)
            hs = round(6 + strength[h] * 2)
            as_ = round(5 + strength[a] * 2)
            out.append(MatchStats(h, a, {
                "goals": (hg, ag),
                "shots": (hs, as_),
                "sot": (round(hs * 0.4), round(as_ * 0.4)),
                "corners": (5, 4),
                "fouls": (10 * discipline[h], 10 * discipline[a]),
                "yellows": (discipline[h], discipline[a]),
            }, kickoff=start + timedelta(days=d)))
    return out


def test_split_es_cronologico_80_20():
    ms = _matches()
    train, test = chronological_split(ms, train_frac=0.8)
    assert len(train) + len(test) == len(ms)
    assert abs(len(train) / len(ms) - 0.8) < 0.02
    # El train es ANTERIOR al test: sin fuga temporal.
    assert train[-1].kickoff <= test[0].kickoff


def test_holdout_estructura_y_skill():
    rep = holdout_report(_matches(rounds=50))
    assert rep["train_n"] > rep["test_n"] > 0
    assert "24/25" in rep["seasons"]
    # El corte no solapa.
    assert rep["train_end"] <= rep["test_start"]

    stats = rep["stats"]
    for s in ("goals", "shots", "fouls", "yellows"):
        assert s in stats
        assert stats[s]["mae"] >= 0
        assert stats[s]["baseline_mae"] is not None
    # Con fuerza latente clara, el modelo por equipo bate a la media de liga.
    assert stats["fouls"]["skill_pct"] > 0
    assert stats["goals"]["skill_pct"] > 0

    out = rep["outcome"]
    assert out["n"] == rep["test_n"]
    assert 0.0 <= out["accuracy"] <= 1.0
    assert out["rps"] >= 0 and out["baseline_rps"] >= 0


def test_comparacion_elige_mejor_algoritmo_por_estadistica():
    rep = holdout_report(_matches(rounds=50))
    comp = rep["comparison"]
    for stat, c in comp.items():
        algos = c["algorithms"]
        # Están los candidatos y el ganador es el de menor MAE (verdad de campo).
        assert set(algos) <= {"liga", "equipo", "ataque_defensa", "regresion"}
        assert c["best"] in algos
        assert algos[c["best"]] == min(algos.values())
        # La regresión expone qué variable influye en la predicción.
        assert set(c["influence"]) == {"ataque_propio", "defensa_rival", "media_liga", "intercepto"}
    # Con fuerza latente por equipo, algún método por equipo bate a la media de liga.
    fouls = comp["fouls"]["algorithms"]
    assert min(fouls["equipo"], fouls["ataque_defensa"], fouls["regresion"]) < fouls["liga"]


def test_muestra_insuficiente_devuelve_none():
    assert holdout_report(_matches(rounds=2)) is None
    assert holdout_report([]) is None
