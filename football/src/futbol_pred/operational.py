"""Control operativo: onces oficiales, completitud y alertas del feed."""

from __future__ import annotations

from datetime import datetime
import re
import unicodedata
from zoneinfo import ZoneInfo

from .ingest.api_football import ApiFootballClient
from .ingest.lineups_ai import _best_props, _fallback_props, _formation

MADRID = ZoneInfo("Europe/Madrid")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _aware(parsed).astimezone(MADRID)


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _side_for(team: str, home: str, away: str) -> str | None:
    target = _key(team)
    if target and (target in _key(home) or _key(home) in target):
        return "local"
    if target and (target in _key(away) or _key(away) in target):
        return "visitante"
    return None


def attach_official_context(
    matches: list[dict], now: datetime, client: ApiFootballClient | None = None, limit: int = 8
) -> int:
    """Actualiza cada 15 min los partidos cercanos al inicio con el once oficial."""

    client = client or ApiFootballClient()
    if client.offline:
        return 0
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        delta = (kickoff - now_local).total_seconds()
        if -3 * 3600 <= delta <= 2 * 3600:
            candidates.append((kickoff, match))
    updated = 0
    for kickoff, match in sorted(candidates, key=lambda item: item[0])[:limit]:
        fixture = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
        fixture_id = ((fixture or {}).get("fixture") or {}).get("id")
        if not fixture_id:
            continue
        official = client.get_official_lineup(fixture_id)
        absences = client.get_absences(fixture_id)
        if not official:
            # Aunque el once aún no exista, las bajas oficiales mejoran el contexto.
            _merge_absences(match.get("alineacion") or {}, match, absences, now_local)
            continue
        by_side = {}
        for team in official:
            side = _side_for(team.get("team", ""), match.get("home", ""), match.get("away", ""))
            if side:
                by_side[side] = team
        if set(by_side) != {"local", "visitante"}:
            continue
        old = match.get("alineacion") or {}
        local = [row["name"] for row in by_side["local"]["starters"]]
        visitor = [row["name"] for row in by_side["visitante"]["starters"]]
        positions_local = [row["position"] for row in by_side["local"]["starters"]]
        positions_visitor = [row["position"] for row in by_side["visitante"]["starters"]]
        key_local = _starter_props(old.get("clave_local"), local, "home", match)
        key_visitor = _starter_props(old.get("clave_visitante"), visitor, "away", match)
        stamp = now_local.isoformat()
        lineup = {
            **old,
            "local": local,
            "visitante": visitor,
            "posiciones_local": positions_local,
            "posiciones_visitante": positions_visitor,
            "formacion_local": by_side["local"].get("formation") or _formation(positions_local),
            "formacion_visitante": by_side["visitante"].get("formation") or _formation(positions_visitor),
            "positions_inferred": False,
            "clave_local": key_local,
            "clave_visitante": key_visitor,
            "best_props": _best_props(key_local, key_visitor),
            "status": "confirmado",
            "provider": "API-Football",
            "model": "alineación oficial",
            "fuente": "API-Football · fixtures/lineups",
            "source_updated_at": stamp,
            "generated_at": stamp,
            "ts": stamp,
            "official_fixture_id": fixture_id,
            "quality": {
                "complete": True, "lineup_players": 22, "positions_players": 22,
                "props_players": len(key_local) + len(key_visitor), "score": 1.0,
                "official": True,
            },
        }
        _merge_absences(lineup, match, absences, now_local)
        match["alineacion"] = lineup
        updated += 1
    return updated


def _starter_props(existing: list[dict] | None, starters: list[str], side: str, match: dict) -> list[dict]:
    wanted = {_key(name) for name in starters}
    kept = [row for row in (existing or []) if _key(row.get("jugador")) in wanted]
    if len(kept) >= 3:
        return kept[:5]
    return _fallback_props(starters, side, match)


def _merge_absences(lineup: dict, match: dict, absences: list[dict], now: datetime) -> None:
    if not lineup or not absences:
        return
    for side, team in (("local", match.get("home", "")), ("visitante", match.get("away", ""))):
        rows = [dict(item, source_updated_at=now.isoformat()) for item in absences if _side_for(item.get("team", ""), team, "") == "local"]
        if rows:
            lineup[f"disponibilidad_{side}"] = rows
            lineup[f"bajas_{side}"] = [f"{row['jugador']} ({row['detalle']})" for row in rows]


