from datetime import datetime
from zoneinfo import ZoneInfo

from futbol_pred.prediction_snapshots import apply_prediction_snapshots

MADRID = ZoneInfo("Europe/Madrid")


def _match(probs=None):
    return {
        "id": "m1",
        "date": "2026-08-24",
        "kickoff": "2026-08-24T21:00:00+02:00",
        "league": "LaLiga",
        "home": "A",
        "away": "B",
        "finished": False,
        "engine": "ensemble",
        "probs": probs or [50, 30, 20],
        "xg": [1.5, 0.8],
        "markets": {"marcador": "1-0"},
        "model_meta": {"version": "edge-2.0"},
    }


def test_primera_ejecucion_crea_snapshot_inmutable():
    matches = [_match()]
    apply_prediction_snapshots(matches, [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    assert matches[0]["prediction_snapshot"]["window"] == "initial"
    assert matches[0]["prediction_snapshot"]["probs"] == [50, 30, 20]


def test_fuera_de_ventana_conserva_prediccion_anterior():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([80, 10, 10])
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 8, tzinfo=MADRID))
    assert current["probs"] == [50, 30, 20]
    assert len(current["prediction_history"]) == 1


def test_tendencias_no_se_congela_con_el_snapshot():
    """tendencias es un indicador derivado (↑/→/↓ del estilo), no la apuesta:
    debe recalcularse en cada ejecución en vez de quedar congelado con el
    snapshot prepartido. Congelarlo dejaba fuera de producción las mejoras del
    modelo de tendencias (referencia de liga + umbral por métrica)."""
    old = _match([50, 30, 20])
    old["tendencias"] = {"goals": {"dir": "flat", "pct": 0}}
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([80, 10, 10])
    current["tendencias"] = {"goals": {"dir": "up", "pct": 12}}  # recalculado, más fresco
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 8, tzinfo=MADRID))
    assert current["probs"] == [50, 30, 20]  # la predicción SÍ se congela
    assert current["tendencias"] == {"goals": {"dir": "up", "pct": 12}}  # tendencias NO
    assert "tendencias" not in current["prediction_snapshot"]


def test_ventana_de_las_diez_crea_revision_del_partido_del_dia():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([55, 27, 18])
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 10, 15, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "10:15"
    assert current["probs"] == [55, 27, 18]
    assert len(current["prediction_history"]) == 2


def test_segundo_cron_de_la_misma_hora_no_reescribe_snapshot():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    ten = _match([55, 27, 18])
    apply_prediction_snapshots([ten], [old], datetime(2026, 8, 24, 10, 15, tzinfo=MADRID))
    repeated = _match([80, 10, 10])
    apply_prediction_snapshots([repeated], [ten], datetime(2026, 8, 24, 10, 30, tzinfo=MADRID))
    assert repeated["probs"] == [55, 27, 18]
    assert len(repeated["prediction_history"]) == 2


def test_captura_t24_t12_y_t6_solo_una_vez():
    initial = _match([48, 31, 21])
    apply_prediction_snapshots([initial], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))

    t24 = _match([49, 31, 20])
    apply_prediction_snapshots([t24], [initial], datetime(2026, 8, 23, 21, tzinfo=MADRID))
    assert t24["prediction_snapshot"]["window"] == "T-24h"

    repeated = _match([70, 20, 10])
    apply_prediction_snapshots([repeated], [t24], datetime(2026, 8, 23, 21, 15, tzinfo=MADRID))
    assert repeated["prediction_snapshot"]["window"] == "T-24h"
    assert repeated["probs"] == [49, 31, 20]

    t12 = _match([51, 30, 19])
    apply_prediction_snapshots([t12], [repeated], datetime(2026, 8, 24, 9, tzinfo=MADRID))
    assert t12["prediction_snapshot"]["window"] == "T-12h"

    t6 = _match([53, 29, 18])
    apply_prediction_snapshots([t6], [t12], datetime(2026, 8, 24, 15, tzinfo=MADRID))
    assert t6["prediction_snapshot"]["window"] == "T-6h"
    assert [row["window"] for row in t6["prediction_history"]] == ["initial", "T-24h", "T-12h", "T-6h"]


def test_once_oficial_crea_snapshot_evento_y_archiva_el_once():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))

    official = _match([52, 29, 19])
    official["alineacion"] = {
        "status": "confirmado",
        "provider": "API-Football",
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "source_updated_at": "2026-08-24T19:45:00+02:00",
        "official_poll_window": "T-60",
    }
    official["official_context"] = {"referee": "Árbitro Real"}
    official["lineup_impact"] = {
        "evidence": "alta",
        "confidence_penalty_pp": 3,
        "probability_adjustment": "not_applied",
    }
    apply_prediction_snapshots([official], [old], datetime(2026, 8, 24, 19, 45, tzinfo=MADRID))

    snapshot = official["prediction_snapshot"]
    assert snapshot["window"] == "final_T-60_official"
    assert snapshot["alineacion"]["status"] == "confirmado"
    assert snapshot["official_context"]["referee"] == "Árbitro Real"
    assert snapshot["lineup_impact"]["probability_adjustment"] == "not_applied"

    repeated = _match([80, 10, 10])
    repeated["alineacion"] = official["alineacion"]
    apply_prediction_snapshots([repeated], [official], datetime(2026, 8, 24, 20, tzinfo=MADRID))
    assert repeated["prediction_snapshot"]["window"] == "final_T-60_official"
    assert sum(row.get("window") == "final_T-60_official" for row in repeated["prediction_history"]) == 1


