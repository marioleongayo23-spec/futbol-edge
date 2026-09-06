"""Alineación probable intradía y PRE-FINAL a T-3h.

La etiqueta ``probable`` solo se usa cuando hay evidencia externa reciente para
AMBOS equipos. El mismo día se refresca en T-8h, T-3h y T-90m para incorporar
cambios de última hora sin convertir la mera plantilla en un once probable.
Los últimos XI oficiales sirven como continuidad y como memoria de posición;
la alineación oficial de API-Football siempre prevalece en T-60/T-30.
"""
from __future__ import annotations

from .normalize import same_team

from collections import Counter
from datetime import datetime
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from .ingest.ai_client import available, chat
from .ingest.lineups_ai import _extract_json, _match_key, _validate_item, ensure_position_metadata
from .ingest.probable_lineup_media import collect_probable_lineup_media, covered_sides

MADRID = ZoneInfo("Europe/Madrid")
PREFINAL_TARGET_HOURS = 3.0
PREFINAL_TOLERANCE_HOURS = 0.35  # compatibilidad con snapshots/tests T-3h
PROBABLE_REFRESH_WINDOWS = (
    ("T-8h", 8.0, 0.45),
    ("T-3h", 3.0, 0.35),
    ("T-90m", 1.5, 0.25),
)
_VALID_POSITIONS = {"POR", "LI", "DFC", "LD", "CAI", "CAD", "MCD", "MC", "MI", "MD", "MP", "EI", "ED", "DC"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _aware(parsed).astimezone(MADRID)


def _entity_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"\b(fc|cf|cd|ud|sd|rcd|club|deportivo|real)\b|[^a-z0-9]", "", text)


def _same_team(left: str | None, right: str | None) -> bool:
    return same_team(left, right)


def _valid_xi(lineup: dict | None) -> bool:
    if not isinstance(lineup, dict):
        return False
    copy = dict(lineup)
    return bool(ensure_position_metadata(copy)) and len(copy.get("local") or []) == 11 and len(copy.get("visitante") or []) == 11


def in_prefinal_window(match: dict, now: datetime) -> bool:
    """Compatibilidad: identifica exclusivamente la ventana PRE-FINAL T-3h."""
    kickoff = _parse(match.get("kickoff"))
    if not kickoff:
        return False
    hours = (kickoff - _aware(now).astimezone(MADRID)).total_seconds() / 3600
    return 0 < hours and abs(hours - PREFINAL_TARGET_HOURS) <= PREFINAL_TOLERANCE_HOURS


def _probable_refresh_window(match: dict, now: datetime) -> str | None:
    kickoff = _parse(match.get("kickoff"))
    if not kickoff:
        return None
    hours = (kickoff - _aware(now).astimezone(MADRID)).total_seconds() / 3600
    if hours <= 0:
        return None
    for label, target, tolerance in PROBABLE_REFRESH_WINDOWS:
        if abs(hours - target) <= tolerance:
            return label
    return None


def _official_history_for_team(
    matches: list[dict], team: str, before: datetime, limit: int = 4
) -> list[dict]:
    rows = []
    ordered = sorted(
        (match for match in matches if isinstance(match, dict)),
        key=lambda match: _parse(match.get("kickoff")) or datetime.min.replace(tzinfo=MADRID),
        reverse=True,
    )
    for historical in ordered:
        kickoff = _parse(historical.get("kickoff"))
        if not kickoff or kickoff >= before:
            continue
        lineup = historical.get("alineacion") or {}
        if lineup.get("status") != "confirmado":
            continue
        if _same_team(historical.get("home"), team):
            names = lineup.get("local") or []
            positions = lineup.get("posiciones_local") or []
        elif _same_team(historical.get("away"), team):
            names = lineup.get("visitante") or []
            positions = lineup.get("posiciones_visitante") or []
        else:
            continue
        if len(names) != 11 or len(positions) != 11:
            continue
        rows.append({
            "kickoff": kickoff.isoformat(),
            "players": list(names),
            "positions": list(positions),
        })
        if len(rows) >= limit:
            break
    return rows


def _official_history(matches: list[dict], match: dict) -> dict:
    before = _parse(match.get("kickoff")) or datetime.max.replace(tzinfo=MADRID)
    return {
        "local": _official_history_for_team(matches, match.get("home", ""), before),
        "visitante": _official_history_for_team(matches, match.get("away", ""), before),
    }


