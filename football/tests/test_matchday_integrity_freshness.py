from datetime import datetime, timedelta

from futbol_pred.hot_refresh import MADRID
from futbol_pred.matchday_absence_refresh import _dedupe
from futbol_pred.matchday_freshness_gate import _audit_match
from futbol_pred.matchday_lineup_integrity import _dedupe_availability, _repair_side


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MCD", "MC", "MC", "EI", "DC", "ED"]


def _names(prefix):
    return [f"{prefix} {i}" for i in range(11)]


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
                {
                    "jugador": "Lesionado LI",
                    "estado": "lesión",
                    "detalle": "lesión muscular",
                    "official": True,
                }
            ],
        },
    }

    replacements = _repair_side([old, target], target, target["alineacion"], "local")

    assert target["alineacion"]["local"][1] == "Alternativa LI"
    assert replacements == [
        {
            "side": "local",
            "out": "Lesionado LI",
            "in": "Alternativa LI",
            "position": "LI",
            "reason": "baja oficial + continuidad del último XI oficial",
            "resolved": True,
        }
    ]


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


def test_freshness_gate_is_critical_when_starter_is_official_absence():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=30)
    match = {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "alineacion": {
            "status": "probable",
            "local": ["Jugador X"] + _names("L")[1:],
            "visitante": _names("V"),
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
            "critical_probable_checked_at": now.isoformat(),
            "player_props_checked_at": now.isoformat(),
            "clave_local": [{"jugador": f"L{i}"} for i in range(8)],
            "clave_visitante": [{"jugador": f"V{i}"} for i in range(8)],
            "disponibilidad_local": [
                {"jugador": "Jugador X", "estado": "lesión", "detalle": "muscular", "official": True}
            ],
            "disponibilidad_visitante": [],
        },
        "operational_checks": {
            "weather_checked_at": now.isoformat(),
            "absences_checked_at": now.isoformat(),
            "lineup_checked_at": now.isoformat(),
        },
        "weather": {"forecast_for": kickoff.isoformat(), "source_updated_at": now.isoformat()},
        "odds": {"1x2": {}, "meta": {"checked_at": now.isoformat(), "ttl_minutes": 5}},
        "market_hot_refresh": {"checked_at": now.isoformat(), "ttl_minutes": 5, "provider": "The Odds API"},
        "prediction_live_refresh": {"checked_at": now.isoformat()},
    }

    audit = _audit_match(match, now, 30)
    assert audit["status"] == "critical"
    assert audit["all_fresh"] is False
    assert any("Jugador X" in conflict for conflict in audit["hard_conflicts"])


def test_freshness_gate_can_reach_ready_when_every_critical_input_is_fresh():
    now = datetime(2026, 8, 26, 20, 30, tzinfo=MADRID)
    kickoff = now + timedelta(minutes=30)
    match = {
        "home": "Local",
        "away": "Visitante",
        "kickoff": kickoff.isoformat(),
        "alineacion": {
            "status": "confirmado",
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
        },
        "operational_checks": {
            "weather_checked_at": now.isoformat(),
            "absences_checked_at": now.isoformat(),
            "lineup_checked_at": now.isoformat(),
        },
        "weather": {"forecast_for": kickoff.isoformat(), "source_updated_at": now.isoformat()},
        "odds": {"1x2": {}, "meta": {"checked_at": now.isoformat(), "ttl_minutes": 5}},
        "market_hot_refresh": {"checked_at": now.isoformat(), "ttl_minutes": 5, "provider": "The Odds API"},
        "prediction_live_refresh": {"checked_at": now.isoformat()},
    }

    audit = _audit_match(match, now, 30)
    assert audit["status"] == "ready"
    assert audit["all_fresh"] is True
    assert audit["requires_retry"] is False
    assert audit["missing_or_stale"] == []
    assert audit["hard_conflicts"] == []
