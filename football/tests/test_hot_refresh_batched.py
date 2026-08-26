from datetime import datetime

from futbol_pred.hot_refresh_batched import refresh_payload
from futbol_pred.ingest.api_football import ApiFootballClient


class NoWeather:
    def forecast(self, _venue, _kickoff):
        return None


def _lineup(team, prefix):
    grids = ["1:1", "2:1", "2:2", "2:3", "2:4", "3:1", "3:2", "3:3", "4:1", "4:2", "4:3"]
    return {
        "team": {"name": team},
        "formation": "4-3-3",
        "coach": {"name": f"Coach {team}"},
        "startXI": [
            {"player": {"name": f"{prefix} {i}", "grid": grid, "pos": "G" if i == 0 else "D" if i < 5 else "M" if i < 8 else "F"}}
            for i, grid in enumerate(grids)
        ],
    }


class BatchFootball(ApiFootballClient):
    def __init__(self, status="NS", goals=None, publish_lineups=True):
        super().__init__(api_key="test")
        self.calls = []
        self.status = status
        self.publish_lineups = publish_lineups
        self.goals = goals or {77: {"home": None, "away": None}, 78: {"home": None, "away": None}}

    def _row(self, fixture_id, home, away, *, detailed=False):
        row = {
            "fixture": {
                "id": fixture_id,
                "date": "2026-08-26T20:00:00+02:00",
                "status": {"short": self.status},
            },
            "teams": {"home": {"name": home}, "away": {"name": away}},
            "goals": self.goals[fixture_id],
        }
        if detailed and self.publish_lineups:
            prefixes = ("RM", "BET") if fixture_id == 77 else ("BAR", "VAL")
            row["lineups"] = [_lineup(home, prefixes[0]), _lineup(away, prefixes[1])]
        return row

    def _get(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "fixtures" and "date" in params:
            return {"response": [
                self._row(77, "Real Madrid", "Real Betis"),
                self._row(78, "Barcelona", "Valencia"),
            ]}
        if path == "fixtures" and "ids" in params:
            ids = [int(value) for value in params["ids"].split("-") if value]
            rows = {
                77: self._row(77, "Real Madrid", "Real Betis", detailed=True),
                78: self._row(78, "Barcelona", "Valencia", detailed=True),
            }
            return {"response": [rows[value] for value in ids]}
        if path == "injuries" and "ids" in params:
            ids = [int(value) for value in params["ids"].split("-") if value]
            return {"response": [
                {
                    "fixture": {"id": fixture_id},
                    "team": {"name": "Real Madrid" if fixture_id == 77 else "Barcelona"},
                    "player": {"name": f"Baja {fixture_id}", "type": "Injury", "reason": "Muscle injury"},
                }
                for fixture_id in ids
            ]}
        raise AssertionError(f"Llamada no batch inesperada: {path} {params}")


def _match(match_id, home, away):
    return {
        "id": match_id,
        "home": home,
        "away": away,
        "league": "LaLiga",
        "date": "2026-08-26",
        "kickoff": "2026-08-26T20:00:00+02:00",
        "status": "SCHEDULED",
        "finished": False,
        "engine": "dixon-coles",
        "probs": [50, 27, 23],
        "xg": [1.4, 1.0],
        "markets": {"marcador": "1-0"},
        "alineacion": {
            "local": [f"{home} P{i}" for i in range(11)],
            "visitante": [f"{away} P{i}" for i in range(11)],
            "posiciones_local": ["MC"] * 11,
            "posiciones_visitante": ["MC"] * 11,
            "status": "estimado",
            "provider": "Motor estadístico local",
            "clave_local": [],
            "clave_visitante": [],
        },
    }


def _feed():
    return {
        "schema_version": 7,
        "generated_at": "2026-08-26T18:00:00+02:00",
        "season": 2026,
        "counts": {"total": 2, "jugados": 0, "proximos": 2, "con_prediccion": 2},
        "matches": [
            _match("m-1", "Real Madrid", "Real Betis"),
            _match("m-2", "Barcelona", "Valencia"),
        ],
    }


def test_t60_dos_partidos_consumen_una_llamada_por_endpoint_batch():
    feed = _feed()
    client = BatchFootball()

    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=NoWeather(),
        football_client=client,
    )

    assert changed is True
    assert client.calls == [
        ("fixtures", {"date": "2026-08-26"}),
        ("fixtures", {"ids": "77-78"}),
        ("injuries", {"ids": "77-78"}),
    ]
    assert stats["lineup"] == 2
    assert stats["absences"] == 2
    assert stats["quota_mode"] == "normal"
    assert [match["api_football_fixture_id"] for match in feed["matches"]] == [77, 78]
    assert all(match["alineacion"]["status"] == "confirmado" for match in feed["matches"])
    assert feed["matches"][0]["alineacion"]["local"][0] == "RM 0"


