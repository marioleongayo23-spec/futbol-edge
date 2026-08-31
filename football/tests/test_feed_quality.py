"""Contrato, last-known-good y escritura atómica del feed."""

from copy import deepcopy
import json

from futbol_pred.feed_quality import evaluate_feed, preserve_last_known_good, write_feed_safely


def _feed(n=20):
    """Feed sintético con reloj fijo para que los tests no caduquen al día siguiente."""
    matches = [
        {
            "id": f"src-{i}",
            "home": f"Local {i}",
            "away": f"Visitante {i}",
            "league": "LaLiga",
            "date": "2026-08-25",
            "kickoff": f"2026-08-25T{(i % 20):02d}:00:00+02:00",
            "status": "SCHEDULED",
            "finished": False,
            "engine": "dixon-coles",
            "probs": [50, 28, 22],
            "xg": [1.5, 0.9],
            "markets": {"marcador": "1-0"},
        }
        for i in range(n)
    ]
    return {
        "schema_version": 3,
        # 00:00 UTC = 02:00 en Madrid. Mantiene la mayoría de fixtures dentro
        # de la ventana en la que schema >=4 exige previa y once, sin depender
        # de datetime.now().
        "generated_at": "2026-08-25T00:00:00+00:00",
        "season": 2026,
        "counts": {"total": n, "jugados": 0, "proximos": n, "con_prediccion": n},
        "matches": matches,
    }


def test_feed_valido_sin_blanks():
    report = evaluate_feed(_feed())
    assert report["valid"] is True
    assert report["metrics"]["blank_matches"] == 0


def test_preserva_preview_y_prediccion_lkg():
    previous = _feed()
    previous["matches"][0]["preview"] = " ".join(["texto"] * 100)
    previous["matches"][0]["preview_meta"] = {"provider": "Gemini"}
    candidate = deepcopy(previous)
    for field in ("preview", "preview_meta", "probs", "xg", "markets"):
        candidate["matches"][0].pop(field, None)
    preserve_last_known_good(candidate, previous)
    assert candidate["matches"][0]["preview_meta"]["provider"] == "Gemini"
    assert candidate["matches"][0]["probs"] == [50, 28, 22]


def test_guard_rechaza_caida_masiva_y_no_pisa_archivo(tmp_path):
    path = tmp_path / "dashboard.json"
    previous = _feed()
    path.write_text(json.dumps(previous), encoding="utf-8")
    candidate = _feed(10)
    ok, report = write_feed_safely(path, candidate, previous=previous)
    assert ok is False
    assert any(issue.startswith("muy_pocos_partidos") for issue in report["issues"])
    assert len(json.loads(path.read_text(encoding="utf-8"))["matches"]) == 20


def test_escritura_segura_anade_informe(tmp_path):
    path = tmp_path / "dashboard.json"
    ok, report = write_feed_safely(path, _feed())
    assert ok is True and report["valid"] is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["feed_quality"]["valid"] is True


def test_schema4_bloquea_proximo_sin_previa():
    feed = _feed()
    feed["schema_version"] = 4
    report = evaluate_feed(feed)
    assert report["valid"] is False
    assert any(issue.startswith("preview_vacia_proximo") for issue in report["issues"])


def test_once_vacio_proximo_avisa_pero_no_bloquea_publicacion():
    """Un próximo NUEVO sin once no puede congelar TODO el feed (previas,
    predicciones y la IA ya generada del resto). Se avisa, pero se publica."""

    feed = _feed()
    feed["schema_version"] = 4
    # Todas las próximas tienen previa (el motor local siempre la rellena) pero
    # ninguna tiene once: antes invalidaba el feed entero.
    for match in feed["matches"]:
        match["preview"] = " ".join(["texto"] * 100)
        match["preview_meta"] = {"provider": "Motor estadístico local"}
    report = evaluate_feed(feed)
    assert report["valid"] is True
    assert not report["issues"]
    assert any(w.startswith("once_vacio_proximo") for w in report["warnings"])
    assert report["metrics"]["empty_lineups_upcoming"] == len(feed["matches"])


def test_perdida_de_once_ya_publicado_sigue_bloqueando():
    """La red de seguridad real: perder un once que el feed anterior YA tenía
    se sigue bloqueando como regresión, aunque once_vacio_proximo sea aviso."""

    previous = _feed()
    previous["matches"][0]["alineacion"] = {
        "local": [f"J{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "status": "probable",
    }
    candidate = deepcopy(previous)
    for match in candidate["matches"]:
        match["preview"] = " ".join(["texto"] * 100)
        match["preview_meta"] = {"provider": "Motor estadístico local"}
    candidate["matches"][0].pop("alineacion")  # se pierde un once ya publicado
    report = evaluate_feed(candidate, previous=previous)
    assert report["valid"] is False
    assert any(issue.startswith("regresion_alineacion") for issue in report["issues"])


def test_schema5_exige_snapshot_prepartido():
    feed = _feed()
    feed["schema_version"] = 5
    report = evaluate_feed(feed)
    assert report["valid"] is False
    assert any(issue.startswith("snapshot_prediccion_ausente") for issue in report["issues"])


def test_schema5_no_restaura_prediccion_retroactiva_de_terminado():
    previous = _feed()
    previous["matches"][0].update({"finished": True, "status": "FINISHED", "result": [2, 0]})
    candidate = deepcopy(previous)
    candidate["schema_version"] = 5
    candidate["matches"][0].pop("probs")
    candidate["matches"][0]["prediction_unavailable_reason"] = "sin_snapshot_prepartido"
    preserve_last_known_good(candidate, previous)
    assert "probs" not in candidate["matches"][0]


def test_no_restaura_metricas_historicas_sin_snapshots():
    previous = _feed()
    previous["accuracy"] = {"n_partidos": 20, "pct_1x2": 65}
    previous["performance"] = {"overall": {"n": 20, "roi": 12}}
    candidate = deepcopy(previous)
    candidate["accuracy"] = None
    candidate["performance"] = None
    preserve_last_known_good(candidate, previous)
    assert candidate["accuracy"] is None
    assert candidate["performance"] is None


def test_rechaza_accuracy_sin_snapshot_prepartido():
    feed = _feed()
    feed["accuracy"] = {"n_partidos": 20, "pct_1x2": 65}
    report = evaluate_feed(feed)
    assert report["valid"] is False
    assert "accuracy_sin_evidencia:20->0" in report["issues"]