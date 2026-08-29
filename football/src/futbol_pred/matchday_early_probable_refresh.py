"""Preparación temprana de XI probable y props desde T-24h.

El refresco crítico T-2h sigue siendo la autoridad cerca del kickoff. Esta capa
empieza a buscar señales de alineación desde el día anterior para que la app vaya
cambiando automáticamente en cuanto aparezcan novedades:

- sincroniza primero la plantilla registrada ACTUAL de cada equipo próximo;
- T-24h .. T-8h: revisa probable como máximo cada 120 min;
- T-8h .. T-4h: revisa probable como máximo cada 45 min;
- T-4h .. T-2h: revisa probable como máximo cada 20 min;
- reutiliza el estimador/media/continuidad del refresco T-2h;
- completa props predictivas si ya existe un XI de 11+11;
- el baseline autoritativo posterior evita que una salida model-only sustituya
  al último XI oficial cuando todavía no hay evidencia externa nueva.

No convierte una estimación temprana en XI oficial ni la etiqueta como certeza.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, OUTPUT, _aware, _parse
from . import matchday_probable_refresh as probable
from . import matchday_player_props_fill as props_fill
from . import matchday_current_squads as current_squads

EARLY_FROM_MIN = 24 * 60
EARLY_TO_MIN = 120


def _cooldown(minutes_to_kickoff: float) -> int:
    if minutes_to_kickoff > 8 * 60:
        return 120
    if minutes_to_kickoff > 4 * 60:
        return 45
    return 20


def _eligible(match: dict, now_local: datetime) -> tuple[bool, float]:
    if not isinstance(match, dict) or match.get("finished"):
        return False, 0.0
    kickoff = _parse(match.get("kickoff"))
    if not kickoff:
        return False, 0.0
    minutes = (kickoff - now_local).total_seconds() / 60.0
    return EARLY_TO_MIN < minutes <= EARLY_FROM_MIN, minutes


def _refresh_one(payload: dict, match: dict, now_local: datetime, minutes: float, client) -> tuple[bool, dict]:
    old_from = probable.CRITICAL_FROM_MIN
    old_until = probable.CRITICAL_UNTIL_MIN
    old_cooldown = probable.MEDIA_COOLDOWN_MIN
    old_props_from = props_fill.FROM_MIN
    try:
        probable.CRITICAL_FROM_MIN = EARLY_FROM_MIN
        probable.CRITICAL_UNTIL_MIN = EARLY_TO_MIN
        probable.MEDIA_COOLDOWN_MIN = _cooldown(minutes)
        props_fill.FROM_MIN = EARLY_FROM_MIN

        mini = {
            "matches": [match],
            "players": payload.get("players") or {},
            "source_health": payload.get("source_health") or {},
            "generated_at": payload.get("generated_at"),
        }
        p_changed, p_stats = probable.refresh_payload(mini, now=now_local, football_client=client)
        f_changed, f_stats = props_fill.refresh_payload(mini, now=now_local)
        return bool(p_changed or f_changed), {
            "media_checked": int(p_stats.get("media_checked") or 0),
            "probable_refreshed": int(p_stats.get("probable_refreshed") or 0),
            "props_refreshed": int(p_stats.get("props_refreshed") or 0),
            "covered_players": int(f_stats.get("covered_players") or 0),
            "real_players": int(f_stats.get("real_players") or 0),
            "model_players": int(f_stats.get("model_players") or 0),
        }
    finally:
        probable.CRITICAL_FROM_MIN = old_from
        probable.CRITICAL_UNTIL_MIN = old_until
        probable.MEDIA_COOLDOWN_MIN = old_cooldown
        props_fill.FROM_MIN = old_props_from


def refresh_payload(payload: dict, now: datetime | None = None, football_client=None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    client = football_client or probable.ApiFootballClient()

    # Compatibilidad operativa: incluso un heartbeat arrancado con una versión
    # anterior del YAML ejecuta este módulo en cada ciclo. Sincronizar aquí la
    # plantilla actual hace que la purga de jugadores antiguos entre en vigor en
    # el siguiente tick, sin esperar a que termine el bloque de Actions anterior.
    roster_changed, roster_stats = current_squads.refresh_payload(
        payload, now=now_local, football_client=client
    )

    candidates = []
    for match in payload.get("matches") or []:
        ok, minutes = _eligible(match, now_local)
        if ok:
            candidates.append((match, minutes))

    stats = {
        "early_matches": len(candidates),
        "media_checked": 0,
        "probable_refreshed": 0,
        "props_refreshed": 0,
        "covered_players": 0,
        "real_players": 0,
        "model_players": 0,
        "current_squads": roster_stats,
    }
    changed = bool(roster_changed)
    for match, minutes in sorted(candidates, key=lambda item: item[1]):
        item_changed, item_stats = _refresh_one(payload, match, now_local, minutes, client)
        changed = changed or item_changed
        for key in ("media_checked", "probable_refreshed", "props_refreshed", "covered_players", "real_players", "model_players"):
            stats[key] += int(item_stats.get(key) or 0)

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
