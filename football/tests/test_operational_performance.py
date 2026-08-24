from datetime import datetime, timedelta

from futbol_pred.dashboard import MADRID
from futbol_pred.ingest.lineups_ai import build_statistical_lineup
from futbol_pred.operational import attach_official_context, build_alerts, content_audit
from futbol_pred.performance import build_performance


def _squad(prefix):
    return [
        {"name": f"{prefix} {i}", "position": "Goalkeeper" if i == 0 else "Defence" if i < 5 else "Midfield" if i < 8 else "Offence"}
        for i in range(15)
    ]


def test_once_oficial_sustituye_estimado_y_mantiene_props_completas():
    now = datetime(2026, 8, 24, 19, tzinfo=MADRID)
    match = {
        "id": "m1", "home": "Local FC", "away": "Visitante CF",
        "kickoff": (now + timedelta(hours=1)).isoformat(), "xg": [1.4, 1.0],
        "stats": {},
    }
    match["alineacion"] = build_statistical_lineup(match, _squad("L"), _squad("V"))

    class FakeClient:
        offline = False

        def find_fixture(self, *_args):
            return {"fixture": {"id": 42}}

        def get_official_lineup(self, _fixture_id):
            return [
                {"team": "Local FC", "formation": "4-3-3", "starters": [{"name": f"Oficial L {i}", "position": p} for i, p in enumerate(["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"])]},
                {"team": "Visitante CF", "formation": "4-4-2", "starters": [{"name": f"Oficial V {i}", "position": p} for i, p in enumerate(["POR", "LI", "DFC", "DFC", "LD", "MI", "MC", "MC", "MD", "DC", "DC"])]},
            ]

        def get_absences(self, _fixture_id):
            return [{"jugador": "Baja L", "team": "Local FC", "estado": "injury", "detalle": "Lesión muscular", "source": "API-Football", "official": True}]

    assert attach_official_context([match], now, FakeClient()) == 1
    lineup = match["alineacion"]
    assert lineup["status"] == "confirmado"
    assert lineup["provider"] == "API-Football"
    assert len(lineup["local"]) == len(lineup["visitante"]) == 11
    assert len(lineup["clave_local"]) >= 3
    assert lineup["disponibilidad_local"][0]["official"] is True


def test_auditoria_y_alerta_identifican_solo_huecos_del_dia():
    now = datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)
    match = {"id": "m1", "home": "A", "away": "B", "kickoff": (now + timedelta(hours=2)).isoformat()}
    audit = content_audit([match], None, now)
    assert audit["matches_today"] == 1
    assert set(audit["incomplete"][0]["missing"]) == {"previa", "once", "posiciones", "props", "jugadores"}
    alerts = build_alerts(None, audit, [
        {"provider": "Gemini", "status": "failed"},
        {"provider": "Groq", "status": "failed"},
    ], now)
    assert {item["code"] for item in alerts} == {"today_content_incomplete", "all_ai_providers_failed"}


def test_rendimiento_desglosa_roi_y_compara_10_15():
    match = {
        "id": "m1", "league": "LaLiga", "home": "A", "away": "B",
        "kickoff": "2026-08-24T21:00:00+02:00", "finished": True, "result": [2, 0],
        "prediction_snapshot": {
            "generated_at": "2026-08-24T10:15:00+02:00", "window": "10:15",
            "probs": [60, 25, 15],
            "value": [{"market": "1x2", "selection": "1", "odds": 2.0, "edge": 0.2}],
        },
        "prediction_history": [
            {"generated_at": "2026-08-23T12:00:00+02:00", "window": "initial", "probs": [45, 30, 25]},
            {"generated_at": "2026-08-24T10:15:00+02:00", "window": "10:15", "probs": [60, 25, 15], "value": [{"market": "1x2", "selection": "1", "odds": 2.0, "edge": 0.2}]},
        ],
    }
    report = build_performance([match])
    assert report["overall"]["roi"] == 100.0
    assert report["by_market"][0]["label"] == "1X2"
    assert report["initial_vs_10_15"]["improved"] is True
