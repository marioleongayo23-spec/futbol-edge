"""Deduplicación de equipos fantasma por alias en el bloque de jugadores."""

from futbol_pred.dashboard import _dedupe_players_by_team


def _players():
    return {
        "laliga": {
            "label": "LaLiga",
            "rankings": {},
            "players": [
                # Fila de STATS (nombre corto, sin plantilla, con rendimiento).
                {"player": "David Hancko", "team": "Atletico Madrid", "goals": 3, "min": 900},
                # Fila de PLANTILLA actual (nombre largo, con acento y metadatos).
                {
                    "player": "Dávid Hancko", "team": "Club Atlético de Madrid",
                    "goals": 0, "min": 0, "position": "Defence", "number": 5,
                    "current_squad_member": True,
                },
                # Jugador solo en plantilla actual.
                {
                    "player": "Jan Oblak", "team": "Club Atlético de Madrid",
                    "position": "Goalkeeper", "current_squad_member": True,
                },
                # Otro club, sin duplicar.
                {"player": "Portero Rival", "team": "Getafe CF", "current_squad_member": True},
            ],
        }
    }


def _matches():
    return [
        {"home": "Club Atlético de Madrid", "away": "Getafe CF"},
    ]


def test_funde_equipos_alias_en_uno_solo():
    out = _dedupe_players_by_team(_players(), _matches())
    teams = {row["team"] for row in out["laliga"]["players"]}
    # 'Atletico Madrid' desaparece; queda el nombre del calendario.
    assert teams == {"Club Atlético de Madrid", "Getafe CF"}
    assert "Atletico Madrid" not in teams


def test_jugador_duplicado_se_funde_conservando_stats_y_plantilla():
    out = _dedupe_players_by_team(_players(), _matches())
    hancko = [r for r in out["laliga"]["players"] if "ancko" in r["player"]]
    assert len(hancko) == 1  # una sola fila, no dos
    row = hancko[0]
    assert row["team"] == "Club Atlético de Madrid"
    assert row["current_squad_member"] is True       # metadato de plantilla
    assert row["position"] == "Defence" and row["number"] == 5
    assert row["goals"] == 3 and row["min"] == 900    # rendimiento de las stats


def test_equipo_sin_alias_no_cambia():
    out = _dedupe_players_by_team(_players(), _matches())
    getafe = [r for r in out["laliga"]["players"] if r["team"] == "Getafe CF"]
    assert len(getafe) == 1 and getafe[0]["player"] == "Portero Rival"


def test_sin_partidos_conserva_nombre_original():
    # Sin calendario que fije el nombre preferido, no se pierde el equipo.
    out = _dedupe_players_by_team(_players(), [])
    assert out["laliga"]["players"]  # no vacía
    # Hancko sigue fundido (mismo canónico), bajo alguno de los dos nombres.
    hancko = [r for r in out["laliga"]["players"] if "ancko" in r["player"]]
    assert len(hancko) == 1