def _position_memory(history_rows: list[dict]) -> dict[str, Counter]:
    memory: dict[str, Counter] = {}
    for row in history_rows or []:
        for name, position in zip(row.get("players") or [], row.get("positions") or []):
            if position not in _VALID_POSITIONS:
                continue
            key = _entity_key(name)
            if not key:
                continue
            memory.setdefault(key, Counter())[position] += 1
    return memory


def _reconcile_positions(result: dict, history: dict) -> dict:
    """Corrige posiciones del modelo con roles repetidos en XI oficiales previos.

    Una sola aparición no fuerza lateralidad: se exigen al menos dos onces
    oficiales y una mayoría >=60 %, evitando convertir una actuación puntual en
    posición habitual. El nombre del jugador nunca se cambia aquí.
    """
    overrides = 0
    supported = 0
    evidence_rows = []
    for side, positions_key in (("local", "posiciones_local"), ("visitante", "posiciones_visitante")):
        memory = _position_memory(history.get(side) or [])
        positions = list(result.get(positions_key) or [])
        names = result.get(side) or []
        if len(positions) != len(names):
            continue
        for index, name in enumerate(names):
            counter = memory.get(_entity_key(name))
            if not counter:
                continue
            total = sum(counter.values())
            habitual, count = counter.most_common(1)[0]
            if total < 2 or count / total < 0.60:
                continue
            supported += 1
            before = positions[index]
            if before != habitual:
                positions[index] = habitual
                overrides += 1
                evidence_rows.append({
                    "side": side,
                    "player": name,
                    "from": before,
                    "to": habitual,
                    "official_starts": total,
                    "support": round(count / total, 2),
                })
        result[positions_key] = positions
    result["position_source"] = "official_history+model" if supported else "model_unverified"
    result["position_history_supported"] = supported
    result["position_history_overrides"] = overrides
    result["position_history_evidence"] = evidence_rows
    return result


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
        "hierarchy": ["official_lineup", "trusted_media_both_sides", "official_history", "model_estimate"],
        "level": level,
        "local": {"grounded": local_grounded, "sources": local},
        "visitante": {"grounded": away_grounded, "sources": away},
    }


def _trusted_previous_xi(current: dict) -> tuple[list[str], list[str], str]:
    """Solo deja pasar un XI previo que ya tuviera respaldo externo real.

    ``squad-only-v3``, model-only y fallbacks son candidatos plausibles de una
    plantilla, no continuidad fiable. No deben convertirse en verdad por
    repetición al alimentar el siguiente prompt intradía.
    """
    if not isinstance(current, dict):
        return [], [], "none"
    if current.get("model") == "squad-only-v3":
        return [], [], "squad_only_rejected"
    trusted = (
        current.get("status") == "confirmado"
        or current.get("source_quality") == "media_grounded"
        or current.get("lineup_kind") == "source_grounded_probable"
    )
    if not trusted:
        return [], [], "untrusted_estimate_rejected"
    local = list(current.get("local") or [])
    visitor = list(current.get("visitante") or [])
    if len(local) != 11 or len(visitor) != 11:
        return [], [], "incomplete_rejected"
    return local, visitor, "trusted"


