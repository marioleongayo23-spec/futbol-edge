"""Base automática de XI desde el último partido oficial.

Regla de publicación para cualquier próximo partido:
- XI oficial del partido actual > probable respaldado por medios > híbrido
  (lado con prensa + lado sin prensa desde el último XI oficial) > último XI
  oficial de ambos equipos.
- Gemini/IA nunca es la fuente base de jugadores.
- si una baja/sanción oficial afecta al último XI, se sustituye con continuidad
  de XI oficiales recientes, priorizando la misma posición/línea.
- si el feed aún no guardó el último XI oficial, se intenta backfill de
  API-Football y se cachea en el partido histórico para no repetir llamadas.

Este módulo es determinista salvo el backfill de la fuente oficial. Se ejecuta
antes y después del recolector de probables: primero evita huecos y después
impide que una salida model-only vuelva a tapar una base oficial válida.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _filter_props, _official_by_side, _parse
from .ingest.api_football import ApiFootballClient
from .matchday_lineup_integrity import _dedupe_availability, _repair_side
from .prefinal_lineups import _official_history, _same_team

OUTPUT = DATA_DIR / "dashboard.json"
HORIZON_DAYS = 7
MAX_BACKFILL_FIXTURES = 24
API_RESERVE = 20
FINISHED = {"FT", "AET", "PEN", "AWD", "FINISHED", "AWARDED"}


def _key(value) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _is_finished(match: dict) -> bool:
    return bool(match.get("finished")) or str(match.get("status") or "").upper() in FINISHED


def _eligible_target(match: dict, now_local: datetime) -> bool:
    if not isinstance(match, dict) or _is_finished(match):
        return False
    kickoff = _parse(match.get("kickoff"))
    if not kickoff:
        return False
    return now_local - timedelta(minutes=5) <= kickoff <= now_local + timedelta(days=HORIZON_DAYS)


def _latest_finished_match(matches: list[dict], target: dict, team: str) -> dict | None:
    target_kickoff = _parse(target.get("kickoff"))
    candidates = []
    for match in matches:
        if match is target or not isinstance(match, dict) or not _is_finished(match):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or (target_kickoff and kickoff >= target_kickoff):
            continue
        if not (_same_team(match.get("home"), team) or _same_team(match.get("away"), team)):
            continue
        candidates.append((kickoff, match))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else None


def _has_official_xi(match: dict | None) -> bool:
    if not isinstance(match, dict):
        return False
    lineup = match.get("alineacion") or {}
    return (
        lineup.get("status") == "confirmado"
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
        and len(lineup.get("posiciones_local") or []) == 11
        and len(lineup.get("posiciones_visitante") or []) == 11
    )


def _fixture_id(match: dict) -> int | None:
    for value in (
        match.get("api_football_fixture_id"),
        (match.get("alineacion") or {}).get("official_fixture_id"),
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _remaining(payload: dict) -> int | None:
    try:
        return int(((payload.get("source_health") or {}).get("api_football") or {}).get("daily_remaining"))
    except (TypeError, ValueError):
        return None


def _store_historical_official(match: dict, official: list[dict], fixture_id: int, now_local: datetime) -> bool:
    sides = _official_by_side(official or [], match)
    if set(sides) != {"local", "visitante"}:
        return False
    local_rows = sides["local"].get("starters") or []
    visitor_rows = sides["visitante"].get("starters") or []
    if len(local_rows) != 11 or len(visitor_rows) != 11:
        return False
    local = [row.get("name") for row in local_rows]
    visitor = [row.get("name") for row in visitor_rows]
    if not all(local) or not all(visitor):
        return False
    positions_local = [row.get("position") or "" for row in local_rows]
    positions_visitor = [row.get("position") or "" for row in visitor_rows]
    old = dict(match.get("alineacion") or {})
    stamp = now_local.isoformat()
    match["api_football_fixture_id"] = fixture_id
    match["alineacion"] = {
        **old,
        "local": local,
        "visitante": visitor,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_visitor,
        "formacion_local": sides["local"].get("formation") or old.get("formacion_local"),
        "formacion_visitante": sides["visitante"].get("formation") or old.get("formacion_visitante"),
        "positions_inferred": False,
        "status": "confirmado",
        "phase": "historical_final",
        "lineup_kind": "official",
        "source_quality": "official",
        "provider": "API-Football",
        "model": "alineación oficial",
        "fuente": "API-Football · backfill último partido oficial",
        "official_fixture_id": fixture_id,
        "official_backfill_at": stamp,
        "source_updated_at": stamp,
        "quality": {
            **(old.get("quality") or {}),
            "complete": True,
            "official": True,
            "lineup_players": 22,
            "positions_players": 22,
        },
    }
    return True


def _backfill_missing_history(payload: dict, targets: list[dict], now_local: datetime, client: ApiFootballClient) -> dict:
    stats = {"requested": 0, "resolved": 0, "fixture_not_found": 0, "lineup_not_found": 0}
    if client.offline:
        stats["skipped"] = "offline"
        return stats

    matches = payload.get("matches") or []
    wanted = []
    seen = set()
    for target in targets:
        history = _official_history(matches, target)
        for side, team in (("local", target.get("home")), ("visitante", target.get("away"))):
            if history.get(side):
                continue
            previous = _latest_finished_match(matches, target, str(team or ""))
            if previous is None or _has_official_xi(previous):
                continue
            key = str(previous.get("id") or f"{previous.get('home')}|{previous.get('away')}|{previous.get('kickoff')}")
            if key not in seen:
                seen.add(key)
                wanted.append(previous)

    remaining = _remaining(payload)
    budget = MAX_BACKFILL_FIXTURES if remaining is None else max(0, min(MAX_BACKFILL_FIXTURES, remaining - API_RESERVE))
    if budget <= 0:
        stats["skipped"] = "quota_reserved"
        return stats

    for previous in wanted[:budget]:
        stats["requested"] += 1
        fixture_id = _fixture_id(previous)
        if fixture_id is None:
            kickoff = _parse(previous.get("kickoff"))
            raw = client.find_fixture(previous.get("home", ""), previous.get("away", ""), kickoff) if kickoff else None
            try:
                fixture_id = int((((raw or {}).get("fixture") or {}).get("id")))
            except (TypeError, ValueError):
                fixture_id = None
        if fixture_id is None:
            stats["fixture_not_found"] += 1
            continue
        official = client.get_official_lineup(fixture_id)
        if not _store_historical_official(previous, official, fixture_id, now_local):
            stats["lineup_not_found"] += 1
            continue
        stats["resolved"] += 1
    return stats


def _best_props_for(names: list[str], rows: list[dict]) -> list[dict]:
    allowed = {_key(name) for name in names}
    return [row for row in rows or [] if _key(row.get("jugador")) in allowed]


def _semantic(lineup: dict) -> tuple:
    return (
        tuple(lineup.get("local") or []),
        tuple(lineup.get("visitante") or []),
        tuple(lineup.get("posiciones_local") or []),
        tuple(lineup.get("posiciones_visitante") or []),
        lineup.get("status"),
        lineup.get("lineup_kind"),
        lineup.get("source_quality"),
        tuple((row.get("side"), row.get("out"), row.get("in"), row.get("resolved")) for row in lineup.get("integrity_replacements") or []),
    )


def _current_is_fully_grounded(lineup: dict) -> bool:
    return (
        lineup.get("status") == "confirmado"
        or lineup.get("source_quality") == "media_grounded"
        or lineup.get("lineup_kind") == "source_grounded_probable"
    )


def _grounded_sides(lineup: dict) -> set[str]:
    evidence = lineup.get("lineup_evidence") or {}
    out = set()
    for side in ("local", "visitante"):
        if bool((evidence.get(side) or {}).get("grounded")):
            out.add(side)
    return out


def _materialize_baseline(matches: list[dict], match: dict, now_local: datetime) -> tuple[bool, str]:
    current = dict(match.get("alineacion") or {})
    if _current_is_fully_grounded(current):
        return False, "preserved_grounded"

    history = _official_history(matches, match)
    if not history.get("local") or not history.get("visitante"):
        return False, "missing_history"
    local_hist = history["local"][0]
    visitor_hist = history["visitante"][0]
    base_local = list(local_hist.get("players") or [])
    base_visitor = list(visitor_hist.get("players") or [])
    base_pos_local = list(local_hist.get("positions") or [])
    base_pos_visitor = list(visitor_hist.get("positions") or [])
    if not (len(base_local) == len(base_visitor) == len(base_pos_local) == len(base_pos_visitor) == 11):
        return False, "invalid_history"

    grounded = _grounded_sides(current)
    has_partial = (
        current.get("source_quality") in {"media_partial", "official_history_hybrid", "official_history_hybrid_adjusted"}
        or current.get("lineup_kind") in {"partially_grounded_estimate", "source_grounded_plus_last_official"}
    ) and bool(grounded)

    local = base_local
    visitor = base_visitor
    pos_local = base_pos_local
    pos_visitor = base_pos_visitor
    if has_partial and "local" in grounded and len(current.get("local") or []) == 11:
        local = list(current["local"])
        if len(current.get("posiciones_local") or []) == 11:
            pos_local = list(current["posiciones_local"])
    if has_partial and "visitante" in grounded and len(current.get("visitante") or []) == 11:
        visitor = list(current["visitante"])
        if len(current.get("posiciones_visitante") or []) == 11:
            pos_visitor = list(current["posiciones_visitante"])

    stamp = now_local.isoformat()
    all_names = local + visitor
    local_props = _filter_props(current.get("clave_local"), local)
    visitor_props = _filter_props(current.get("clave_visitante"), visitor)
    if has_partial:
        source_quality = "official_history_hybrid"
        lineup_kind = "source_grounded_plus_last_official"
        provider = current.get("provider") or "Medios recientes + último XI oficial"
        model = current.get("model") or "continuidad-oficial-v1"
        grounded_label = "local" if grounded == {"local"} else "visitante" if grounded == {"visitante"} else "+".join(sorted(grounded))
        fuente = f"Híbrido automático: evidencia reciente {grounded_label} + último XI oficial del lado sin evidencia"
        warning = "XI híbrido: se actualiza el equipo respaldado por fuente reciente y se mantiene el último XI oficial del otro equipo."
    else:
        source_quality = "official_history_baseline"
        lineup_kind = "last_official_baseline"
        provider = "Último XI oficial"
        model = "continuidad-oficial-v1"
        fuente = "Último XI oficial disponible de cada equipo · pendiente de probable actualizado"
        warning = "Base provisional: último XI oficial disponible; se sustituirá automáticamente cuando aparezca un probable fiable o el XI oficial."

    merged = {
        **current,
        "local": local,
        "visitante": visitor,
        "posiciones_local": pos_local,
        "posiciones_visitante": pos_visitor,
        "clave_local": local_props,
        "clave_visitante": visitor_props,
        "best_props": _best_props_for(all_names, current.get("best_props") or []),
        "status": "estimado",
        "phase": "rolling_baseline",
        "lineup_kind": lineup_kind,
        "source_quality": source_quality,
        "provider": provider,
        "model": model,
        "fuente": fuente,
        "display_warning": warning,
        "position_source": "official_history",
        "baseline_sources": {
            "local": {"kickoff": local_hist.get("kickoff"), "source": "último XI oficial"},
            "visitante": {"kickoff": visitor_hist.get("kickoff"), "source": "último XI oficial"},
        },
        "baseline_policy": "official_current > media_grounded > hybrid > last_official",
        "numeric_props_source": current.get("numeric_props_source") if (local_props or visitor_props) else "pending_real_data",
    }
    _dedupe_availability(merged)
    replacements = []
    replacements.extend(_repair_side(matches, match, merged, "local"))
    replacements.extend(_repair_side(matches, match, merged, "visitante"))
    if replacements:
        merged["integrity_replacements"] = replacements
        merged["integrity_checked_at"] = stamp
        if has_partial:
            merged["source_quality"] = "official_history_hybrid_adjusted"
            merged["lineup_kind"] = "source_grounded_plus_last_official_adjusted"
        else:
            merged["source_quality"] = "official_history_baseline_adjusted"
            merged["lineup_kind"] = "last_official_baseline_adjusted"
        merged["display_warning"] = (
            "Base de último XI oficial ajustada automáticamente por lesión/sanción oficial con continuidad de partidos recientes."
            if all(row.get("resolved") for row in replacements)
            else "Base de último XI oficial saneada por bajas oficiales; queda al menos una posición por confirmar."
        )

    before = _semantic(current)
    after = _semantic(merged)
    if before == after and current.get("baseline_sources") == merged.get("baseline_sources"):
        return False, "unchanged"
    merged["source_updated_at"] = stamp
    merged["generated_at"] = stamp
    merged["ts"] = stamp
    quality = dict(merged.get("quality") or {})
    quality.update({
        "complete": len(merged.get("local") or []) == 11 and len(merged.get("visitante") or []) == 11,
        "lineup_players": len(merged.get("local") or []) + len(merged.get("visitante") or []),
        "positions_players": len(merged.get("posiciones_local") or []) + len(merged.get("posiciones_visitante") or []),
        "official": False,
        "baseline_from_official_history": True,
    })
    merged["quality"] = quality
    match["alineacion"] = merged
    match["updatedAt"] = stamp
    return True, "hybrid" if has_partial else "baseline"


def refresh_payload(payload: dict, now: datetime | None = None, client: ApiFootballClient | None = None):
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    matches = payload.get("matches") or []
    targets = [match for match in matches if _eligible_target(match, now_local)]
    client = client or ApiFootballClient()
    backfill = _backfill_missing_history(payload, targets, now_local, client)

    changed = bool(backfill.get("resolved"))
    stats = {
        "targets": len(targets),
        "baseline": 0,
        "hybrid": 0,
        "preserved_grounded": 0,
        "missing_history": 0,
        "unchanged": 0,
        "backfill": backfill,
    }
    for match in sorted(targets, key=lambda row: _parse(row.get("kickoff")) or now_local):
        item_changed, result = _materialize_baseline(matches, match, now_local)
        changed = changed or item_changed
        if result in stats:
            stats[result] += 1
        elif result == "baseline":
            stats["baseline"] += 1
        elif result == "hybrid":
            stats["hybrid"] += 1
        elif result in {"missing_history", "invalid_history"}:
            stats["missing_history"] += 1

    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path=OUTPUT, now: datetime | None = None):
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
