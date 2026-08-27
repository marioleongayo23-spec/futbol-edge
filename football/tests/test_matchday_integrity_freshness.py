from datetime import datetime, timedelta

from futbol_pred.hot_refresh import MADRID
from futbol_pred.lineup_authority import is_authoritative_official_lineup
from futbol_pred.matchday_absence_refresh import _dedupe
from futbol_pred.matchday_confirmation_guard import refresh_payload as guard_refresh_payload
from futbol_pred.matchday_freshness_gate import _apply_publication_gate, _audit_match
from futbol_pred.matchday_lineup_integrity import _dedupe_availability, _repair_side
from futbol_pred.matchday_official_last_mile import refresh_payload as last_mile_refresh_payload


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MCD", "MC", "MC", "EI", "DC", "ED"]


def _names(prefix):
    return [f"{prefix} {i}" for i in range(11)]


def _official_lineup(now):
    return {
        "status": "confirmado",
        "phase": "final",
        "lineup_kind": "official",
        "source_quality": "official",
        "provider": "API-Football",
        "official_fixture_id": 12345,
        "local": _names("L"),
        "visitante": _names("V"),
        "posiciones_local": POSITIONS,
        "posiciones_visitante": POSITIONS,
        "source_updated_at": now.isoformat(),
        "official_poll_at": now.isoformat(),
        "player_props_checked_at": now.isoformat(),
        "clave_local": [{"jugador": f"L{i}"} for i in range(8)],
        "clave_visitante": [{"jugador": f"V{i}"} for i in range(8)],
        "disponibilidad_local": [],
        "disponibilidad_visitante": [],
        "quality": {"official": True, "complete": True, "lineup_players": 22},
    }


def _ready_match(now, kickoff):
    return {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "alineacion": _official_lineup(now),
        "operational_checks": {
            "weather_checked_at": now.isoformat(),
            "absences_checked_at": now.isoformat(),
            "lineup_checked_at": now.isoformat(),
        },
        "weather": {"forecast_for": kickoff.isoformat(), "source_updated_at": now.isoformat()},
        "odds": {"1x2": {}, "meta": {"checked_at": now.isoformat(), "ttl_minutes": 5}},
        "market_hot_refresh": {"checked_at": now.isoformat(), "ttl_minutes": 5, "provider": "The Odds API"},
        "prediction_live_refresh": {"checked_at": now.isoformat()},
        "prediction_confidence": {"score": 82, "level": "alta"},
        "recommendation": {"decision": "eligible", "label": "Pronóstico publicable", "reasons": []},
        "probs": [52, 28, 20],
    }


def test_absence_refresh_deduplicates_exact_rows():
    row = {
        "team": "Local",
        "jugador": "Jugador X",
        "estado": "lesión",
        "detalle": "Hamstring Injury",
        "official": True,
    }
    assert _dedupe([row, dict(row)]) == [row]


def test_lineup_integrity_replaces_official_absence_from_recent_official_history():
    kickoff = datetime(2026, 8, 26, 21, tzinfo=MADRID)
    old = {
        "home": "Local",
        "away": "Rival antiguo",
        "kickoff": (kickoff - timedelta(days=7)).isoformat(),
        "alineacion": {
            "status": "confirmado",
            "local": ["Portero", "Alternativa LI", "Central 1", "Central 2", "LD", "MCD", "MC1", "MC2", "EI", "DC", "ED"],
            "visitante": _names("R"),
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
        },
    }
    target = {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "alineacion": {
            "status": "probable",
            "local": ["Portero", "Lesionado LI", "Central 1", "Central 2", "LD", "MCD", "MC1", "MC2", "EI", "DC", "ED"],
            "visitante": _names("V"),
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
            "disponibilidad_local": [
                {"jugador": "Lesionado LI", "estado": "lesión", "detalle": "lesión muscular", "official": True}
            ],
        },
    }

    replacements = _repair_side([old, target], target, target["alineacion"], "local")

    assert target["alineacion"]["local"][1] == "Alternativa LI"
    assert replacements[0]["out"] == "Lesionado LI"
    assert replacements[0]["in"] == "Alternativa LI"
    assert replacements[0]["resolved"] is True