def test_lineup_no_publicado_se_reintenta_a_los_cinco_minutos_en_modo_normal():
    feed = _feed()
    first = BatchFootball(publish_lineups=False)
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T18:55:00+02:00"),
        weather_client=NoWeather(),
        football_client=first,
    )
    assert feed["matches"][0]["operational_checks"]["lineup_check_result"] == "not_published"

    retry = BatchFootball(publish_lineups=False)
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=NoWeather(),
        football_client=retry,
    )
    # El XI sí se reintenta; injuries no, porque la ventana T−60 ya se consultó
    # cinco minutos antes y tiene cooldown independiente.
    assert retry.calls == [("fixtures", {"ids": "77-78"})]
    assert feed["matches"][0]["operational_checks"]["lineup_checked_at"] == "2026-08-26T19:00:00+02:00"


def test_live_reutiliza_fixture_ids_y_refresca_cada_diez_minutos_aprox():
    feed = _feed()
    first = BatchFootball()
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=NoWeather(),
        football_client=first,
    )

    live = BatchFootball(
        status="1H",
        goals={77: {"home": 1, "away": 0}, 78: {"home": 0, "away": 1}},
    )
    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T20:20:00+02:00"),
        weather_client=NoWeather(),
        football_client=live,
    )

    assert changed is True
    assert live.calls == [("fixtures", {"ids": "77-78"})]
    assert stats["fixture"] == 2
    assert feed["matches"][0]["live_score"] == [1, 0]
    assert feed["matches"][1]["live_score"] == [0, 1]

    ten_minutes_later = BatchFootball(status="1H")
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T20:30:00+02:00"),
        weather_client=NoWeather(),
        football_client=ten_minutes_later,
    )
    assert ten_minutes_later.calls == [("fixtures", {"ids": "77-78"})]
    assert feed["matches"][0]["operational_checks"]["fixture_checked_at"] == "2026-08-26T20:30:00+02:00"


def test_t120_no_repite_injuries_que_el_proveedor_actualiza_mas_lento():
    feed = _feed()
    client = BatchFootball()

    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T18:00:00+02:00"),
        weather_client=NoWeather(),
        football_client=client,
    )

    assert client.calls == []


def test_cuota_baja_reduce_frecuencia_de_lineup():
    feed = _feed()
    feed["source_health"] = {"api_football": {"daily_remaining": 30}}
    # T-60: primera consulta permitida.
    first = BatchFootball(publish_lineups=False)
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=NoWeather(),
        football_client=first,
    )
    assert feed["matches"][0]["operational_checks"]["lineup_checked_at"] == "2026-08-26T19:00:00+02:00"

    # Cinco minutos después, modo low exige ~9 min y no vuelve a gastar fixtures.
    retry = BatchFootball(publish_lineups=False)
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:05:00+02:00"),
        weather_client=NoWeather(),
        football_client=retry,
    )
    assert retry.calls == []
