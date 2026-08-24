from datetime import datetime
from zoneinfo import ZoneInfo

from futbol_pred.prediction_snapshots import apply_prediction_snapshots

MADRID = ZoneInfo("Europe/Madrid")


def _match(probs=None):
    return {
        "id": "m1",
        "date": "2026-08-24",
        "kickoff": "2026-08-24T21:00:00+02:00",
        "league": "LaLiga",
        "home": "A",
        "away": "B",
        "finished": False,
        "engine": "ensemble",
        "probs": probs or [50, 30, 20],
        "xg": [1.5, 0.8],
        "markets": {"marcador": "1-0"},
        "model_meta": {"version": "edge-2.0"},
    }


def test_primera_ejecucion_crea_snapshot_inmutable():
    matches = [_match()]
    apply_prediction_snapshots(matches, [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    assert matches[0]["prediction_snapshot"]["window"] == "initial"
    assert matches[0]["prediction_snapshot"]["probs"] == [50, 30, 20]


def test_fuera_de_ventana_conserva_prediccion_anterior():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([80, 10, 10])
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 8, tzinfo=MADRID))
    assert current["probs"] == [50, 30, 20]
    assert len(current["prediction_history"]) == 1


def test_ventana_de_las_diez_crea_revision_del_partido_del_dia():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([55, 27, 18])
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 10, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "10:00"
    assert current["probs"] == [55, 27, 18]
    assert len(current["prediction_history"]) == 2


def test_segundo_cron_de_la_misma_hora_no_reescribe_snapshot():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    ten = _match([55, 27, 18])
    apply_prediction_snapshots([ten], [old], datetime(2026, 8, 24, 10, 0, tzinfo=MADRID))
    repeated = _match([80, 10, 10])
    apply_prediction_snapshots([repeated], [ten], datetime(2026, 8, 24, 10, 15, tzinfo=MADRID))
    assert repeated["probs"] == [55, 27, 18]
    assert len(repeated["prediction_history"]) == 2


def test_partido_terminado_no_captura_resultado_conocido():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([99, 1, 0])
    current.update({"finished": True, "result": [4, 0], "engine": "resultado-real"})
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 23, tzinfo=MADRID))
    assert current["prediction_snapshot"]["probs"] == [50, 30, 20]
    assert current["probs"] == [50, 30, 20]
    assert current["engine"] == "resultado-real"


def test_historico_sin_snapshot_elimina_prediccion_reconstruida():
    current = _match([99, 1, 0])
    current.update({"finished": True, "result": [4, 0], "engine": "resultado-real"})
    apply_prediction_snapshots([current], [], datetime(2026, 8, 24, 23, tzinfo=MADRID))
    assert "probs" not in current
    assert current["prediction_unavailable_reason"] == "sin_snapshot_prepartido"