def test_lineup_integrity_deduplicates_availability_without_touching_player_identity():
    lineup = {
        "disponibilidad_local": [
            {"jugador": "Jugador X", "estado": "lesión", "detalle": "muscular", "official": True},
            {"jugador": "Jugador X", "estado": "lesión", "detalle": "muscular", "official": True},
        ]
    }
    assert _dedupe_availability(lineup) is True
    assert len(lineup["disponibilidad_local"]) == 1
    assert lineup["disponibilidad_local"][0]["jugador"] == "Jugador X"


def test_authority_rejects_model_only_even_if_status_says_confirmado():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    fake = {
        "status": "confirmado",
        "phase": "final",
        "lineup_kind": "model_estimate",
        "source_quality": "model_only",
        "provider": "Motor estadístico local",
        "local": _names("L"),
        "visitante": _names("V"),
    }
    assert is_authoritative_official_lineup(fake) is False
    assert is_authoritative_official_lineup(_official_lineup(now)) is True


def test_confirmation_guard_downgrades_false_confirmed_so_polling_can_continue():
    now = datetime(2026, 8, 26, 20, 20, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=40)
    match = {
        "home": "Local", "away": "Visitante", "kickoff": kickoff.isoformat(), "finished": False,
        "alineacion": {
            "status": "confirmado", "lineup_kind": "model_estimate", "source_quality": "model_only",
            "provider": "Motor estadístico local", "local": _names("L"), "visitante": _names("V"),
        },
    }
    changed, stats = guard_refresh_payload({"matches": [match]}, now=now)
    assert changed is True
    assert stats["downgraded"] == 1
    assert match["alineacion"]["status"] == "estimado"
    assert match["alineacion"]["lineup_kind"] == "invalid_confirmation_downgraded"
    assert "trazabilidad oficial" in match["alineacion"]["display_warning"]


def test_confirmation_guard_keeps_real_official_lineup():
    now = datetime(2026, 8, 26, 20, 20, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=40)
    match = {
        "home": "Local", "away": "Visitante", "kickoff": kickoff.isoformat(), "finished": False,
        "alineacion": _official_lineup(now),
    }
    changed, stats = guard_refresh_payload({"matches": [match]}, now=now)
    assert changed is False
    assert stats["downgraded"] == 0
    assert match["alineacion"]["status"] == "confirmado"


def test_freshness_gate_is_critical_when_starter_is_official_absence():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=30)
    match = _ready_match(now, kickoff)
    match["alineacion"]["status"] = "probable"
    match["alineacion"]["provider"] = "AS"
    match["alineacion"]["source_quality"] = "media_grounded"
    match["alineacion"]["lineup_kind"] = "source_grounded_probable"
    match["alineacion"].pop("official_fixture_id", None)
    match["alineacion"]["quality"] = {"official": False}
    match["alineacion"]["local"][0] = "Jugador X"
    match["alineacion"]["disponibilidad_local"] = [
        {"jugador": "Jugador X", "estado": "lesión", "detalle": "muscular", "official": True}
    ]

    audit = _audit_match(match, now, 30)
    assert audit["status"] == "critical"
    assert audit["all_fresh"] is False
    assert any("Jugador X" in conflict for conflict in audit["hard_conflicts"])


def test_weather_naive_open_meteo_hour_is_madrid_local_not_utc():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    kickoff = datetime(2026, 8, 26, 21, 0, tzinfo=MADRID)
    match = _ready_match(now, kickoff)
    match["weather"]["forecast_for"] = "2026-08-26T21:00:00"

    audit = _audit_match(match, now, 30)
    assert audit["checks"]["weather"]["ok"] is True
    assert audit["checks"]["weather"]["kickoff_hour_match"] is True


def test_freshness_gate_can_reach_ready_when_every_critical_input_is_fresh():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=30)
    match = _ready_match(now, kickoff)

    audit = _audit_match(match, now, 30)
    assert audit["status"] == "ready"
    assert audit["all_fresh"] is True
    assert audit["requires_retry"] is False
    assert audit["missing_or_stale"] == []
    assert audit["hard_conflicts"] == []
    assert audit["checks"]["official_lineup"]["state"] == "confirmed_authoritative"


