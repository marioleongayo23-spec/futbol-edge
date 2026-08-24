"""Agregado de precisión histórica (predicho vs real) del feed."""

from futbol_pred.dashboard import _aggregate_accuracy


def test_aggregate_acierto_y_mae():
    # statsReal en el feed real viene como {home,away,total}.
    matches = [
        {"finished": True, "result": [2, 0], "probs": [60, 25, 15],
         "stats": {"corners": {"total": 9}, "shots": {"total": 22}},
         "statsReal": {"corners": {"home": 6, "away": 4, "total": 10},
                       "shots": {"home": 12, "away": 11, "total": 23}}},
        {"finished": True, "result": [1, 1], "probs": [30, 40, 30],
         "stats": {"corners": {"total": 10}},
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
        {"finished": True, "result": [0, 2], "probs": [70, 20, 10]},  # dijo 1, salió 2
    ]
    agg = _aggregate_accuracy(matches)
    assert agg["aciertos_1x2"] == 0 and agg["n_1x2"] == 1 and agg["pct_1x2"] == 0


def test_aggregate_sin_datos():
    assert _aggregate_accuracy([{"finished": False}]) is None