def content_audit(matches: list[dict], players: dict | None, now: datetime) -> dict:
    """Comprueba solo los partidos del día y explica exactamente cada hueco."""

    today = _aware(now).astimezone(MADRID).date()
    team_players = set()
    for bucket in (players or {}).values():
        for row in bucket.get("players") or []:
            if row.get("team") and row.get("player"):
                team_players.add(_key(row["team"]))
    checked, incomplete = 0, []
    for match in matches:
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != today:
            continue
        checked += 1
        reasons = []
        if len(str(match.get("preview") or "").split()) < 90:
            reasons.append("previa")
        lineup = match.get("alineacion") or {}
        if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11:
            reasons.append("once")
        if len(lineup.get("posiciones_local") or []) != 11 or len(lineup.get("posiciones_visitante") or []) != 11:
            reasons.append("posiciones")
        if len(lineup.get("clave_local") or []) < 3 or len(lineup.get("clave_visitante") or []) < 3:
            reasons.append("props")
        if _key(match.get("home")) not in team_players or _key(match.get("away")) not in team_players:
            reasons.append("jugadores")
        if reasons:
            incomplete.append({"id": match.get("id"), "partido": f"{match.get('home')} - {match.get('away')}", "missing": reasons})
    return {
        "window": f"{_aware(now).astimezone(MADRID).hour:02d}:15" if _aware(now).astimezone(MADRID).hour in {0, 10} else "continuo",
        "checked_at": _aware(now).astimezone(MADRID).isoformat(),
        "matches_today": checked,
        "complete": checked - len(incomplete),
        "incomplete": incomplete,
        "status": "ok" if not incomplete else "warning",
    }


def annotate_prediction_context(matches: list[dict]) -> None:
    """Explica la confianza con factores observables, incluidas las bajas.

    Las bajas reducen la confianza si no hay una valoración fiable del impacto;
    no se falsea una corrección direccional de goles sin datos del jugador.
    """

    for match in matches:
        probs = match.get("probs")
        if not isinstance(probs, list) or len(probs) != 3:
            continue
        factors = [
            {"factor": "local/visitante", "impact": "incluido", "detail": "parámetros separados de ataque y defensa en casa/fuera"},
            {"factor": "fuerza del rival", "impact": "incluido", "detail": "Dixon-Coles contrastado con Elo"},
        ]
        trends = match.get("tendencias") or {}
        reasons = [row.get("reason") for row in trends.values() if isinstance(row, dict) and row.get("reason")]
        if reasons:
            factors.append({"factor": "forma y descanso", "impact": "incluido", "detail": reasons[0]})
        lineup = match.get("alineacion") or {}
        availability = (lineup.get("disponibilidad_local") or []) + (lineup.get("disponibilidad_visitante") or [])
        official_absences = sum(bool(row.get("official")) for row in availability if isinstance(row, dict))
        if availability:
            factors.append({
                "factor": "bajas y sanciones",
                "impact": "reduce confianza" if official_absences else "provisional",
                "detail": f"{len(availability)} incidencias; {official_absences} confirmadas por fuente oficial",
            })
        else:
            factors.append({"factor": "bajas y sanciones", "impact": "sin incidencias verificadas", "detail": "se actualizará cuando la fuente publique cambios"})
        components = (match.get("model_meta") or {}).get("components") or {}
        dc, elo = components.get("dixon_coles") or {}, components.get("elo") or {}
        disagreement = max((abs(float(dc.get(key, 0)) - float(elo.get(key, 0))) for key in ("1", "X", "2")), default=0)
        penalty = min(15, official_absences * 3 + (0 if lineup.get("status") == "confirmado" else 5))
        score = max(0, min(100, round(max(probs) + 35 - disagreement * 100 - penalty)))
        match["prediction_confidence"] = {
            "score": score,
            "level": "alta" if score >= 72 else "media" if score >= 55 else "baja",
            "model_disagreement_pp": round(disagreement * 100, 1),
            "availability_penalty_pp": penalty,
        }
        match["prediction_factors"] = factors


def build_alerts(previous: dict | None, audit: dict, ai_events: list[dict], now: datetime) -> list[dict]:
    alerts = []
    stamp = _aware(now).astimezone(MADRID).isoformat()
    if audit.get("incomplete"):
        alerts.append({
            "severity": "critical", "code": "today_content_incomplete",
            "message": f"{len(audit['incomplete'])} partido(s) del día siguen incompletos",
            "match_ids": [item["id"] for item in audit["incomplete"]], "at": stamp,
        })
    configured_failed = {event.get("provider") for event in ai_events if event.get("status") == "failed"}
    if {"Gemini", "Groq"}.issubset(configured_failed):
        alerts.append({
            "severity": "critical", "code": "all_ai_providers_failed",
            "message": "Fallaron Gemini y Groq; se conserva caché o cálculo local", "at": stamp,
        })
    elif configured_failed:
        alerts.append({
            "severity": "warning", "code": "ai_provider_failed",
            "message": f"Falló {', '.join(sorted(configured_failed))}; el fallback siguió activo", "at": stamp,
        })
    old_time = _parse((previous or {}).get("generated_at"))
    if old_time and (_aware(now).astimezone(MADRID) - old_time).total_seconds() > 2 * 3600:
        alerts.append({
            "severity": "warning", "code": "previous_feed_stale",
            "message": "El feed anterior tenía más de 2 horas de antigüedad", "at": stamp,
        })
    return alerts