def test_freshness_gate_treats_legacy_odds_string_as_warning_not_crash():
    now = datetime(2026, 8, 26, 20, 48, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=12)
    match = _ready_match(now, kickoff)
    match["odds"] = "pendiente_odds_api"
    match.pop("market_hot_refresh", None)

    audit = _audit_match(match, now, 12)
    assert audit["status"] == "warning"
    assert audit["checks"]["odds"]["ok"] is False
    assert audit["checks"]["odds"]["state"] == "legacy_pending_or_unavailable"
    assert audit["checks"]["odds"]["raw_state"] == "pendiente_odds_api"
    assert audit["hard_conflicts"] == []


def test_gate_forces_no_pick_and_caps_100_confidence_when_not_ready():
    now = datetime(2026, 8, 26, 20, 48, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=12)
    match = _ready_match(now, kickoff)
    match["prediction_confidence"] = {"score": 100, "level": "alta"}
    match["recommendation"] = {"decision": "eligible", "label": "Pronóstico publicable", "reasons": []}
    original_probs = list(match["probs"])
    match["odds"] = "pendiente_odds_api"
    match.pop("market_hot_refresh", None)
    result = _audit_match(match, now, 12)

    changed = _apply_publication_gate(match, result, now)

    assert changed is True
    assert result["status"] == "warning"
    assert match["probs"] == original_probs
    assert match["prediction_confidence"]["score"] == 54
    assert match["prediction_confidence"]["raw_score_before_freshness_gate"] == 100.0
    assert match["recommendation"]["decision"] == "no_pick"
    assert "datos por completar" in match["recommendation"]["label"]


def test_model_only_confirmed_becomes_critical_and_cannot_be_publishable():
    now = datetime(2026, 8, 26, 20, 54, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=6)
    match = _ready_match(now, kickoff)
    match["alineacion"].update({
        "status": "confirmado",
        "lineup_kind": "model_estimate",
        "source_quality": "model_only",
        "provider": "Motor estadístico local",
    })
    match["alineacion"].pop("official_fixture_id", None)
    match["alineacion"]["quality"] = {"official": False}

    result = _audit_match(match, now, 6)
    assert result["status"] == "critical"
    assert result["checks"]["official_lineup"]["state"] == "invalid_confirmation_provenance"
    assert "XI marcado como confirmado sin procedencia oficial verificable" in result["hard_conflicts"]


class _LastMileClient:
    offline = False

    def find_fixture(self, home, away, kickoff):
        return {"fixture": {"id": 777}, "teams": {"home": {"name": home}, "away": {"name": away}}}

    def get_official_lineup(self, fixture_id):
        assert fixture_id == 777
        return [
            {
                "team": "Local",
                "formation": "4-3-3",
                "starters": [{"name": f"L {i}", "position": POSITIONS[i]} for i in range(11)],
            },
            {
                "team": "Visitante",
                "formation": "4-3-3",
                "starters": [{"name": f"V {i}", "position": POSITIONS[i]} for i in range(11)],
            },
        ]


def test_last_mile_can_replace_estimate_with_authoritative_official_xi_at_t5():
    now = datetime(2026, 8, 26, 20, 55, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=5)
    match = {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "finished": False,
        "alineacion": {
            "status": "estimado",
            "lineup_kind": "model_estimate",
            "source_quality": "model_only",
            "provider": "Motor estadístico local",
            "local": _names("OldL"),
            "visitante": _names("OldV"),
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
        },
    }

    changed, stats = last_mile_refresh_payload({"matches": [match]}, now=now, client=_LastMileClient())

    assert changed is True
    assert stats["official_found"] == 1
    assert match["api_football_fixture_id"] == 777
    assert match["alineacion"]["local"] == _names("L")
    assert match["alineacion"]["visitante"] == _names("V")
    assert match["alineacion"]["source_quality"] == "official"
    assert match["alineacion"]["lineup_kind"] == "official"
    assert is_authoritative_official_lineup(match["alineacion"]) is True
