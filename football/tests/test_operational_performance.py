from datetime import datetime, timedelta

from futbol_pred.dashboard import MADRID, _merge_lineup_players
from futbol_pred.ingest.lineups_ai import build_statistical_lineup
from futbol_pred.operational import (
    annotate_prediction_context, attach_official_context, build_alerts, content_audit, lineup_impact,
)
from futbol_pred.performance import build_performance


def _squad(prefix):
    return [
        {"name": f"{prefix} {i}", "position": "Goalkeeper" if i == 0 else "Defence" if i < 5 else "Midfield" if i < 8 else "Offence"}
        for i in range(15)
    ]


def _real_props(prefix):
    return [
        {
            "jugador": f"{prefix} {i}", "g": 0.25, "a": 0.15, "r": 2.2,
            "rp": 0.9, "fc": 1.1, "fr": 1.0, "t": 0.15,
            "min": 78.0, "tit": 1.0, "source": "API-Football · players",
            "sample_minutes": 900,
        }
        for i in range(3)
    ]


def test_once_oficial_sustituye_estimado_y_no_inventa_props_sin_muestra():
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
    assert lineup["clave_local"] == []
    assert lineup["clave_visitante"] == []
    assert lineup["numeric_props_source"] == "pending_real_data"
    assert lineup["disponibilidad_local"][0]["official"] is True


def test_auditoria_y_alerta_identifican_huecos_obligatorios_del_dia():
    now = datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)
    match = {"id": "m1", "home": "A", "away": "B", "kickoff": (now + timedelta(hours=2)).isoformat()}
    audit = content_audit([match], None, now)
    assert audit["matches_today"] == 1
    assert set(audit["incomplete"][0]["missing"]) == {"previa", "once", "posiciones", "jugadores"}
    alerts = build_alerts(None, audit, [
        {"provider": "Gemini", "status": "failed"},
        {"provider": "Groq", "status": "failed"},
    ], now)
    assert {item["code"] for item in alerts} == {"today_content_incomplete", "all_ai_providers_failed"}


def test_rendimiento_desglosa_roi_compara_capas_y_10_15():
    latest = {
        "generated_at": "2026-08-24T10:15:00+02:00", "window": "10:15",
        "probs": [60, 25, 15],
        "model_probs": [50, 30, 20],
        "odds": {"1x2": {"fair": {"1": 0.55, "X": 0.28, "2": 0.17}}},
        "value": [{"market": "1x2", "selection": "1", "odds": 2.0, "edge": 0.2}],
    }
    match = {
        "id": "m1", "league": "LaLiga", "home": "A", "away": "B",
        "kickoff": "2026-08-24T21:00:00+02:00", "finished": True, "result": [2, 0],
        "prediction_snapshot": latest,
        "prediction_history": [
            {"generated_at": "2026-08-23T12:00:00+02:00", "window": "initial", "probs": [45, 30, 25]},
            latest,
        ],
    }
    report = build_performance([match])
    assert report["overall"]["roi"] == 100.0
    assert report["by_market"][0]["label"] == "1X2"
    assert report["initial_vs_10_15"]["improved"] is True

    quality = report["probability_quality"]
    assert quality["published"]["n"] == quality["model_only"]["n"] == 1
    assert quality["market"]["n"] == 1
    assert quality["published"]["log_loss"] < quality["model_only"]["log_loss"]
    assert quality["published_vs_model"]["n"] == 1
    assert quality["published_vs_model"]["improved_both"] is True
    assert quality["published_vs_model"]["log_loss_delta"] < 0


def test_jugadores_del_once_rellenan_indice_global_sin_huecos():
    match = {
        "home": "Celta B", "away": "Andorra", "league": "LaLiga Hypermotion",
        "alineacion": build_statistical_lineup({"xg": [1.2, 0.9]}, _squad("C"), _squad("A")),
    }
    players = _merge_lineup_players(None, [match])
    rows = players["segunda"]["players"]
    assert len(rows) == 22
    assert {row["team"] for row in rows} == {"Celta B", "Andorra"}
    assert all(row["source"] == "Motor estadístico local" for row in rows)


