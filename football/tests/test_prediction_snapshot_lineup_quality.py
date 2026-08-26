from datetime import datetime
from zoneinfo import ZoneInfo

from futbol_pred.prediction_snapshots import apply_prediction_snapshots


MADRID = ZoneInfo("Europe/Madrid")


def _match(probs):
    return {
        "id": "m1",
        "date": "2026-08-24",
        "kickoff": "2026-08-24T21:00:00+02:00",
        "league": "LaLiga",
        "home": "A",
        "away": "B",
        "finished": False,
        "probs": probs,
        "xg": [1.5, 0.8],
        "model_meta": {"version": "edge-2.0"},
    }


def test_t3_estimado_no_se_promociona_a_prefinal_probable():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))

    current = _match([54, 28, 18])
    current["alineacion"] = {
        "status": "estimado",
        "phase": "pre_final_estimate",
        "source_quality": "model_only",
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
    }
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 18, tzinfo=MADRID))

    assert current["prediction_snapshot"]["window"] == "T-3h"
    assert current["prediction_snapshot"]["alineacion"]["status"] == "estimado"
