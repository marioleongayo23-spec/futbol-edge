from datetime import datetime, timedelta

from futbol_pred.hot_refresh import MADRID
from futbol_pred.matchday_lineup_baseline import refresh_payload


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MCD", "MC", "MC", "EI", "DC", "ED"]


def _names(prefix):
    return [f"{prefix} {i}" for i in range(11)]


def _finished(home, away, kickoff, local=None, visitante=None):
    return {
        "id": f"old-{home}-{away}-{kickoff.date()}",
        "home": home,
        "away": away,
        "kickoff": kickoff.isoformat(),
        "finished": True,
        "status": "FT",
        "alineacion": {
            "status": "confirmado",
            "lineup_kind": "official",
            "source_quality": "official",
            "provider": "API-Football",
            "local": local or _names(home),
            "visitante": visitante or _names(away),
            "posiciones_local": list(POSITIONS),
            "posiciones_visitante": list(POSITIONS),
        },
    }


def _target(now):
    return {
        "id": "next",
        "home": "Local",
        "away": "Visitante",
        "kickoff": (now + timedelta(hours=20)).isoformat(),
        "finished": False,
        "probs": [45, 30, 25],
        "alineacion": {
            "status": "estimado",
            "source_quality": "model_only",
            "lineup_kind": "model_estimate",
            "provider": "Gemini",
            "local": _names("Inventado L"),
            "visitante": _names("Inventado V"),
            "posiciones_local": list(POSITIONS),
            "posiciones_visitante": list(POSITIONS),
        },
    }


class _Offline:
    offline = True


def test_uses_last_official_xi_instead_of_model_only():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=MADRID)
    old_local = _finished("Local", "Otro", now - timedelta(days=5), local=_names("Oficial L"))
    old_away = _finished("Otro2", "Visitante", now - timedelta(days=4), visitante=_names("Oficial V"))
    target = _target(now)
    payload = {"matches": [old_local, old_away, target]}

    changed, stats = refresh_payload(payload, now=now, client=_Offline())

    assert changed is True
    assert stats["baseline"] == 1
    lineup = target["alineacion"]
    assert lineup["local"] == _names("Oficial L")
    assert lineup["visitante"] == _names("Oficial V")
    assert lineup["source_quality"] == "official_history_baseline"
    assert lineup["lineup_kind"] == "last_official_baseline"
    assert lineup["provider"] == "Último XI oficial"


def test_official_absence_is_replaced_from_recent_official_history():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=MADRID)
    older_names = _names("Local")
    older_names[1] = "Alternativa LI"
    latest_names = _names("Local")
    latest_names[1] = "Lesionado LI"
    older = _finished("Local", "Antiguo A", now - timedelta(days=10), local=older_names)
    latest = _finished("Local", "Antiguo B", now - timedelta(days=4), local=latest_names)
    old_away = _finished("Antiguo C", "Visitante", now - timedelta(days=3), visitante=_names("Oficial V"))
    target = _target(now)
    target["alineacion"]["disponibilidad_local"] = [
        {
            "jugador": "Lesionado LI",
            "estado": "lesión",
            "detalle": "lesión muscular",
            "source": "API-Football",
            "official": True,
        }
    ]

    changed, _ = refresh_payload({"matches": [older, latest, old_away, target]}, now=now, client=_Offline())

    assert changed is True
    lineup = target["alineacion"]
    assert lineup["local"][1] == "Alternativa LI"
    assert lineup["source_quality"] == "official_history_baseline_adjusted"
    assert lineup["integrity_replacements"][0]["out"] == "Lesionado LI"
    assert lineup["integrity_replacements"][0]["in"] == "Alternativa LI"


def test_partial_media_updates_only_grounded_side_and_keeps_other_last_official():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=MADRID)
    old_local = _finished("Local", "Otro", now - timedelta(days=5), local=_names("Oficial L"))
    old_away = _finished("Otro2", "Visitante", now - timedelta(days=4), visitante=_names("Oficial V"))
    target = _target(now)
    target["alineacion"].update({
        "source_quality": "media_partial",
        "lineup_kind": "partially_grounded_estimate",
        "provider": "AS + IA",
        "local": _names("Prensa L"),
        "visitante": _names("IA V"),
        "lineup_evidence": {
            "level": "trusted_media_partial",
            "local": {"grounded": True, "sources": [{"source": "AS"}]},
            "visitante": {"grounded": False, "sources": []},
        },
    })

    changed, stats = refresh_payload({"matches": [old_local, old_away, target]}, now=now, client=_Offline())

    assert changed is True
    assert stats["hybrid"] == 1
    lineup = target["alineacion"]
    assert lineup["local"] == _names("Prensa L")
    assert lineup["visitante"] == _names("Oficial V")
    assert lineup["source_quality"] == "official_history_hybrid"
    assert lineup["lineup_kind"] == "source_grounded_plus_last_official"


class _BackfillClient:
    offline = False

    def find_fixture(self, home, away, kickoff):
        return {"fixture": {"id": 9001}, "teams": {"home": {"name": home}, "away": {"name": away}}}

    def get_official_lineup(self, fixture_id):
        assert fixture_id == 9001
        return [
            {
                "team": "Local",
                "formation": "4-3-3",
                "starters": [{"name": f"Backfill L {i}", "position": POSITIONS[i]} for i in range(11)],
            },
            {
                "team": "Otro",
                "formation": "4-3-3",
                "starters": [{"name": f"Backfill O {i}", "position": POSITIONS[i]} for i in range(11)],
            },
        ]


def test_backfills_missing_last_official_lineup_and_caches_it():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=MADRID)
    previous = {
        "id": "previous",
        "home": "Local",
        "away": "Otro",
        "kickoff": (now - timedelta(days=4)).isoformat(),
        "finished": True,
        "status": "FT",
    }
    old_away = _finished("Otro2", "Visitante", now - timedelta(days=4), visitante=_names("Oficial V"))
    target = _target(now)
    payload = {"matches": [previous, old_away, target], "source_health": {}}

    changed, stats = refresh_payload(payload, now=now, client=_BackfillClient())

    assert changed is True
    assert stats["backfill"]["resolved"] == 1
    assert previous["alineacion"]["status"] == "confirmado"
    assert previous["alineacion"]["local"][0] == "Backfill L 0"
    assert target["alineacion"]["local"][0] == "Backfill L 0"
