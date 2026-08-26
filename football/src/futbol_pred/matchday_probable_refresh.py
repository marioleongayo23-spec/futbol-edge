"""Refresco autoritativo T-2h para XI probable y props reales de jugadores.

Objetivo operativo:
- desde T-120 hasta T-12, vuelve a investigar medios fiables cada ~12 min;
- no usa una mera plantilla como evidencia de titularidad;
- exige posiciones explícitas en la respuesta del estimador (sin 4-3-3 por índice);
- si cambia el XI probable, recalcula props a partir de tasas REALES de API-Football;
- al confirmarse el XI oficial, reutiliza el mismo caché intradía de tasas para
  cubrir inmediatamente los 22 titulares sin esperar al pipeline pesado.

Las estadísticas de temporada no se descargan cada 5 minutos: se refrescan una
vez al entrar en T-2h y se reutilizan durante unas horas porque no cambian en ese
intervalo. XI, clima, bajas, cuotas y estado sí siguen sus ciclos rápidos.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import re
from typing import Iterable

import requests

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .ingest import api_football_players as player_api
from .ingest.api_football import ApiFootballClient
from .ingest.lineups_ai import _best_props, _extract_json, _match_key, _position, _validate_item
from .prefinal_lineups import (
    MADRID,
    _apply_result,
    _evidence_summary,
    _official_history,
    _reconcile_positions,
    collect_probable_lineup_media,
    available,
    chat,
    _prompt,
)

OUTPUT = DATA_DIR / "dashboard.json"
CRITICAL_FROM_MIN = 120
CRITICAL_UNTIL_MIN = 12
MEDIA_COOLDOWN_MIN = 12
PLAYER_RATES_TTL_MIN = 360
MIN_MATCHDAY_PLAYER_MINUTES = 45
MAX_ARTICLE_CHARS = 2400
MAX_ARTICLES_PER_MATCH = 3


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse(value) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(value))).astimezone(MADRID)
    except (TypeError, ValueError):
        return None


def _age_min(value, now_local: datetime) -> float | None:
    stamp = _parse(value)
    if stamp is None:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 60.0)


def _clean_text(value: str | None) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _article_context(url: str | None, session=requests) -> dict:
    """Obtiene contexto textual de una pieza pública sin hacerlo obligatorio.

    El texto se usa únicamente como contexto del estimador y NO se persiste en el
    feed. Se prioriza JSON-LD articleBody y, si no existe, la description.
    """
    if not url:
        return {}
    try:
        response = session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; FutbolEdge/1.0; +matchday-lineup)",
                "Accept-Language": "es-ES,es;q=0.9",
            },
            timeout=10,
            allow_redirects=True,
        )
        if not response.ok:
            return {}
        html = response.text or ""
    except Exception:
        return {}

    body = None
    modified = None
    # JSON-LD suele ser la vía más estable para medios modernos.
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes: Iterable = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            candidate = node.get("articleBody")
            if candidate and len(_clean_text(candidate)) > len(_clean_text(body)):
                body = candidate
                modified = node.get("dateModified") or node.get("datePublished")

    if not body:
        match = re.search(
            r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)',
            html,
            re.I,
        )
        if match:
            body = match.group(1)
    text = _clean_text(body)[:MAX_ARTICLE_CHARS]
    return {
        "analysis_text": text or None,
        "article_modified_at": str(modified) if modified else None,
        "resolved_url": getattr(response, "url", None),
    }


def _enrich_media(rows: list[dict]) -> list[dict]:
    enriched = []
    for index, row in enumerate(rows or []):
        item = dict(row)
        if index < MAX_ARTICLES_PER_MATCH:
            item.update({k: v for k, v in _article_context(item.get("url")).items() if v})
        enriched.append(item)
    return enriched


def _stored_media(rows: list[dict]) -> list[dict]:
    """Nunca persiste cuerpo de artículos en dashboard.json."""
    blocked = {"analysis_text"}
    return [{k: v for k, v in row.items() if k not in blocked} for row in rows or []]


def _media_fingerprint(rows: list[dict]) -> str:
    compact = [
        {
            "source": row.get("source"),
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "article_modified_at": row.get("article_modified_at"),
            "analysis_text": row.get("analysis_text"),
        }
        for row in rows or []
    ]
    return hashlib.sha256(json.dumps(compact, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _raw_positions_complete(item: dict) -> bool:
    """El camino crítico no acepta posiciones rellenadas por índice."""
    if not isinstance(item, dict):
        return False
    for side in ("local", "visitante"):
        rows = item.get(side) or []
        if len(rows) != 11:
            return False
        for row in rows:
            if not isinstance(row, dict):
                return False
            if not _position(row.get("pos") or row.get("posicion") or row.get("position")):
                return False
    return True


def _league_id(match: dict) -> int | None:
    label = str(match.get("league") or "").casefold()
    if "hypermotion" in label or "segunda" in label:
        return 141
    if "champions" in label or "ucl" in label:
        return 2
    if "laliga" in label or "primera" in label:
        return 140
    return None


def _season_for(match: dict, kickoff: datetime) -> int:
    try:
        season = int(match.get("season"))
        if 2000 <= season <= 2100:
            return season
    except (TypeError, ValueError):
        pass
    return kickoff.year if kickoff.month >= 7 else kickoff.year - 1


def _quota_allows_props(payload: dict) -> bool:
    health = ((payload.get("source_health") or {}).get("api_football") or {})
    try:
        remaining = int(health.get("daily_remaining"))
    except (TypeError, ValueError):
        return True
    # Reservamos margen para el XI oficial y el estado del partido.
    return remaining > 10


def _fetch_rates_low_sample(client: ApiFootballClient, team: str, season: int, league_id: int | None) -> list[dict]:
    """Muestra real de temporada aceptando arranque de curso desde 45 minutos."""
    old_threshold = player_api.MIN_PLAYER_MINUTES
    player_api.MIN_PLAYER_MINUTES = MIN_MATCHDAY_PLAYER_MINUTES
    try:
        rates = player_api.fetch_team_player_rates(client, team, season, league_id, max_pages=2)
    finally:
        player_api.MIN_PLAYER_MINUTES = old_threshold
    out = []
    for row in rates or []:
        sample = int(row.get("minutes") or 0)
        item = dict(row)
        item["sample_quality"] = "alta" if sample >= 900 else "media" if sample >= 270 else "baja_inicio_temporada"
        out.append(item)
    return out


def _cache_valid(cache: dict, now_local: datetime) -> bool:
    age = _age_min(cache.get("checked_at"), now_local)
    return age is not None and age <= PLAYER_RATES_TTL_MIN and bool(cache.get("local") or cache.get("visitante"))


def _ensure_matchday_rates(payload: dict, match: dict, now_local: datetime, client: ApiFootballClient) -> dict:
    cache = dict(match.get("matchday_player_rates") or {})
    if _cache_valid(cache, now_local):
        return cache
    if client.offline or not _quota_allows_props(payload):
        return cache
    kickoff = _parse(match.get("kickoff")) or now_local
    season = _season_for(match, kickoff)
    league_id = _league_id(match)
    local = _fetch_rates_low_sample(client, match.get("home", ""), season, league_id)
    visitor = _fetch_rates_low_sample(client, match.get("away", ""), season, league_id)
    cache = {
        "checked_at": now_local.isoformat(),
        "source": "API-Football · players",
        "season": season,
        "league_id": league_id,
        "min_sample_minutes": MIN_MATCHDAY_PLAYER_MINUTES,
        "local": local,
        "visitante": visitor,
    }
    match["matchday_player_rates"] = cache
    return cache


def _tag_prop_quality(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows or []:
        item = dict(row)
        sample = int(item.get("sample_minutes") or 0)
        item["sample_quality"] = "alta" if sample >= 900 else "media" if sample >= 270 else "baja_inicio_temporada"
        out.append(item)
    return out


def _refresh_props(payload: dict, match: dict, now_local: datetime, client: ApiFootballClient) -> bool:
    lineup = match.get("alineacion") or {}
    local_names = list(lineup.get("local") or [])
    visitor_names = list(lineup.get("visitante") or [])
    if len(local_names) != 11 or len(visitor_names) != 11:
        return False
    cache = _ensure_matchday_rates(payload, match, now_local, client)
    local_rates = cache.get("local") or []
    visitor_rates = cache.get("visitante") or []
    if not local_rates and not visitor_rates:
        return False
    local_props = _tag_prop_quality(player_api.props_for_official_starters(local_names, local_rates, limit=11))
    visitor_props = _tag_prop_quality(player_api.props_for_official_starters(visitor_names, visitor_rates, limit=11))

    # Si un jugador aún no tiene muestra suficiente, conservamos exclusivamente
    # una prop anterior que ya fuese real y que siga perteneciendo al XI actual.
    def merge_real(new_rows, old_rows, names):
        allowed = {str(name).casefold() for name in names}
        by_name = {str(row.get("jugador") or "").casefold(): row for row in new_rows}
        for row in old_rows or []:
            key = str(row.get("jugador") or "").casefold()
            if (
                key in allowed and key not in by_name
                and str(row.get("source") or "").startswith("API-Football")
                and row.get("sample_minutes")
            ):
                by_name[key] = row
        return [by_name[str(name).casefold()] for name in names if str(name).casefold() in by_name]

    local_props = merge_real(local_props, lineup.get("clave_local"), local_names)
    visitor_props = merge_real(visitor_props, lineup.get("clave_visitante"), visitor_names)
    before = (lineup.get("clave_local"), lineup.get("clave_visitante"), lineup.get("best_props"))
    lineup["clave_local"] = local_props
    lineup["clave_visitante"] = visitor_props
    lineup["best_props"] = _best_props(local_props, visitor_props) if (local_props or visitor_props) else []
    lineup["numeric_props_source"] = "API-Football · players" if (local_props or visitor_props) else "pending_real_data"
    lineup["player_props_source"] = f"API-Football · players ({len(local_props) + len(visitor_props)}/22 con muestra real)"
    lineup["player_props_checked_at"] = now_local.isoformat()
    lineup["player_props_lineup_status"] = lineup.get("status")
    quality = dict(lineup.get("quality") or {})
    quality["props_players"] = len(local_props) + len(visitor_props)
    quality["real_player_props"] = len(local_props) + len(visitor_props)
    quality["player_props_source"] = lineup["player_props_source"]
    lineup["quality"] = quality
    match["alineacion"] = lineup
    checks = dict(match.get("operational_checks") or {})
    checks["player_props_checked_at"] = now_local.isoformat()
    checks["player_props_check_result"] = "ok" if (local_props or visitor_props) else "insufficient_sample"
    match["operational_checks"] = checks
    after = (lineup.get("clave_local"), lineup.get("clave_visitante"), lineup.get("best_props"))
    return before != after


def _critical_matches(payload: dict, now_local: datetime) -> list[tuple[dict, float]]:
    out = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if -5 <= minutes <= CRITICAL_FROM_MIN:
            out.append((match, minutes))
    return sorted(out, key=lambda item: item[1])


def refresh_payload(payload: dict, now: datetime | None = None, football_client: ApiFootballClient | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    client = football_client or ApiFootballClient()
    critical = _critical_matches(payload, now_local)
    changed = False
    stats = {"critical_matches": len(critical), "media_checked": 0, "probable_refreshed": 0, "props_refreshed": 0}

    candidates = []
    for match, minutes in critical:
        lineup = match.get("alineacion") or {}
        # Props se recalculan también para un XI oficial que acaba de aparecer.
        if len(lineup.get("local") or []) == 11 and len(lineup.get("visitante") or []) == 11:
            if _refresh_props(payload, match, now_local, client):
                changed = True
                stats["props_refreshed"] += 1
        if lineup.get("status") == "confirmado" or not (CRITICAL_UNTIL_MIN <= minutes <= CRITICAL_FROM_MIN):
            continue
        age = _age_min(lineup.get("critical_probable_checked_at"), now_local)
        if age is not None and age < MEDIA_COOLDOWN_MIN:
            continue

        media = collect_probable_lineup_media(match.get("home", ""), match.get("away", ""), now_local, max_age_hours=24)
        media = _enrich_media(media)
        fingerprint = _media_fingerprint(media)
        stats["media_checked"] += 1
        lineup["critical_probable_checked_at"] = now_local.isoformat()
        lineup["critical_media_fingerprint"] = fingerprint
        match["alineacion"] = lineup
        changed = True

        # Si el XI ya está bien respaldado y no apareció nueva evidencia, no
        # gastamos una llamada de IA solo para repetir los mismos once nombres.
        previous_fp = lineup.get("critical_media_fingerprint_previous")
        generated_age = _age_min(lineup.get("critical_probable_generated_at"), now_local)
        needs_estimate = (
            lineup.get("status") != "probable"
            or fingerprint != previous_fp
            or generated_age is None
            or generated_age >= 30
        )
        lineup["critical_media_fingerprint_previous"] = fingerprint
        if not needs_estimate:
            continue
        evidence = _evidence_summary(match, media)
        candidates.append({
            "match": match,
            "partido": f"{match.get('home', '')} - {match.get('away', '')}",
            "window": f"T-{max(CRITICAL_UNTIL_MIN, int(round(minutes)))}m",
            "media": media,
            "stored_media": _stored_media(media),
            "evidence": evidence,
            "official_history": _official_history(payload.get("matches") or [], match),
        })

    results: dict[str, dict] = {}
    provider = model = None
    if candidates and available():
        response = chat(_prompt(candidates), max_tokens=3600, temperature=0.08, timeout=45)
        if response:
            raw = _extract_json(response.text) or []
            wanted = {_match_key(item["partido"]): item for item in candidates}
            for raw_item in raw:
                if not isinstance(raw_item, dict) or not _raw_positions_complete(raw_item):
                    continue
                key = _match_key(raw_item.get("partido", ""))
                if key not in wanted:
                    continue
                validated = _validate_item(raw_item)
                if validated:
                    results[key] = validated
            provider, model = response.provider, response.model

    for item in candidates:
        match = item["match"]
        result = results.get(_match_key(item["partido"]))
        if not result or not provider or not model:
            continue
        result = _reconcile_positions(result, item["official_history"])
        _apply_result(
            match,
            result,
            item["stored_media"],
            item["evidence"],
            now_local,
            provider,
            model,
            item["window"],
        )
        lineup = match.get("alineacion") or {}
        lineup["critical_probable_checked_at"] = now_local.isoformat()
        lineup["critical_probable_generated_at"] = now_local.isoformat()
        lineup["critical_media_fingerprint"] = _media_fingerprint(item["media"])
        lineup["critical_media_fingerprint_previous"] = lineup["critical_media_fingerprint"]
        match["alineacion"] = lineup
        changed = True
        stats["probable_refreshed"] += 1
        if _refresh_props(payload, match, now_local, client):
            stats["props_refreshed"] += 1

    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path=OUTPUT, now: datetime | None = None) -> tuple[bool, dict]:
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing"}
    candidate = deepcopy(previous)
    changed, stats = refresh_payload(candidate, now=now)
    if not changed:
        return False, stats
    ok, report = write_feed_safely(path, candidate, previous=previous)
    stats["feed_valid"] = bool(ok)
    stats["feed_issues"] = report.get("issues") or []
    return ok, stats


def main() -> int:
    ok, stats = run()
    print(json.dumps({"written": ok, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
