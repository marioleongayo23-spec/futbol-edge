from copy import deepcopy
from datetime import datetime

from futbol_pred.matchday_prediction_refresh import refresh_payload


def _match():
    return {
        "id": "m1", "home": "Local", "away": "Visitante", "league": "LaLiga",
        "kickoff": "2026-08-26T21:00:00+02:00", "finished": False,
        "model_probs": [55.0, 27.0, 18.0], "probs": [54, 27, 19],
        "xg": [1.8, 1.0],
        "markets": {"over_2_5": .53, "over_1_5": .76, "over_3_5": .29, "btts": .48},
        "stats": {
            "goals": {"home": 1.8, "away": 1.0, "total": 2.8},
            "shots": {"home": 14, "away": 9, "total": 23},
            "sot": {"home": 5, "away": 3, "total": 8},
            "fouls": {"home": 12, "away": 13, "total": 25},
            "yellows": {"home": 2.1, "away": 2.4, "total": 4.5},
        },
        "weather": {
            "source": "Open-Meteo", "forecast_for": "2026-08-26T21:00:00",
            "source_updated_at": "2026-08-26T18:00:00+02:00",
            "temperature_c": 22, "apparent_temperature_c": 22,
            "humidity_pct": 65, "wind_kmh": 32, "precipitation_mm": 2.0,
            "precipitation_probability_pct": 85, "weather_code": 61,
            "heat_stress": {"level": "bajo"},
        },
        "odds": {
            "1x2": {"odds": {"1": 1.90, "X": 3.60, "2": 4.20}},
            "ou25": {"odds": {"over": 1.95, "under": 1.90}},
        },
        "value": [
            {"market": "1x2", "selection": "1", "odds": 1.9, "modelProb": .54, "edge": .026},
            {"market": "ou25", "selection": "over", "odds": 1.95, "modelProb": .53, "edge": .0335},
        ],
        "market_calibration": {"model_weight": .7, "market_weight": .3, "temperature": 1.0},
        "model_meta": {"components": {"dixon_coles": {"1": .55}, "elo": {"1": .52}}},
        "tendencias": {"shots": {"dir": "flat"}},
        "tactical_matchup": {"reliability": "media"},
        "alineacion": {
            "status": "estimado", "local": [f"L{i}" for i in range(11)],
            "visitante": [f"V{i}" for i in range(11)],
            "clave_local": [], "clave_visitante": [],
            "disponibilidad_local": [], "disponibilidad_visitante": [],
        },
        "prediction_confidence": {"score": 70, "model_disagreement_pp": 3.0, "evidence": {}},
        "recommendation": {"decision": "eligible", "reasons": []},
    }


def _feed(match=None):
    return {"schema_version": 7, "generated_at": "2026-08-26T17:55:00+02:00", "matches": [match or _match()]}


def test_clima_nuevo_recalcula_xg_mercados_y_value_sin_tocar_model_probs():
    feed = _feed()
    match = feed["matches"][0]
    pure = list(match["model_probs"])
    old_xg = list(match["xg"])

    changed, stats = refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:05:00+02:00"))

    assert changed is True
    assert stats["weather_recalculated"] == 1
    assert match["model_probs"] == pure
    assert match["xg"][0] < old_xg[0]
    assert match["markets"]["over_2_5"] < .53
    ou = next(row for row in match["value"] if row["market"] == "ou25" and row["selection"] == "over")
    assert ou["weather_adjusted"] is True
    assert ou["prediction_refreshed_at"] == "2026-08-26T18:05:00+02:00"
    assert match["weather_adjustment"]["weather_forecast_for"] == "2026-08-26T21:00:00"


def test_segundo_refresh_no_acumula_el_multiplicador_del_clima():
    feed = _feed()
    refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:05:00+02:00"))
    first_xg = list(feed["matches"][0]["xg"])
    first_shots = deepcopy(feed["matches"][0]["stats"]["shots"])

    refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:10:00+02:00"))

    assert feed["matches"][0]["xg"] == first_xg
    assert feed["matches"][0]["stats"]["shots"] == first_shots


def test_si_pipeline_reconstruye_base_se_reaplica_sin_dividir_dos_veces():
    feed = _feed()
    refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:05:00+02:00"))
    adjusted = deepcopy(feed["matches"][0]["weather_adjustment"])

    rebuilt = _match()
    rebuilt["weather_adjustment"] = adjusted
    feed2 = _feed(rebuilt)
    refresh_payload(feed2, now=datetime.fromisoformat("2026-08-26T18:10:00+02:00"))

    assert feed2["matches"][0]["weather_adjustment"]["xg"]["before"] == [1.8, 1.0]
    assert feed2["matches"][0]["stats"]["shots"]["home"] == feed["matches"][0]["stats"]["shots"]["home"]


def test_xi_oficial_actualiza_confianza_y_completitud_en_la_misma_pasada():
    match = _match()
    previous_score = match["prediction_confidence"]["score"]
    match["alineacion"]["status"] = "confirmado"
    match["alineacion"]["disponibilidad_local"] = [{
        "jugador": "L9", "estado": "lesión", "official": True, "detalle": "Muscle injury"
    }]
    feed = _feed(match)

    _, stats = refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:05:00+02:00"))

    conf = match["prediction_confidence"]
    assert stats["confidence_recalculated"] == 1
    assert conf["evidence"]["official_lineup"] is True
    assert match["lineup_impact"]["home"]["official_absences"] == 1
    assert match["lineup_impact"]["status"] == "confirmado"
    assert conf["refreshed_at"] == "2026-08-26T18:05:00+02:00"
    assert match["recommendation"]["refreshed_at"] == "2026-08-26T18:05:00+02:00"
    assert conf["score"] != previous_score


def test_solo_actua_en_partidos_del_mismo_dia():
    match = _match()
    match["kickoff"] = "2026-08-27T21:00:00+02:00"
    feed = _feed(match)

    changed, stats = refresh_payload(feed, now=datetime.fromisoformat("2026-08-26T18:05:00+02:00"))

    assert changed is False
    assert stats["matches"] == 0
    assert "prediction_live_refresh" not in match
