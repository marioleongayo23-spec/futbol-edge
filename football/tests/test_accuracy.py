"""Agregado de precisión histórica (predicho vs real) del feed."""

from futbol_pred.dashboard import _aggregate_accuracy


def _snapshot(probs, stats=None):
    return {
        "generated_at": "2026-08-23T10:00:00+02:00",
        "probs": probs,
        "stats": stats or {},
    }


def test_aggregate_acierto_y_mae():
    # statsReal en el feed real viene como {home,away,total}.
    matches = [
        {"finished": True, "result": [2, 0], "kickoff": "2026-08-23T21:00:00+02:00",
         "prediction_history": [_snapshot([60, 25, 15], {"corners": {"total": 9}, "shots": {"total": 22}})],
         "statsReal": {"corners": {"home": 6, "away": 4, "total": 10},
                       "shots": {"home": 12, "away": 11, "total": 23}}},
        {"finished": True, "result": [1, 1], "kickoff": "2026-08-23T22:00:00+02:00",
         "prediction_history": [_snapshot([30, 40, 30], {"corners": {"total": 10}})],
         "statsReal": {"corners": {"home": 5, "away": 4, "total": 9}}},
        {"finished": False},  # se ignora
    ]
    agg = _aggregate_accuracy(matches)
    assert agg["n_partidos"] == 2
    assert agg["aciertos_1x2"] == 2 and agg["n_1x2"] == 2 and agg["pct_1x2"] == 100
    corners = next(m for m in agg["metrics"] if m["key"] == "corners")
    assert corners["n"] == 2 and corners["mae"] == 1.0 and corners["sesgo"] == 0.0
    shots = next(m for m in agg["metrics"] if m["key"] == "shots")
    assert shots["mae"] == 1.0 and shots["sesgo"] == 1.0  # real > previsto


def test_aggregate_falla_favorito():
    matches = [
        {"finished": True, "result": [0, 2], "kickoff": "2026-08-23T21:00:00+02:00",
         "prediction_history": [_snapshot([70, 20, 10])]},  # dijo 1, salió 2
    ]
    agg = _aggregate_accuracy(matches)
    assert agg["aciertos_1x2"] == 0 and agg["n_1x2"] == 1 and agg["pct_1x2"] == 0


def test_aggregate_sin_datos():
    assert _aggregate_accuracy([{"finished": False}]) is None


def test_aggregate_no_usa_prediccion_recalculada_sin_snapshot():
    match = {
        "finished": True,
        "result": [3, 0],
        "kickoff": "2026-08-23T21:00:00+02:00",
        "probs": [99, 1, 0],
    }
    assert _aggregate_accuracy([match]) is None


def test_reliability_por_bandas_de_confianza():
    """La curva de fiabilidad agrupa por confianza del favorito y compara la
    probabilidad media dada con el acierto real observado."""
    def mk(res, probs):
        return {"finished": True, "result": res, "kickoff": "2026-08-23T21:00:00+02:00",
                "prediction_history": [_snapshot(probs)]}
    matches = [
        mk([2, 0], [70, 20, 10]),  # muy claro, acierta (1)
        mk([2, 1], [68, 22, 10]),  # muy claro, acierta (1)
        mk([0, 1], [66, 20, 14]),  # muy claro, falla (salió 2)
        mk([1, 0], [58, 25, 17]),  # claro, acierta (1)
        mk([0, 0], [55, 30, 15]),  # claro, falla (salió X)
        mk([1, 1], [48, 30, 22]),  # ajustado, falla (salió X)
    ]
    rel = _aggregate_accuracy(matches)["reliability"]
    assert rel is not None and rel["n"] == 6
    muy = next(b for b in rel["bands"] if b["label"].startswith("Muy claro"))
    assert muy["n"] == 3 and muy["hits"] == 2 and muy["hit_rate"] == 67
    assert muy["avg_pred"] == 68  # media de 70, 68, 66


def test_reliability_none_con_muestra_pequena():
    matches = [
        {"finished": True, "result": [2, 0], "kickoff": "2026-08-23T21:00:00+02:00",
         "prediction_history": [_snapshot([70, 20, 10])]},
    ]
    assert _aggregate_accuracy(matches)["reliability"] is None
