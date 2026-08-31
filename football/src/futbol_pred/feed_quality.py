"""Contrato de calidad y protección last-known-good del feed público."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile

_TOP_LEVEL_LKG = (
    "quiniela", "players", "model", "market_calibration", "historical_seed",
)
_MATCH_LKG = (
    "probs",
    "model_probs",
    "model_meta",
    "market_calibration",
    "xg",
    "markets",
    "stats",
    "tendencias",
    "h2h",
    "odds",
    "value",
    "preview",
    "preview_meta",
    "alineacion",
    "ai_attempts",
    "prediction_snapshot",
    "prediction_history",
    "venue_meta",
    "weather",
    "weather_actual",
    "weather_adjustment",
    "closing_odds",
    "extended_market",
    "extended_value",
    "tactical_matchup",
    "prediction_confidence",
    "prediction_factors",
    "recommendation",
    "score_distribution",
    "official_context",
)
_REQUIRED_MATCH = ("id", "home", "away", "league", "kickoff", "status")


def load_feed(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _missing(value) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    return isinstance(value, str) and value.startswith("pendiente_")


def match_identity(match: dict) -> str:
    """Identidad estable aunque una API cambie el id o la hora unos minutos."""

    date = str(match.get("date") or match.get("kickoff") or "")[:10]
    parts = (
        match.get("league"),
        match.get("home"),
        match.get("away"),
        date,
    )
    return "|".join(str(part or "").strip().casefold() for part in parts)


def preserve_last_known_good(candidate: dict, previous: dict | None) -> dict:
    """Rellena huecos/regresiones del candidato con el último feed publicado."""

    if not previous:
        return candidate
    for field in _TOP_LEVEL_LKG:
        if _missing(candidate.get(field)) and not _missing(previous.get(field)):
            candidate[field] = deepcopy(previous[field])

    old_by_id = {match.get("id"): match for match in previous.get("matches", []) if match.get("id")}
    old_by_key = {match_identity(match): match for match in previous.get("matches", [])}
    for match in candidate.get("matches", []):
        old = old_by_id.get(match.get("id")) or old_by_key.get(match_identity(match))
        if not old:
            continue
        restored_fields = set()
        for field in _MATCH_LKG:
            if (
                candidate.get("schema_version", 0) >= 5
                and match.get("prediction_unavailable_reason") == "sin_snapshot_prepartido"
                and not match.get("prediction_snapshot")
                and field in {"probs", "model_probs", "model_meta", "market_calibration", "xg", "markets", "stats", "tendencias", "odds", "value"}
            ):
                continue
            if _missing(match.get(field)) and not _missing(old.get(field)):
                match[field] = deepcopy(old[field])
                restored_fields.add(field)
        if match.get("preview") and not (match.get("preview_meta") or {}).get("provider"):
            match["preview_meta"] = {"provider": "IA (caché anterior)", "legacy": True}
        if match.get("alineacion") and not match["alineacion"].get("provider"):
            match["alineacion"]["provider"] = "IA (caché anterior)"
        if "alineacion" in restored_fields and match.get("alineacion"):
            match["alineacion"]["cache_status"] = "recuperado_de_cache"
        if "preview" in restored_fields and match.get("preview_meta"):
            match["preview_meta"]["cache_status"] = "recuperado_de_cache"
        if match.get("probs") and match.get("engine") in {None, "calendar-only", "datos-insuficientes"}:
            if old.get("engine") in {"dixon-coles", "ensemble", "residual", "resultado-real"}:
                match["engine"] = old["engine"]
    return candidate


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _has_pre_match_snapshot(match: dict) -> bool:
    """Comprueba la evidencia que permite puntuar una predicción histórica."""

    try:
        kickoff = datetime.fromisoformat(str(match.get("kickoff")))
    except (TypeError, ValueError):
        return False
    snapshots = list(match.get("prediction_history") or [])
    if isinstance(match.get("prediction_snapshot"), dict):
        snapshots.append(match["prediction_snapshot"])
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("probs"), list):
            continue
        try:
            captured = datetime.fromisoformat(str(snapshot.get("generated_at")))
            if captured < kickoff:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _ai_complete(match: dict, issues: list[str], schema_version: int = 5) -> None:
    preview = match.get("preview")
    if preview:
        if len(str(preview).split()) < 90:
            issues.append(f"preview_demasiado_corta:{match.get('id')}")
        meta = match.get("preview_meta") or {}
        if not meta.get("provider"):
            issues.append(f"preview_sin_provider:{match.get('id')}")

    lineup = match.get("alineacion")
    if not lineup:
        return
    if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11:
        issues.append(f"once_incompleto:{match.get('id')}")
    if (
        len(lineup.get("posiciones_local") or []) != 11
        or len(lineup.get("posiciones_visitante") or []) != 11
        or not lineup.get("formacion_local")
        or not lineup.get("formacion_visitante")
    ):
        issues.append(f"posiciones_incompletas:{match.get('id')}")
    if not lineup.get("provider"):
        issues.append(f"once_sin_provider:{match.get('id')}")
    rows = (lineup.get("clave_local") or []) + (lineup.get("clave_visitante") or [])
    if rows:
        required_props = {"jugador", "g", "a", "r", "rp", "fc", "fr", "t", "min", "tit"}
        for row in rows:
            if not isinstance(row, dict) or not required_props.issubset(row):
                issues.append(f"props_sin_campos_ampliados:{match.get('id')}")
                break
            try:
                sample = float(row.get("sample_minutes") or 0)
            except (TypeError, ValueError):
                sample = 0
            source = str(row.get("source") or "")
            evidence_type = str(row.get("evidence_type") or "")
            prediction_kind = str(row.get("prediction_kind") or "")
            real_projection = source.startswith("API-Football") and sample > 0
            explicit_model_estimate = (
                source.startswith("Modelo")
                and sample <= 0
                and evidence_type == "model_estimate"
                and bool(prediction_kind)
            )
            if not (real_projection or explicit_model_estimate):
                issues.append(f"props_sin_fuente_trazable:{match.get('id')}")
                break
    if schema_version >= 6 and lineup.get("status") not in {"confirmado", "probable", "estimado"}:
        issues.append(f"once_sin_estado:{match.get('id')}")


def evaluate_feed(candidate: dict, previous: dict | None = None) -> dict:
    """Devuelve un informe auditable y marca cualquier regresión bloqueante."""

    issues: list[str] = []
    matches = candidate.get("matches")
    if not isinstance(matches, list):
        matches = []
        issues.append("matches_no_es_lista")
    if len(matches) < 20:
        issues.append(f"muy_pocos_partidos:{len(matches)}")

    ids = set()
    blank_matches = 0
    prediction_count = preview_count = lineup_count = required_ai_count = 0
    leagues = set()
    try:
        generated_at = datetime.fromisoformat(str(candidate.get("generated_at")))
    except (TypeError, ValueError):
        generated_at = None
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            issues.append(f"partido_no_objeto:{index}")
            continue
        missing = [field for field in _REQUIRED_MATCH if _missing(match.get(field))]
        if missing:
            blank_matches += 1
            issues.append(f"campos_vacios:{index}:{','.join(missing)}")
        match_id = match.get("id")
        if match_id in ids:
            issues.append(f"id_duplicado:{match_id}")
        ids.add(match_id)
        leagues.add(match.get("league"))
        try:
            datetime.fromisoformat(str(match.get("kickoff")))
        except (TypeError, ValueError):
            issues.append(f"kickoff_invalido:{match_id}")

        probs = match.get("probs")
        if probs is not None:
            prediction_count += 1
            if not (isinstance(probs, list) and len(probs) == 3 and all(_finite(x) for x in probs)):
                issues.append(f"probs_invalidas:{match_id}")
            elif not 98 <= sum(probs) <= 102:
                issues.append(f"probs_no_suman_100:{match_id}")
        if candidate.get("schema_version", 0) >= 5 and probs is not None:
            snapshot = match.get("prediction_snapshot")
            if not isinstance(snapshot, dict):
                issues.append(f"snapshot_prediccion_ausente:{match_id}")
            else:
                try:
                    captured = datetime.fromisoformat(str(snapshot.get("generated_at")))
                    kickoff = datetime.fromisoformat(str(match.get("kickoff")))
                    if captured >= kickoff:
                        issues.append(f"snapshot_posterior_kickoff:{match_id}")
                except (TypeError, ValueError):
                    issues.append(f"snapshot_fecha_invalida:{match_id}")
        xg = match.get("xg")
        if xg is not None and not (
            isinstance(xg, list) and len(xg) == 2 and all(_finite(x) and 0 <= x <= 6 for x in xg)
        ):
            issues.append(f"xg_invalido:{match_id}")
        preview_count += int(bool(match.get("preview")))
        lineup_count += int(bool(match.get("alineacion")))
        _ai_complete(match, issues, int(candidate.get("schema_version") or 0))
        if candidate.get("schema_version", 0) >= 4 and generated_at and probs and not match.get("finished"):
            try:
                delta = datetime.fromisoformat(str(match.get("kickoff"))) - generated_at
            except (TypeError, ValueError):
                delta = None
            if delta is not None and delta.total_seconds() >= -3 * 3600:
                required_ai_count += 1
                if not match.get("preview"):
                    issues.append(f"preview_vacia_proximo:{match_id}")
                if not match.get("alineacion"):
                    issues.append(f"once_vacio_proximo:{match_id}")

    counts = candidate.get("counts") or {}
    if counts.get("total") != len(matches):
        issues.append("counts_total_inconsistente")

    try:
        datetime.fromisoformat(str(candidate.get("generated_at")))
    except (TypeError, ValueError):
        issues.append("generated_at_invalido")

    evaluable = sum(
        1 for match in matches
        if isinstance(match, dict)
        and match.get("finished")
        and isinstance(match.get("result"), list)
        and _has_pre_match_snapshot(match)
    )
    accuracy = candidate.get("accuracy")
    if accuracy is not None:
        reported = accuracy.get("n_partidos") if isinstance(accuracy, dict) else None
        if not isinstance(reported, int) or reported < 1 or reported > evaluable:
            issues.append(f"accuracy_sin_evidencia:{reported}->{evaluable}")
    performance = candidate.get("performance")
    if performance is not None and evaluable == 0:
        issues.append("performance_sin_evidencia")

    if previous and previous.get("season") == candidate.get("season"):
        old_matches = previous.get("matches") or []
        if old_matches and len(matches) < max(20, math.floor(len(old_matches) * 0.85)):
            issues.append(f"regresion_total:{len(old_matches)}->{len(matches)}")
        old_leagues = {match.get("league") for match in old_matches if match.get("league")}
        if not old_leagues.issubset(leagues):
            issues.append("regresion_ligas:" + ",".join(sorted(old_leagues - leagues)))
        old_by_key = {match_identity(match): match for match in old_matches}
        for match in matches:
            old = old_by_key.get(match_identity(match))
            if not old:
                continue
            for field in ("probs", "preview", "alineacion"):
                if (
                    field == "probs"
                    and candidate.get("schema_version", 0) >= 5
                    and match.get("prediction_unavailable_reason") == "sin_snapshot_prepartido"
                ):
                    continue
                if not _missing(old.get(field)) and _missing(match.get(field)):
                    issues.append(f"regresion_{field}:{match.get('id')}")

    # ``once_vacio_proximo`` es INFORMATIVO, no bloqueante. Un partido próximo
    # NUEVO sin once (p. ej. una eliminatoria recién programada cuyos equipos aún
    # no tienen plantilla que reconstruir, o un fixture que la fuente de onces no
    # localiza) no puede tirar TODO el candidato y congelar en el último feed
    # bueno las previas, predicciones, clima y la IA ya generada del resto de
    # partidos. La pérdida de un once YA publicado se sigue bloqueando aparte con
    # ``regresion_alineacion``, y toda próxima conserva al menos su previa —que sí
    # es bloqueante y el motor local siempre puede rellenar—. Este era el bloqueo
    # real que mantenía la IA congelada: 8 próximos sin once invalidaban el feed
    # entero en cada ejecución.
    warnings = [issue for issue in issues if issue.startswith("once_vacio_proximo:")]
    blocking = [issue for issue in issues if not issue.startswith("once_vacio_proximo:")]

    metrics = {
        "matches": len(matches),
        "predictions": prediction_count,
        "previews": preview_count,
        "lineups": lineup_count,
        "upcoming_content_required": required_ai_count,
        "blank_matches": blank_matches,
        "empty_lineups_upcoming": len(warnings),
        "leagues": sorted(str(league) for league in leagues if league),
        "evaluable_predictions": evaluable,
    }
    return {
        "valid": not blocking,
        "score": 1.0 if not blocking else round(max(0.0, 1.0 - len(blocking) / max(len(matches), 1)), 3),
        "issues": blocking[:50],
        "warnings": warnings[:50],
        "metrics": metrics,
    }


def write_feed_safely(path: Path, payload: dict, previous: dict | None = None) -> tuple[bool, dict]:
    """Valida, escribe atómicamente y nunca pisa un feed bueno con uno peor."""

    previous = previous if previous is not None else load_feed(path)
    preserve_last_known_good(payload, previous)
    report = evaluate_feed(payload, previous)
    payload["feed_quality"] = report
    if not report["valid"]:
        return False, report

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return True, report
