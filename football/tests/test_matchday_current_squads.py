from datetime import datetime
from zoneinfo import ZoneInfo

from futbol_pred.matchday_current_squads import refresh_payload

MADRID = ZoneInfo("Europe/Madrid")


def _players(prefix):
    return [
        {"id": 1000 + i, "name": f"{prefix}{i}", "position": "Goalkeeper" if i == 0 else "Defender", "number": i + 1}
        for i in range(11)
    ]


class FakeClient:
    offline = False

    def __init__(self):
        self.calls = []

    def _get(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "teams":
            return {
                "response": [
                    {"team": {"id": 1, "name": "Equipo A"}},
                    {"team": {"id": 2, "name": "Equipo B"}},
                ]
            }
        if path == "players/squads" and int(params["team"]) == 1:
            return {"response": [{"players": _players("A")}]} 
        if path == "players/squads" and int(params["team"]) == 2:
            return {"response": [{"players": _players("B")}]} 
        raise AssertionError((path, params))


def _payload():
    return {
        "players": {
            "laliga": {
                "label": "LaLiga",
                "rankings": {},
                "players": [
                    {"player": "Jugador Viejo", "team": "Equipo A", "position": "DFC", "goals": 9, "min": 900},
                    {"player": "A0", "team": "Equipo A", "position": "POR", "goals": 0, "min": 90},
                ],
            }
        },
        "matches": [
            {
                "id": "m1",
                "home": "Equipo A",
                "away": "Equipo B",
                "league": "LaLiga",
                "kickoff": "2026-08-29T15:00:00+02:00",
                "finished": False,
                "alineacion": {
                    "status": "probable",
                    "source_quality": "media_grounded",
                    "lineup_kind": "source_grounded_probable",
                    "local": ["Jugador Viejo"] + [f"A{i}" for i in range(1, 11)],
                    "visitante": [f"B{i}" for i in range(11)],
                    "posiciones_local": ["POR"] + ["DFC"] * 10,
                    "posiciones_visitante": ["POR"] + ["DFC"] * 10,
                },
            }
        ],
    }


def test_purga_jugadores_fuera_de_plantilla_actual_y_oculta_once_contaminado():
    payload = _payload()
    client = FakeClient()
    changed, stats = refresh_payload(
        payload,
        now=datetime(2026, 8, 29, 9, 0, tzinfo=MADRID),
        football_client=client,
    )

    assert changed is True
    names = [row["player"] for row in payload["players"]["laliga"]["players"] if row.get("team") == "Equipo A"]
    assert "Jugador Viejo" not in names
    assert set(f"A{i}" for i in range(11)).issubset(names)
    assert stats["stale_players_purged"] == 1

    lineup = payload["matches"][0]["alineacion"]
    assert lineup["source_quality"] == "model_only"
    assert lineup["lineup_kind"] == "roster_conflict_withheld"
    assert lineup["current_squad_conflicts"]["local"] == ["Jugador Viejo"]


def test_reutiliza_plantilla_actual_cacheada_sin_consumir_api():
    now = datetime(2026, 8, 29, 9, 0, tzinfo=MADRID)
    payload = _payload()
    for team, prefix in (("Equipo A", "A"), ("Equipo B", "B")):
        bucket = payload["players"]["laliga"]["players"]
        bucket[:] = [row for row in bucket if row.get("team") != team]
        bucket.extend(
            {
                "player": f"{prefix}{i}",
                "team": team,
                "position": "POR" if i == 0 else "DFC",
                "current_squad_member": True,
                "current_squad_checked_at": now.isoformat(),
            }
            for i in range(11)
        )

    class NoNetwork:
        offline = False
        def _get(self, path, params):
            raise AssertionError("No debe consultar API con roster actual <12h")

    changed, stats = refresh_payload(payload, now=now, football_client=NoNetwork())
    assert stats["teams_fetched"] == 0
    assert stats["api_calls_estimate"] == 0
    assert payload["matches"][0]["current_squads"]["local"]["players"]
