from datetime import datetime, timedelta

from futbol_pred.coverage import MADRID, coverage_for_match, enrich_payload


def _xi(status="probable"):
    positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
    return {
        "status": status,
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "posiciones_local": positions,
        "posiciones_visitante": positions,
        "provider": "Fuente externa" if status == "probable" else "API-Football",
        "source_updated_at": "2026-08-26T18:00:00+02:00",
    }


def _players():
    return {
        "laliga": {
            "players": [
                {"team": team, "player": f"{team}{i}"}
                for team in ("A", "B") for i in range(11)
            ]
        }
    }


def test_cobertura_no_exige_fuentes_antes_de_su_ventana():
    now = datetime(2026, 8, 26, 9, 0, tzinfo=MADRID)
    match = {
        "id": "m1", "home": "A", "away": "B", "status": "SCHEDULED",
        "source": "football_data", "kickoff": (now + timedelta(hours=13)).isoformat(),
        "updatedAt": now.isoformat(),
    }
    coverage = coverage_for_match(match, now)
    assert coverage is not None
    assert coverage["items"]["fixture"]["state"] == "ok"
    assert coverage["items"]["weather"]["state"] == "scheduled"
    assert coverage["items"]["absences"]["required"] is False
    assert coverage["items"]["lineup_probable"]["required"] is False
    assert coverage["items"]["lineup_official"]["required"] is False
    assert coverage["items"]["odds"]["state"] == "missing"
    assert coverage["missing_required"] == ["odds"]


def test_tmenos2h_detecta_clima_bajas_cuotas_y_once_solo_estimado():
    now = datetime(2026, 8, 26, 19, 0, tzinfo=MADRID)
    match = {
        "id": "m2", "home": "A", "away": "B", "status": "SCHEDULED",
        "kickoff": (now + timedelta(hours=2)).isoformat(), "updatedAt": now.isoformat(),
        "alineacion": _xi("estimado"), "odds": "pendiente_odds_api",
    }
    coverage = coverage_for_match(match, now)
    assert coverage["items"]["weather"]["state"] == "missing"
    assert coverage["items"]["absences"]["state"] == "missing"
    assert coverage["items"]["lineup_probable"]["state"] == "estimated"
    assert coverage["items"]["lineup_official"]["state"] == "scheduled"
    assert set(coverage["missing_required"]) == {"weather", "absences", "lineup_probable", "odds"}


def test_tmenos30_publicado_parcial_no_cuenta_como_once_oficial():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    match = {
        "id": "m3", "home": "A", "away": "B", "status": "SCHEDULED",
        "kickoff": (now + timedelta(minutes=30)).isoformat(), "updatedAt": now.isoformat(),
        "alineacion": _xi("probable"),
        "operational_checks": {
            "lineup_checked_at": now.isoformat(), "lineup_check_result": "partial",
            "weather_checked_at": now.isoformat(), "absences_checked_at": now.isoformat(),
        },
        "weather": {"temperature_c": 23, "source_updated_at": now.isoformat()},
        "odds": {"1x2": {"1": 1.9, "X": 3.4, "2": 4.1}},
    }
    coverage = coverage_for_match(match, now)
    assert coverage["items"]["lineup_official"]["required"] is True
    assert coverage["items"]["lineup_official"]["state"] == "partial"
    assert coverage["complete"] is False


def test_once_confirmado_11_mas_11_cierra_cobertura_oficial():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    match = {
        "id": "m4", "home": "A", "away": "B", "status": "SCHEDULED",
        "kickoff": (now + timedelta(minutes=30)).isoformat(), "updatedAt": now.isoformat(),
        "alineacion": _xi("confirmado"),
        "operational_checks": {
            "lineup_checked_at": now.isoformat(), "lineup_check_result": "published",
            "weather_checked_at": now.isoformat(), "absences_checked_at": now.isoformat(),
        },
        "weather": {"temperature_c": 23, "source_updated_at": now.isoformat()},
        "odds": {"1x2": {"1": 1.9, "X": 3.4, "2": 4.1}},
    }
    coverage = coverage_for_match(match, now)
    assert coverage["items"]["lineup_official"]["state"] == "ok"
    assert coverage["complete"] is True


def test_enrich_recalcula_complete_y_hace_visibles_cuotas_ausentes():
    now = datetime(2026, 8, 26, 11, 7, tzinfo=MADRID)
    match = {
        "id": "real-missing-odds", "home": "A", "away": "B", "status": "SCHEDULED",
        "kickoff": (now + timedelta(hours=10)).isoformat(), "updatedAt": now.isoformat(),
        "preview": " ".join(["previa"] * 100), "alineacion": _xi("estimado"),
        "odds": "pendiente_odds_api",
    }
    payload = {
        "matches": [match], "players": _players(),
        "content_audit": {"matches_today": 1, "complete": 1, "incomplete": [], "status": "ok", "checked_at": now.isoformat()},
    }
    assert enrich_payload(payload, now) is True
    assert payload["content_audit"]["complete"] == 0
    assert payload["content_audit"]["status"] == "warning"
    assert payload["content_audit"]["incomplete"][0]["missing"] == ["cuotas"]
    assert payload["matches"][0]["coverage"]["items"]["odds"]["state"] == "missing"