def test_impacto_once_cuantifica_props_reales_y_bajas_sin_alterar_1x2():
    lineup = build_statistical_lineup({"xg": [1.4, 1.0]}, _squad("L"), _squad("V"))
    lineup["status"] = "confirmado"
    lineup["clave_local"] = _real_props("L")
    lineup["clave_visitante"] = _real_props("V")
    lineup["numeric_props_source"] = "API-Football · players"
    lineup["disponibilidad_local"] = [{
        "jugador": "Titular lesionado", "estado": "injury", "official": True,
        "source": "API-Football", "detalle": "Lesión",
    }]
    impact = lineup_impact(lineup)
    assert impact["home"]["expected_minutes_avg"] >= 55
    assert impact["home"]["official_absences"] == 1
    assert impact["confidence_penalty_pp"] == 3.0
    assert impact["probability_adjustment"] == "not_applied"

    match = {
        "probs": [52, 28, 20], "model_meta": {"components": {}},
        "alineacion": lineup,
    }
    annotate_prediction_context([match])
    assert match["probs"] == [52, 28, 20]
    assert match["lineup_impact"]["home"]["attack_presence_index"] is not None
    assert match["prediction_confidence"]["availability_penalty_pp"] == 3.0


def test_poll_oficial_usa_t60_y_no_repite_si_ya_confirma():
    now = datetime(2026, 8, 24, 19, tzinfo=MADRID)
    match = {"id": "win", "home": "A", "away": "B", "kickoff": (now + timedelta(hours=1)).isoformat(), "xg": [1.1, 1.0], "stats": {}}

    class WindowClient:
        offline = False
        calls = 0
        def find_fixture(self, *_args): return {"fixture": {"id": 9}}
        def get_official_lineup(self, _id):
            self.calls += 1
            positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
            return [
                {"team": "A", "formation": "4-3-3", "starters": [{"name": f"A{i}", "position": p} for i, p in enumerate(positions)]},
                {"team": "B", "formation": "4-3-3", "starters": [{"name": f"B{i}", "position": p} for i, p in enumerate(positions)]},
            ]
        def get_absences(self, _id): return []

    client = WindowClient()
    assert attach_official_context([match], now, client) == 1
    assert match["alineacion"]["official_poll_window"] == "T-60"
    assert "T-60" in match["alineacion"]["official_poll_windows"]
    assert attach_official_context([match], now + timedelta(minutes=30), client) == 0
    assert client.calls == 1


def test_poll_oficial_reintenta_t30_si_t60_no_tenia_once():
    kickoff = datetime(2026, 8, 24, 20, tzinfo=MADRID)
    match = {"id": "retry", "home": "A", "away": "B", "kickoff": kickoff.isoformat(), "xg": [1.1, 1.0], "stats": {}, "alineacion": {}}

    class RetryClient:
        offline = False
        calls = 0
        def find_fixture(self, *_args): return {"fixture": {"id": 10}}
        def get_official_lineup(self, _id):
            self.calls += 1
            if self.calls == 1: return None
            positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
            return [
                {"team": "A", "formation": "4-3-3", "starters": [{"name": f"A{i}", "position": p} for i, p in enumerate(positions)]},
                {"team": "B", "formation": "4-3-3", "starters": [{"name": f"B{i}", "position": p} for i, p in enumerate(positions)]},
            ]
        def get_absences(self, _id): return []

    client = RetryClient()
    assert attach_official_context([match], kickoff - timedelta(hours=1), client) == 0
    assert match["alineacion"]["official_poll_window_last_attempt"] == "T-60"
    assert attach_official_context([match], kickoff - timedelta(minutes=30), client) == 1
    assert match["alineacion"]["official_poll_window"] == "T-30"
    assert set(match["alineacion"]["official_poll_windows"]) == {"T-60", "T-30"}


def test_alerta_de_fuente_stale_detecta_colector_caido():
    # Un colector puede quedarse parado (cuota agotada, endpoint caído) mientras el
    # workflow termina en verde. La alerta debe destaparlo por su marca de tiempo.
    now = datetime(2026, 8, 30, 15, 37, tzinfo=MADRID)
    previous = {
        "generated_at": now.isoformat(),
        "source_health": {
            "the_odds_api": {"checked_at": (now - timedelta(hours=30)).isoformat()},
            "api_football": {"checked_at": (now - timedelta(hours=3)).isoformat()},
            "current_squads": {"checked_at": now.isoformat()},
        },
    }

    alerts = build_alerts(previous, {"incomplete": []}, [], now)
    codes = {a["code"] for a in alerts}

    assert "source_stale_the_odds_api" in codes
    assert "source_stale_api_football" not in codes  # 3 h < umbral 12 h
    assert "source_stale_current_squads" not in codes  # fresco
    odds_alert = next(a for a in alerts if a["code"] == "source_stale_the_odds_api")
    assert odds_alert["severity"] == "critical"  # 30 h > 2×12 h
    assert odds_alert["source"] == "the_odds_api"
