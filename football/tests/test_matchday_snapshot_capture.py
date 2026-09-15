from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import futbol_pred.prediction_snapshots as snapshots
from futbol_pred.matchday_snapshot_capture import refresh_payload

MADRID = ZoneInfo("Europe/Madrid")


def _payload():
    return {
        "matches": [{
            "id": "m-live",
            "league": "LaLiga",
            "date": "2026-09-08",
            "kickoff": "2026-09-08T21:00:00+02:00",
            "home": "Barcelona",
            "away": "Valencia",
            "finished": False,
            "probs": [61, 23, 16],
            "model_probs": [60.5, 23.5, 16.0],
            "stats": {
                "fouls": {"home": 12.0, "away": 14.0, "total": 26.0},
                "yellows": {"home": 2.5, "away": 3.0, "total": 5.5},
            },
            "weather": {"temperature_c": 28},
            "alineacion": {"status": "probable", "local": ["L"] * 11, "visitante": ["V"] * 11},
            "model_meta": {"version": "edge-test"},
        }]
    }


def test_captura_desde_lkg_copia_solo_metadata_y_no_pisa_serving(monkeypatch):
    marker = {
        "schema": "stat-shadow-v1",
        "stats": {
            "fouls": {
                "published": {"home": 12, "away": 14, "total": 26},
                "bias_shrunk_v1": {"home": 11.5, "away": 14.2, "total": 25.7},
            }
        },
        "affects_production": False,
        "affects_1x2": False,
        "automatic_production_promotion": False,
    }
    monkeypatch.setattr(snapshots, "build_stat_shadow", lambda match: marker)

    payload = _payload()
    previous = deepcopy(payload)
    serving_before = deepcopy(payload["matches"][0])
    changed, audit = refresh_payload(
        payload,
        previous,
        now=datetime(2026, 9, 7, 21, 0, tzinfo=MADRID),
    )

    assert changed is True
    match = payload["matches"][0]
    assert match["prediction_snapshot"]["window"] == "T-24h"
    assert match["prediction_snapshot"]["stat_challengers"] == marker
    assert match["prediction_history"][-1]["stat_challengers"] == marker

    # Solo se añaden los dos campos auditables; serving permanece byte-a-byte igual.
    for key, value in serving_before.items():
        assert match[key] == value
    assert audit["serving_fields_changed"] == 0
    assert audit["snapshots_changed"] == 1
    assert audit["histories_changed"] == 1
    assert audit["affects_1x2"] is False


def test_fuera_de_hito_no_fabrica_revision_nueva(monkeypatch):
    monkeypatch.setattr(snapshots, "build_stat_shadow", lambda match: {"schema": "stat-shadow-v1"})
    initial = _payload()
    previous = deepcopy(initial)
    refresh_payload(
        initial,
        previous,
        now=datetime(2026, 9, 7, 21, 0, tzinfo=MADRID),
    )

    current = deepcopy(initial)
    changed, audit = refresh_payload(
        current,
        initial,
        now=datetime(2026, 9, 7, 22, 0, tzinfo=MADRID),
    )
    assert changed is False
    assert audit["snapshots_changed"] == 0
    assert audit["histories_changed"] == 0
