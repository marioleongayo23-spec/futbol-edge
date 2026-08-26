"""Alineación PRE-FINAL a T-3h.

La PRE-FINAL solo se considera once probable cuando está apoyada por evidencia
externa reciente para AMBOS equipos. Una noticia de un solo lado puede mejorar
la estimación, pero nunca respalda automáticamente el XI del rival.
No sustituye a la alineación oficial T-60/T-30 y no altera 1X2 sin validación.
"""
from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

from .ingest.ai_client import available, chat
from .ingest.lineups_ai import _extract_json, _match_key, _validate_item, ensure_position_metadata
from .ingest.probable_lineup_media import collect_probable_lineup_media, covered_sides

MADRID = ZoneInfo("Europe/Madrid")
PREFINAL_TARGET_HOURS = 3.0
PREFINAL_TOLERANCE_HOURS = 0.35  # cron cada 15 min + pequeños retrasos del runner


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _aware(parsed).astimezone(MADRID)


def _valid_xi(lineup: dict | None) -> bool:
    if not isinstance(lineup, dict):
        return False
    copy = dict(lineup)
    return bool(ensure_position_metadata(copy)) and len(copy.get("local") or []) == 11 and len(copy.get("visitante") or []) == 11


def in_prefinal_window(match: dict, now: datetime) -> bool:
    kickoff = _parse(match.get("kickoff"))
    if not kickoff:
        return False
    hours = (kickoff - _aware(now).astimezone(MADRID)).total_seconds() / 3600
    return 0 < hours and abs(hours - PREFINAL_TARGET_HOURS) <= PREFINAL_TOLERANCE_HOURS


def _filter_real_props(rows, starters: list[str]) -> list[dict]:
    allowed = {str(name).strip().casefold() for name in starters}
    return [
        row for row in (rows or [])
        if isinstance(row, dict)
        and str(row.get("jugador") or row.get("player") or "").strip().casefold() in allowed
        and str(row.get("source") or "").startswith("API-Football")
        and row.get("sample_minutes")
    ]


def _row_sides(row: dict, match: dict) -> list[str]:
    explicit = [side for side in (row.get("covered_sides") or []) if side in {"local", "visitante"}]
    if explicit:
        return explicit
    # Compatibilidad con cachés/fixtures antiguos que aún no traen covered_sides.
    return covered_sides(
        match.get("home", ""),
        match.get("away", ""),
        str(row.get("title") or ""),
        str(row.get("snippet") or ""),
    )


def _source_card(row: dict) -> dict:
    return {
        key: row.get(key)
        for key in ("source", "title", "published_at", "url", "evidence_level", "evidence_rank")
        if row.get(key) is not None
    }


def _evidence_summary(match: dict, media: list[dict]) -> dict:
    local = []
    away = []
    for row in media or []:
        if not isinstance(row, dict):
            continue
        sides = _row_sides(row, match)
        card = _source_card(row)
        if "local" in sides:
            local.append(card)
        if "visitante" in sides:
            away.append(card)
    local_grounded = bool(local)
    away_grounded = bool(away)
    if local_grounded and away_grounded:
        level = "trusted_media_both_sides"
    elif local_grounded or away_grounded:
        level = "trusted_media_partial"
    else:
        level = "model_only"
    return {
        "policy": "both_sides_required_for_probable",
        "hierarchy": ["official_lineup", "trusted_media_both_sides", "model_estimate"],
        "level": level,
        "local": {"grounded": local_grounded, "sources": local},
        "visitante": {"grounded": away_grounded, "sources": away},
    }