def test_no_captura_once_oficial_despues_del_inicio():
    match = _match([60, 25, 15])
    match["alineacion"] = {"status": "confirmado", "local": ["A"] * 11, "visitante": ["B"] * 11}
    apply_prediction_snapshots([match], [], datetime(2026, 8, 24, 21, 5, tzinfo=MADRID))
    assert "prediction_snapshot" not in match
    assert match["prediction_unavailable_reason"] == "sin_snapshot_prepartido"


def test_clima_queda_archivado_en_la_revision_y_no_se_reescribe():
    old = _match([50, 30, 20])
    old["weather"] = {"temperature_c": 20, "source_updated_at": "2026-08-23T15:00:00+02:00"}
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))

    ten = _match([55, 27, 18])
    ten["weather"] = {"temperature_c": 35, "source_updated_at": "2026-08-24T10:15:00+02:00"}
    apply_prediction_snapshots([ten], [old], datetime(2026, 8, 24, 10, 15, tzinfo=MADRID))
    assert ten["prediction_snapshot"]["weather"]["temperature_c"] == 35

    repeated = _match([80, 10, 10])
    repeated["weather"] = {"temperature_c": 99, "source_updated_at": "2026-08-24T10:30:00+02:00"}
    apply_prediction_snapshots([repeated], [ten], datetime(2026, 8, 24, 10, 30, tzinfo=MADRID))
    assert repeated["prediction_snapshot"]["weather"]["temperature_c"] == 35
    assert repeated["weather"]["temperature_c"] == 35


def test_fase_restore_no_captura_hasta_que_el_contexto_este_completo():
    now = datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)
    match = _match([51, 28, 21])
    match["id"] = "m-context"
    apply_prediction_snapshots([match], [], now, capture=False)
    assert "prediction_snapshot" not in match
    match["lineup_impact"] = {"evidence": "alta", "confidence_penalty_pp": 0}
    match["state_simulation"] = {"status": "scenario_only_not_in_1x2"}
    apply_prediction_snapshots([match], [], now)
    assert match["prediction_snapshot"]["lineup_impact"]["evidence"] == "alta"
    assert match["prediction_snapshot"]["state_simulation"]["status"].startswith("scenario")


def test_partido_terminado_no_captura_resultado_conocido():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([99, 1, 0])
    current.update({"finished": True, "result": [4, 0], "engine": "resultado-real"})
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 23, tzinfo=MADRID))
    assert current["prediction_snapshot"]["probs"] == [50, 30, 20]
    assert current["probs"] == [50, 30, 20]
    assert current["engine"] == "resultado-real"


def test_historico_sin_snapshot_elimina_prediccion_reconstruida():
    current = _match([99, 1, 0])
    current.update({"finished": True, "result": [4, 0], "engine": "resultado-real"})
    apply_prediction_snapshots([current], [], datetime(2026, 8, 24, 23, tzinfo=MADRID))
    assert "probs" not in current
    assert current["prediction_unavailable_reason"] == "sin_snapshot_prepartido"


def test_t3_es_prefinal_solo_con_once_probable_completo_refrescado():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([54, 28, 18])
    current["alineacion"] = {
        "status": "probable", "phase": "pre_final",
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "media_sources": [{"source": "AS", "title": "Once probable"}],
    }
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 18, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "pre_final_T-3h"
    assert len(current["prediction_snapshot"]["alineacion"]["local"]) == 11


def test_t3_sin_once_completo_no_finge_prefinal():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([54, 28, 18])
    current["alineacion"] = {"status": "probable", "phase": "pre_final", "local": ["L"] * 9, "visitante": ["V"] * 11}
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 18, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "T-3h"


def test_final_t30_si_el_once_oficial_no_estaba_disponible_a_t60():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    final = _match([56, 27, 17])
    final["alineacion"] = {
        "status": "confirmado", "phase": "final", "official_poll_window": "T-30",
        "local": [f"L{i}" for i in range(11)], "visitante": [f"V{i}" for i in range(11)],
    }
    apply_prediction_snapshots([final], [old], datetime(2026, 8, 24, 20, 30, tzinfo=MADRID))
    assert final["prediction_snapshot"]["window"] == "final_T-30_official"


def test_final_t60_no_se_reemplaza_por_una_segunda_final_t30():
    first = _match([55, 28, 17])
    first["alineacion"] = {
        "status": "confirmado", "phase": "final", "official_poll_window": "T-60",
        "local": [f"L{i}" for i in range(11)], "visitante": [f"V{i}" for i in range(11)],
    }
    apply_prediction_snapshots([first], [], datetime(2026, 8, 24, 20, tzinfo=MADRID))
    second = _match([70, 20, 10])
    second["alineacion"] = {**first["alineacion"], "official_poll_window": "T-30"}
    apply_prediction_snapshots([second], [first], datetime(2026, 8, 24, 20, 30, tzinfo=MADRID))
    assert second["prediction_snapshot"]["window"] == "final_T-60_official"
    assert second["probs"] == [55, 28, 17]