def _prompt(candidates: list[dict]) -> str:
    payload = []
    for item in candidates:
        match = item["match"]
        current = match.get("alineacion") or {}
        prev_local, prev_visitor, previous_quality = _trusted_previous_xi(current)
        payload.append({
            "partido": item["partido"],
            "ventana": item["window"],
            "kickoff": match.get("kickoff"),
            "once_previo_local": prev_local,
            "once_previo_visitante": prev_visitor,
            "calidad_once_previo": previous_quality,
            "ultimos_onces_oficiales": item.get("official_history") or {},
            "bajas_previas_local": current.get("bajas_local") or [],
            "bajas_previas_visitante": current.get("bajas_visitante") or [],
            "evidencia_medios": item["media"],
            "cobertura_evidencia": item["evidence"],
        })
    return (
        "Actúas como analista prepartido de fútbol español durante el mismo día del partido. "
        "Construye una propuesta de XI usando SOLO la evidencia suministrada, los últimos XI oficiales, "
        "y, únicamente si se facilita, un once previo ya respaldado. NO uses un jugador solo porque figure "
        "en la plantilla: si no existe una señal nueva que justifique un cambio, prioriza continuidad de los "
        "últimos XI oficiales. Una lista de plantilla o una estimación model-only NO es evidencia de titularidad. "
        "La prensa es evidencia, no confirmación oficial. La evidencia se atribuye por equipo: jamás uses una "
        "noticia del local como respaldo del XI visitante, ni al revés. Si falta evidencia de un lado, ese XI será "
        "tratado por el sistema como estimación aunque puedas proponerlo. No inventes lesiones ni digas que un once "
        "es oficial. Si una noticia contradice otra, prioriza la más reciente. Para cada partido devuelve EXACTAMENTE "
        "11 jugadores únicos por lado, ordenados POR→DEF→MED→ATA y con su demarcación habitual real. "
        "No generes estadísticas numéricas de jugadores. Devuelve EXCLUSIVAMENTE JSON válido con esta forma: "
        '[{"partido":"tal cual","local":[{"j":"Nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
        '"visitante":[{"j":"Nombre","pos":"..."}],"bajas_local":["Nombre (duda: motivo)"],'
        '"bajas_visitante":["Nombre (lesión|sanción|duda|rotación: motivo)"]}]\nDATOS:\n'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _phase_for(window: str, grounded: bool) -> str:
    if window == "T-3h":
        return "pre_final" if grounded else "pre_final_estimate"
    return "same_day_probable" if grounded else "same_day_estimate"


def _attempts(old: dict, window: str, stamp: str) -> dict:
    attempts = dict(old.get("probable_refresh_windows") or {})
    attempts[window] = stamp
    return attempts


def _apply_result(
    match: dict,
    result: dict,
    media: list[dict],
    evidence: dict,
    now: datetime,
    provider: str,
    model: str,
    window: str,
) -> None:
    old = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    local_props = _filter_real_props(old.get("clave_local"), result["local"])
    visitor_props = _filter_real_props(old.get("clave_visitante"), result["visitante"])
    fully_grounded = evidence.get("level") == "trusted_media_both_sides"
    partially_grounded = evidence.get("level") == "trusted_media_partial"
    if fully_grounded:
        source_quality = "media_grounded"
        lineup_kind = "source_grounded_probable"
        status = "probable"
        fuente = f"{window} · medios recientes para ambos equipos + continuidad oficial + IA"
        warning = None
    elif partially_grounded:
        source_quality = "media_partial"
        lineup_kind = "partially_grounded_estimate"
        status = "estimado"
        fuente = f"Estimación {window} · evidencia reciente solo para un equipo + continuidad oficial + IA"
        missing_side = "visitante" if evidence.get("local", {}).get("grounded") else "local"
        warning = f"Hay evidencia reciente solo para el {('equipo visitante' if missing_side == 'visitante' else 'equipo local')}; el partido no se etiqueta como XI probable completo."
    else:
        source_quality = "model_only"
        lineup_kind = "model_estimate"
        status = "estimado"
        fuente = f"Estimación {window} · continuidad oficial + IA · sin fuente externa suficiente"
        warning = "XI estimado por modelo; no existe evidencia externa suficiente para ambos equipos."

    merged = {
        **old,
        **result,
        "clave_local": local_props,
        "clave_visitante": visitor_props,
        "best_props": [],
        "status": status,
        "phase": _phase_for(window, fully_grounded),
        "lineup_kind": lineup_kind,
        "provider": provider,
        "model": model,
        "fuente": fuente,
        "media_sources": media,
        "lineup_evidence": evidence,
        "evidence_scope": evidence.get("level"),
        "source_quality": source_quality,
        "display_warning": warning,
        "probable_refresh_windows": _attempts(old, window, stamp),
        "probable_refresh_window_last": window,
        "source_updated_at": stamp,
        "generated_at": stamp,
        "ts": stamp,
        "numeric_props_source": "API-Football · players" if (local_props or visitor_props) else "pending_real_data",
        **({"prefinal_refresh_at": stamp} if window == "T-3h" else {}),
    }
    ensure_position_metadata(merged)
    match["alineacion"] = merged


def _mark_attempt_without_downgrade(match: dict, window: str, now: datetime) -> None:
    lineup = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    lineup["probable_refresh_windows"] = _attempts(lineup, window, stamp)
    lineup["probable_refresh_window_last"] = window
    lineup["probable_refresh_preserved"] = True
    if window == "T-3h":
        lineup["prefinal_refresh_at"] = stamp
    match["alineacion"] = lineup


def _mark_fallback(
    match: dict, media: list[dict], evidence: dict, now: datetime, window: str
) -> bool:
    lineup = match.get("alineacion") or {}
    stamp = _aware(now).astimezone(MADRID).isoformat()
    lineup["probable_refresh_windows"] = _attempts(lineup, window, stamp)
    lineup["probable_refresh_window_last"] = window
    if window == "T-3h":
        lineup["prefinal_attempt_at"] = stamp
    lineup["media_sources"] = media
    lineup["lineup_evidence"] = evidence
    lineup["evidence_scope"] = evidence.get("level")
    if not _valid_xi(lineup):
        match["alineacion"] = lineup
        return False
    lineup["status"] = "estimado"
    lineup["phase"] = _phase_for(window, False)
    lineup["lineup_kind"] = "fallback_estimate"
    if window == "T-3h":
        lineup["prefinal_refresh_at"] = stamp
    lineup["source_quality"] = "fallback_with_media" if media else "statistical_fallback"
    lineup["fuente"] = (
        f"Estimación {window} · once previo + señales de medios no integradas (fallback)"
        if media else f"Estimación {window} · motor/once previo (fallback)"
    )
    lineup["display_warning"] = (
        "Hay señales de medios, pero no se pudo construir un once probable validado; se conserva una estimación previa."
        if media else "XI estimado sin una fuente externa fiable de once probable."
    )
    match["alineacion"] = lineup
    return True


def refresh_prefinal_lineups(matches: list[dict], now: datetime, limit: int = 8) -> dict:
    """Refresca el XI en T-8h, T-3h y T-90m; T-3h sigue siendo PRE-FINAL.

    Un XI solo se promociona a ``probable`` si ambos lados están respaldados por
    evidencia reciente. Un refresco posterior nunca degrada un XI ya grounded si
    el índice de noticias temporalmente deja de devolver la evidencia anterior.
    """
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        if match.get("finished") or not match.get("probs"):
            continue
        window = _probable_refresh_window(match, now_local)
        if not window:
            continue
        lineup = match.get("alineacion") or {}
        if lineup.get("status") == "confirmado":
            continue
        attempts = lineup.get("probable_refresh_windows") or {}
        if attempts.get(window) or (window == "T-3h" and lineup.get("prefinal_refresh_at")):
            continue
        media = collect_probable_lineup_media(match.get("home", ""), match.get("away", ""), now_local)
        evidence = _evidence_summary(match, media)
        candidates.append({
            "match": match,
            "partido": f"{match.get('home', '')} - {match.get('away', '')}",
            "window": window,
            "media": media,
            "evidence": evidence,
            "official_history": _official_history(matches, match),
        })
        if len(candidates) >= limit:
            break

    results: dict[str, dict] = {}
    provider = model = None
    if candidates and available():
        response = chat(_prompt(candidates), max_tokens=3600, temperature=0.12, timeout=45)
        if response:
            raw = _extract_json(response.text) or []
            requested = {_match_key(item["partido"]): item["partido"] for item in candidates}
            for raw_item in raw:
                key = _match_key(raw_item.get("partido", "")) if isinstance(raw_item, dict) else ""
                if key not in requested:
                    continue
                validated = _validate_item(raw_item)
                if validated:
                    results[key] = validated
            provider, model = response.provider, response.model

    refreshed = grounded = partial = fallback = probable = preserved = 0
    window_counts = Counter()
    for item in candidates:
        match = item["match"]
        key = _match_key(item["partido"])
        result = results.get(key)
        level = item["evidence"].get("level")
        old = match.get("alineacion") or {}
        window_counts[item["window"]] += 1
        grounded += int(level == "trusted_media_both_sides")
        partial += int(level == "trusted_media_partial")

        # Una fuente grounded anterior no se degrada por un RSS que en la pasada
        # siguiente ya no devuelve el mismo artículo.
        if old.get("source_quality") == "media_grounded" and level != "trusted_media_both_sides":
            _mark_attempt_without_downgrade(match, item["window"], now_local)
            preserved += 1
            continue

        if result and provider and model:
            result = _reconcile_positions(result, item["official_history"])
            _apply_result(
                match, result, item["media"], item["evidence"], now_local,
                provider, model, item["window"],
            )
            refreshed += 1
            probable += int(match.get("alineacion", {}).get("status") == "probable")
        elif _mark_fallback(match, item["media"], item["evidence"], now_local, item["window"]):
            refreshed += 1
            fallback += 1

    return {
        "candidates": len(candidates),
        "refreshed": refreshed,
        "media_grounded": grounded,
        "media_partial": partial,
        "probable": probable,
        "fallback": fallback,
        "preserved": preserved,
        "target": "T-8h/T-3h/T-90m",
        "windows": dict(window_counts),
        "grounding_policy": "both_sides_required_for_probable",
    }
