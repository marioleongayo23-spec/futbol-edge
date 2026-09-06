"""Cobertura operativa auditable del feed de Fútbol Edge.

Este módulo no inventa datos ni bloquea la publicación del feed. Clasifica qué
piezas deberían existir según la cercanía al saque inicial y deja visible si la
fuente fue comprobada, todavía no toca, está ausente o solo existe como
estimación. Se ejecuta después del pipeline pesado y del hot-refresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from .config import DATA_DIR

MADRID = ZoneInfo("Europe/Madrid")
OUTPUT = Path(DATA_DIR) / "dashboard.json"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse(value) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(value))).astimezone(MADRID)
    except (TypeError, ValueError):
        return None


def _key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _pending(value) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    return isinstance(value, str) and value.startswith("pendiente_")


def _item(state: str, required: bool, *, checked_at=None, source=None, detail=None) -> dict:
    out = {"state": state, "required": bool(required)}
    if checked_at:
        out["checked_at"] = checked_at
    if source:
        out["source"] = source
    if detail:
        out["detail"] = detail
    return out


def coverage_for_match(match: dict, now: datetime) -> dict | None:
    """Devuelve cobertura temporal estable para un partido del día.

    No incluye ``minutes_to_kickoff`` ni una marca de evaluación para evitar que
    el feed cambie cada diez minutos solo por el paso del tiempo. El estado solo
    cambia al cruzar una ventana operativa o cuando llega información real.
    """
    now_local = _aware(now).astimezone(MADRID)
    kickoff = _parse(match.get("kickoff"))
    if not kickoff or kickoff.date() != now_local.date():
        return None

    minutes = (kickoff - now_local).total_seconds() / 60
    lineup = match.get("alineacion") or {}
    checks = match.get("operational_checks") or {}
    status = str(lineup.get("status") or "sin confirmar").casefold()

    lineup_stamp = lineup.get("source_updated_at") or lineup.get("generated_at") or lineup.get("ts")
    weather = match.get("weather") or {}
    odds = match.get("odds")

    fixture_ok = bool(match.get("id") and match.get("status"))
    weather_ok = bool(weather)
    absences_ok = bool(checks.get("absences_checked_at")) and checks.get("absences_check_result") not in {"error", "unavailable", "failed"}
    probable_ok = (status in {"probable", "confirmado"}
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
        and lineup.get("source_quality") not in {"model_only", "statistical_fallback", "roster_grounded", "media_partial"})
    official_ok = (
        status == "confirmado"
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
    )
    odds_meta = odds.get("meta") or {} if isinstance(odds, dict) else {}
    one = (odds.get("1x2") or {}) if isinstance(odds, dict) else {}
    one = one if isinstance(one, dict) else {}
    prices = one.get("odds") or one
    prices = prices if isinstance(prices, dict) else {}
    odds_ok = all(isinstance(prices.get(k), (int, float)) and 1 < prices[k] < float("inf") for k in ("1", "X", "2"))

    weather_required = minutes <= 8 * 60
    absences_required = minutes <= 6 * 60
    probable_required = minutes <= 3 * 60
    official_required = minutes <= 45
    odds_required = minutes <= 24 * 60

    weather_result = checks.get("weather_check_result")
    absence_result = checks.get("absences_check_result")
    lineup_result = checks.get("lineup_check_result")

    items = {
        "fixture": _item(
            "ok" if fixture_ok else "missing",
            True,
            checked_at=checks.get("fixture_checked_at") or match.get("updatedAt"),
            source=match.get("source"),
            detail=checks.get("fixture_check_result") or ("calendario cargado" if fixture_ok else "sin partido verificable"),
        ),
        "weather": _item(
            "ok" if weather_ok else "scheduled" if not weather_required else "unavailable" if weather_result == "unavailable" else "missing",
            weather_required,
            checked_at=weather.get("source_updated_at") or checks.get("weather_checked_at"),
            source=weather.get("source") or ("Open-Meteo" if weather_ok else None),
            detail=weather_result or ("previsión disponible" if weather_ok else "ventana T−8h" if not weather_required else "sin previsión"),
        ),
        "absences": _item(
            "ok" if absences_ok else "scheduled" if not absences_required else "unavailable" if absence_result == "unavailable" else "missing",
            absences_required,
            checked_at=checks.get("absences_checked_at"),
            source="API-Football" if absences_ok else None,
            detail=absence_result or ("comprobado; 0 o más incidencias" if absences_ok else "ventana T−6h" if not absences_required else "sin comprobación"),
        ),
        "lineup_probable": _item(
            "ok" if probable_ok else "scheduled" if not probable_required else "estimated" if status == "estimado" else "missing",
            probable_required,
            checked_at=lineup_stamp,
            source=lineup.get("provider") or lineup.get("fuente"),
            detail=("XI respaldado por fuente" if probable_ok else "ventana T−3h" if not probable_required else "solo estimación" if status == "estimado" else "sin XI probable fiable"),
        ),
        "lineup_official": _item(
            "ok" if official_ok else "scheduled" if not official_required else "partial" if lineup_result in {"partial", "published"} else "waiting" if lineup_result == "not_published" else "missing",
            official_required,
            checked_at=checks.get("lineup_checked_at") or lineup.get("official_poll_at"),
            source="API-Football" if official_ok or checks.get("lineup_checked_at") else None,
            detail=("XI oficial 11+11" if official_ok else "ventana T−60/T−30" if not official_required else "respuesta parcial" if lineup_result in {"partial", "published"} else "aún no publicado" if lineup_result == "not_published" else "sin comprobación oficial"),
        ),
        "odds": _item(
            "ok" if odds_ok else "scheduled" if not odds_required else "missing",
            odds_required,
            source=odds_meta.get("provider") or (odds.get("source") if isinstance(odds, dict) else None),
            checked_at=odds_meta.get("source_updated_at") or odds_meta.get("checked_at"),
            detail="cuotas reales disponibles" if odds_ok else "se exige en las 24 h previas" if odds_required else "fuera de ventana",
        ),
    }

    # Review timestamps are source specific: regenerating the feed cannot
    # turn an old observation into a fresh one. Unknown timestamps stay
    # explicit; only dated evidence can be classified as expired.
    ttl_hours = {"weather": 12, "absences": 12, "lineup_probable": 24, "odds": 6}
    for key, ttl in ttl_hours.items():
        item = items[key]
        stamp = _parse(item.get("checked_at"))
        if item["state"] == "ok" and stamp is not None:
            age = (now_local - stamp).total_seconds() / 3600
            if age > ttl or age < -0.25:
                item["state"] = "stale"
                item["detail"] = "fecha de fuente fuera de la ventana de frescura"
        item["freshness_known"] = stamp is not None
        item["ttl_hours"] = ttl

    missing_required = [
        key for key, value in items.items()
        if value["required"] and value["state"] != "ok"
    ]
    return {
        "schema_version": 2,
        "complete": not missing_required,
        "items": items,
        "missing_required": missing_required,
    }


_MISSING_LABELS = {
    "weather": "clima",
    "absences": "bajas",
    "lineup_probable": "once_probable",
    "lineup_official": "once_oficial",
    "odds": "cuotas",
    "fixture": "partido",
}


def _team_players(payload: dict) -> set[str]:
    out: set[str] = set()
    for bucket in (payload.get("players") or {}).values():
        if not isinstance(bucket, dict):
            continue
        for row in bucket.get("players") or []:
            if isinstance(row, dict) and row.get("team") and row.get("player"):
                out.add(_key(row["team"]))
    return out


def _structural_missing(match: dict, players: set[str]) -> list[str]:
    reasons: list[str] = []
    if len(str(match.get("preview") or "").split()) < 90:
        reasons.append("previa")
    lineup = match.get("alineacion") or {}
    if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11:
        reasons.append("once")
    if len(lineup.get("posiciones_local") or []) != 11 or len(lineup.get("posiciones_visitante") or []) != 11:
        reasons.append("posiciones")
    if _key(match.get("home")) not in players or _key(match.get("away")) not in players:
        reasons.append("jugadores")
    return reasons


def enrich_payload(payload: dict, now: datetime | None = None) -> bool:
    """Añade la matriz por partido y recalcula la auditoría del día.

    Devuelve ``True`` únicamente si cambia contenido semántico. La marca
    ``checked_at`` del audit se conserva cuando el estado sigue idéntico, para
    que el cron ligero no publique commits vacíos por el reloj.
    """
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    players = _team_players(payload)
    matches_today = []
    incomplete = []
    summary: dict[str, dict[str, int]] = {}
    changed = False

    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        coverage = coverage_for_match(match, now_local)
        if coverage is None:
            continue
        matches_today.append(match)
        if match.get("coverage") != coverage:
            match["coverage"] = coverage
            changed = True

        reasons = _structural_missing(match, players)
        operational = [_MISSING_LABELS[key] for key in coverage["missing_required"]]
        if "once" in reasons:
            operational = [item for item in operational if item not in {"once_probable", "once_oficial"}]
        reasons.extend(item for item in operational if item not in reasons)
        if reasons:
            incomplete.append({
                "id": match.get("id"),
                "partido": f"{match.get('home')} - {match.get('away')}",
                "missing": reasons,
            })

        for key, item in coverage["items"].items():
            bucket = summary.setdefault(key, {})
            bucket[item["state"]] = bucket.get(item["state"], 0) + 1

    previous = payload.get("content_audit") if isinstance(payload.get("content_audit"), dict) else {}
    core = {
        "matches_today": len(matches_today),
        "complete": len(matches_today) - len(incomplete),
        "incomplete": incomplete,
        "status": "ok" if not incomplete else "warning",
        "coverage_summary": summary,
    }
    previous_core = {key: previous.get(key) for key in core}
    audit = {**previous, **core}
    if previous_core != core:
        audit["checked_at"] = now_local.isoformat()
        audit["window"] = "continuo"
    else:
        audit.setdefault("checked_at", now_local.isoformat())
        audit.setdefault("window", "continuo")

    if payload.get("content_audit") != audit:
        payload["content_audit"] = audit
        changed = True
    return changed


def run(path: Path = OUTPUT, now: datetime | None = None) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    changed = enrich_payload(payload, now=now)
    if changed:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    changed = run()
    print(json.dumps({"coverage_changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
