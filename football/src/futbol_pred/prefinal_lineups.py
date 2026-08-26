"""Alineación PRE-FINAL a T-3h.

La PRE-FINAL solo se considera once probable cuando está apoyada por evidencia
externa reciente. Si no hay medios/fuente suficiente, el sistema puede conservar
o producir una estimación para análisis interno, pero queda marcada como
``estimado`` y nunca se promociona visualmente como once probable.
No sustituye a la alineación oficial T-60/T-30 y no altera 1X2 sin validación.
"""
from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

from .ingest.ai_client import available, chat
from .ingest.lineups_ai import _extract_json, _match_key, _validate_item, ensure_position_metadata
from .ingest.probable_lineup_media import collect_probable_lineup_media

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
        })
    return (
        "Actúas como analista prepartido de fútbol español. Son aproximadamente T-3h. "
        "Construye una propuesta de XI usando SOLO la evidencia suministrada, el once previo "
        "y contexto táctico razonable. La prensa es evidencia, no confirmación oficial. "
        "Si evidencia_medios está vacía, el resultado será tratado por el sistema únicamente "
        "como ESTIMACIÓN de modelo, nunca como once probable respaldado por fuentes. "
        "No inventes lesiones ni digas que un once es oficial. Si una noticia contradice otra, "
        "prioriza la más reciente y explica la incertidumbre solo mediante las bajas/dudas. "
        "Para cada partido devuelve EXACTAMENTE 11 jugadores únicos por lado, ordenados POR→DEF→MED→ATA. "
        "No generes estadísticas numéricas de jugadores. Devuelve EXCLUSIVAMENTE JSON válido con esta forma: "
        '[{"partido":"tal cual","local":[{"j":"Nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
        '"visitante":[{"j":"Nombre","pos":"..."}],"bajas_local":["Nombre (duda: motivo)"],'
        '"bajas_visitante":["Nombre (lesión|sanción|duda|rotación: motivo)"]}]\nDATOS:\n'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _apply_result(match: dict, result: dict, media: list[dict], now: datetime, provider: str, model: str) -> None:
    old = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    local_props = _filter_real_props(old.get("clave_local"), result["local"])
    visitor_props = _filter_real_props(old.get("clave_visitante"), result["visitante"])
    grounded = bool(media)
    merged = {
        **old,
        **result,
        "clave_local": local_props,
        "clave_visitante": visitor_props,
        "best_props": [],
        "status": "probable" if grounded else "estimado",
        "phase": "pre_final" if grounded else "pre_final_estimate",
        "lineup_kind": "source_grounded_probable" if grounded else "model_estimate",
        "provider": provider,
        "model": model,
        "fuente": "Pre-final T-3h · medios recientes + IA" if grounded else "Estimación T-3h · IA + once previo · sin fuente externa suficiente",
        "media_sources": media,
        "source_quality": "media_grounded" if grounded else "model_only",
        "display_warning": None if grounded else "XI estimado por modelo; no existe una fuente externa suficiente para llamarlo once probable.",
        "prefinal_refresh_at": stamp,
        "source_updated_at": stamp,
        "generated_at": stamp,
        "ts": stamp,
        "numeric_props_source": "API-Football · players" if (local_props or visitor_props) else "pending_real_data",
    }
    ensure_position_metadata(merged)
    match["alineacion"] = merged


def _mark_fallback(match: dict, media: list[dict], now: datetime) -> bool:
    lineup = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    lineup["prefinal_attempt_at"] = stamp
    lineup["media_sources"] = media
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

    Devuelve métricas operativas para auditar cobertura y grounding. Solo una
    respuesta con evidencia externa se etiqueta como PRE-FINAL probable. Si IA
    falla o no hay grounding suficiente, conserva el mejor XI previo válido como
    estimación; nunca rellena nombres para alcanzar 11 ni lo vende como probable.
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
        candidates.append({
            "match": match,
            "partido": f"{match.get('home', '')} - {match.get('away', '')}",
            "media": media,
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

    refreshed = grounded = fallback = 0
    for item in candidates:
        match = item["match"]
        key = _match_key(item["partido"])
        result = results.get(key)
        if result and provider and model:
            _apply_result(match, result, item["media"], now_local, provider, model)
            refreshed += 1
            grounded += int(bool(item["media"]))
        elif _mark_fallback(match, item["media"], now_local):
            refreshed += 1
            fallback += 1
            grounded += int(bool(item["media"]))

    return {
        "candidates": len(candidates),
        "refreshed": refreshed,
        "media_grounded": grounded,
        "fallback": fallback,
        "target": "T-3h",
    }