def _prompt(candidates: list[dict]) -> str:
    payload = []
    for item in candidates:
        match = item["match"]
        current = match.get("alineacion") or {}
        payload.append({
            "partido": item["partido"],
            "kickoff": match.get("kickoff"),
            "once_previo_local": current.get("local") or [],
            "once_previo_visitante": current.get("visitante") or [],
            "bajas_previas_local": current.get("bajas_local") or [],
            "bajas_previas_visitante": current.get("bajas_visitante") or [],
            "evidencia_medios": item["media"],
            "cobertura_evidencia": item["evidence"],
        })
    return (
        "Actúas como analista prepartido de fútbol español. Son aproximadamente T-3h. "
        "Construye una propuesta de XI usando SOLO la evidencia suministrada, el once previo "
        "y contexto táctico razonable. La prensa es evidencia, no confirmación oficial. "
        "La evidencia se atribuye por equipo: jamás uses una noticia del local como respaldo del XI visitante, ni al revés. "
        "Si falta evidencia de un lado, ese XI será tratado por el sistema como estimación aunque puedas proponerlo. "
        "No inventes lesiones ni digas que un once es oficial. Si una noticia contradice otra, "
        "prioriza la más reciente y explica la incertidumbre solo mediante las bajas/dudas. "
        "Para cada partido devuelve EXACTAMENTE 11 jugadores únicos por lado, ordenados POR→DEF→MED→ATA. "
        "No generes estadísticas numéricas de jugadores. Devuelve EXCLUSIVAMENTE JSON válido con esta forma: "
        '[{"partido":"tal cual","local":[{"j":"Nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
        '"visitante":[{"j":"Nombre","pos":"..."}],"bajas_local":["Nombre (duda: motivo)"],'
        '"bajas_visitante":["Nombre (lesión|sanción|duda|rotación: motivo)"]}]\nDATOS:\n'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _apply_result(match: dict, result: dict, media: list[dict], evidence: dict,
                  now: datetime, provider: str, model: str) -> None:
    old = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    local_props = _filter_real_props(old.get("clave_local"), result["local"])
    visitor_props = _filter_real_props(old.get("clave_visitante"), result["visitante"])
    fully_grounded = evidence.get("level") == "trusted_media_both_sides"
    partially_grounded = evidence.get("level") == "trusted_media_partial"
    if fully_grounded:
        source_quality = "media_grounded"
        lineup_kind = "source_grounded_probable"
        phase = "pre_final"
        status = "probable"
        fuente = "Pre-final T-3h · medios recientes para ambos equipos + IA"
        warning = None
    elif partially_grounded:
        source_quality = "media_partial"
        lineup_kind = "partially_grounded_estimate"
        phase = "pre_final_estimate"
        status = "estimado"
        fuente = "Estimación T-3h · evidencia reciente solo para uno de los equipos + IA"
        missing_side = "visitante" if evidence.get("local", {}).get("grounded") else "local"
        warning = f"Hay evidencia reciente solo para el {('equipo visitante' if missing_side == 'visitante' else 'equipo local')}; el partido no se etiqueta como XI probable completo."
    else:
        source_quality = "model_only"
        lineup_kind = "model_estimate"
        phase = "pre_final_estimate"
        status = "estimado"
        fuente = "Estimación T-3h · IA + once previo · sin fuente externa suficiente"
        warning = "XI estimado por modelo; no existe evidencia externa suficiente para ambos equipos."

    merged = {
        **old,
        **result,
        "clave_local": local_props,
        "clave_visitante": visitor_props,
        "best_props": [],
        "status": status,
        "phase": phase,
        "lineup_kind": lineup_kind,
        "provider": provider,
        "model": model,
        "fuente": fuente,
        "media_sources": media,
        "lineup_evidence": evidence,
        "evidence_scope": evidence.get("level"),
        "source_quality": source_quality,
        "display_warning": warning,
        "prefinal_refresh_at": stamp,
        "source_updated_at": stamp,
        "generated_at": stamp,
        "ts": stamp,
        "numeric_props_source": "API-Football · players" if (local_props or visitor_props) else "pending_real_data",
    }
    ensure_position_metadata(merged)
    match["alineacion"] = merged


def _mark_fallback(match: dict, media: list[dict], evidence: dict, now: datetime) -> bool:
    lineup = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    lineup["prefinal_attempt_at"] = stamp
    lineup["media_sources"] = media
    lineup["lineup_evidence"] = evidence
    lineup["evidence_scope"] = evidence.get("level")
    if not _valid_xi(lineup):
        match["alineacion"] = lineup
        return False
    lineup["status"] = "estimado"
    lineup["phase"] = "pre_final_estimate"
    lineup["lineup_kind"] = "fallback_estimate"
    lineup["prefinal_refresh_at"] = stamp
    lineup["source_quality"] = "fallback_with_media" if media else "statistical_fallback"
    lineup["fuente"] = (
        "Estimación T-3h · once previo + señales de medios no integradas (fallback)"
        if media else "Estimación T-3h · motor/once previo (fallback)"
    )
    lineup["display_warning"] = (
        "Hay señales de medios, pero no se pudo construir un once probable validado; se conserva una estimación previa."
        if media else "XI estimado sin una fuente externa fiable de once probable."
    )
    match["alineacion"] = lineup
    return True


def refresh_prefinal_lineups(matches: list[dict], now: datetime, limit: int = 8) -> dict:
    """Refresca una vez el XI en la ventana T-3h.

    Un PRE-FINAL solo se promociona a ``probable`` si ambos lados están
    respaldados por evidencia de prensa reciente y el resultado contiene 11+11.
    Evidencia parcial se conserva y se hace auditable, pero el estado global
    permanece ``estimado``.
    """
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        if match.get("finished") or not match.get("probs") or not in_prefinal_window(match, now_local):
            continue
        lineup = match.get("alineacion") or {}
        if lineup.get("status") == "confirmado" or lineup.get("prefinal_refresh_at"):
            continue
        media = collect_probable_lineup_media(match.get("home", ""), match.get("away", ""), now_local)
        evidence = _evidence_summary(match, media)
        candidates.append({
            "match": match,
            "partido": f"{match.get('home', '')} - {match.get('away', '')}",
            "media": media,
            "evidence": evidence,
        })
        if len(candidates) >= limit:
            break

    results: dict[str, dict] = {}
    provider = model = None
    if candidates and available():
        response = chat(_prompt(candidates), max_tokens=3200, temperature=0.15, timeout=45)
        if response:
            raw = _extract_json(response.text) or []
            requested = {_match_key(item["partido"]): item["partido"] for item in candidates}
            for item in raw:
                key = _match_key(item.get("partido", "")) if isinstance(item, dict) else ""
                if key not in requested:
                    continue
                validated = _validate_item(item)
                if validated:
                    results[key] = validated
            provider, model = response.provider, response.model

    refreshed = grounded = partial = fallback = probable = 0
    for item in candidates:
        match = item["match"]
        key = _match_key(item["partido"])
        result = results.get(key)
        level = item["evidence"].get("level")
        grounded += int(level == "trusted_media_both_sides")
        partial += int(level == "trusted_media_partial")
        if result and provider and model:
            _apply_result(match, result, item["media"], item["evidence"], now_local, provider, model)
            refreshed += 1
            probable += int(match.get("alineacion", {}).get("status") == "probable")
        elif _mark_fallback(match, item["media"], item["evidence"], now_local):
            refreshed += 1
            fallback += 1

    return {
        "candidates": len(candidates),
        "refreshed": refreshed,
        "media_grounded": grounded,
        "media_partial": partial,
        "probable": probable,
        "fallback": fallback,
        "target": "T-3h",
        "grounding_policy": "both_sides_required_for_probable",
    }
