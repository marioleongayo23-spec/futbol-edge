"""Control operativo: onces oficiales, completitud y alertas del feed."""
from __future__ import annotations

from datetime import datetime
import re
import unicodedata
from zoneinfo import ZoneInfo

from .ingest.api_football import ApiFootballClient
from .ingest.api_football_players import fetch_team_player_rates, props_for_official_starters
from .ingest.lineups_ai import _best_props, _formation
from .model.state_simulator import simulate_match_states

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
        value = int(match.get("season"))
        if 2000 <= value <= 2100:
            return value
    except (TypeError, ValueError):
        pass
    local = _aware(kickoff).astimezone(MADRID)
    return local.year if local.month >= 7 else local.year - 1


def _real_starter_props(client, match, team_name, starters, kickoff):
    try:
        rates = fetch_team_player_rates(
            client, team_name, _season_for(match, kickoff), _league_id(match), max_pages=2
        )
        props = props_for_official_starters(starters, rates, limit=11)
    except Exception:
        return None
    return props if len(props) >= 3 else None


def _official_poll_window(minutes_to_kickoff: float, attempts: dict) -> str | None:
    """Ventanas de publicación del XI: primero T-60 y fallback T-30."""
    if 45 <= minutes_to_kickoff <= 75 and not attempts.get("T-60"):
        return "T-60"
    if 15 <= minutes_to_kickoff < 45 and not attempts.get("T-30"):
        return "T-30"
    return None


def attach_official_context(matches: list[dict], now: datetime, client: ApiFootballClient | None = None, limit: int = 8, stats_models: dict[str, object] | None = None) -> int:
    """Busca el XI oficial en T-60 y, si aún no existe, reintenta en T-30."""
    client = client or ApiFootballClient()
    if client.offline:
        return 0
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes_to_kickoff = (kickoff - now_local).total_seconds() / 60
        if minutes_to_kickoff <= 0:
            continue
        lineup = match.get("alineacion") or {}
        if (
            lineup.get("status") == "confirmado"
            and len(lineup.get("local") or []) == 11
            and len(lineup.get("visitante") or []) == 11
        ):
            continue
        attempts = dict(lineup.get("official_poll_windows") or {})
        poll_window = _official_poll_window(minutes_to_kickoff, attempts)
        if not poll_window:
            continue
        candidates.append((kickoff, match, poll_window))

    resolved = []
    for kickoff, match, poll_window in sorted(candidates, key=lambda item: item[0])[:limit]:
        fixture = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
        fixture_id = ((fixture or {}).get("fixture") or {}).get("id")
        if fixture_id:
            resolved.append((kickoff, match, poll_window, int(fixture_id), fixture))
    details = client.get_fixture_details([item[3] for item in resolved]) if hasattr(client, "get_fixture_details") else {}
    updated = 0
    for kickoff, match, poll_window, fixture_id, fixture in resolved:
        detail = details.get(fixture_id) or fixture
        official = client.lineup_from_fixture(detail) if hasattr(client, "lineup_from_fixture") and details else client.get_official_lineup(fixture_id)
        absences = client.get_absences(fixture_id)
        old = match.get("alineacion") or {}
        attempts = dict(old.get("official_poll_windows") or {})
        attempts[poll_window] = now_local.isoformat()
        old["official_poll_windows"] = attempts
        old["official_poll_at"] = now_local.isoformat()  # compatibilidad con feeds previos
        old["official_poll_window_last_attempt"] = poll_window
        match["alineacion"] = old
        if hasattr(client, "fixture_context"):
            official_context = client.fixture_context(detail)
            if official_context:
                official_context["source_updated_at"] = now_local.isoformat()
                official_context["official_poll_window"] = poll_window
                stats_model = (stats_models or {}).get(match.get("league"))
                referee_model = getattr(stats_model, "referee_model", None)
                referee = official_context.get("referee")
                if referee_model is not None and referee:
                    try:
                        profile = referee_model.context(referee)
                        if profile:
                            official_context["referee_profile"] = profile
                        adjusted, applied = referee_model.adjust_stats(match.get("stats"), referee)
                        if applied:
                            match["stats"] = adjusted
                            official_context["referee_adjustment_applied"] = applied
                    except Exception:
                        pass
                match["official_context"] = official_context
        if not official:
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
        if len(local) != 11 or len(visitor) != 11:
            continue
        real_local = _real_starter_props(client, match, match.get("home", ""), local, kickoff)
        real_visitor = _real_starter_props(client, match, match.get("away", ""), visitor, kickoff)
        key_local = real_local or []
        key_visitor = real_visitor or []
        real_count = len(key_local) + len(key_visitor)
        props_source = (
            f"API-Football · players ({real_count}/22 con muestra)"
            if real_count else "sin datos reales suficientes"
        )
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
            "phase": "final",
            "provider": "API-Football",
            "model": "alineación oficial",
            "fuente": f"API-Football · fixtures/lineups · {poll_window}",
            "official_poll_window": poll_window,
            "player_props_source": props_source,
            "numeric_props_source": "API-Football · players" if real_count else "pending_real_data",
            "source_updated_at": stamp,
            "generated_at": stamp,
            "ts": stamp,
            "official_fixture_id": fixture_id,
            "quality": {
                "complete": True,
                "lineup_players": 22,
                "positions_players": 22,
                "props_players": len(key_local) + len(key_visitor),
                "score": 1.0,
                "official": True,
                "official_poll_window": poll_window,
                "real_player_props": real_count,
                "player_props_source": props_source,
            },
        }
        _merge_absences(lineup, match, absences, now_local)
        match["alineacion"] = lineup
        updated += 1
    return updated



def _merge_absences(lineup: dict, match: dict, absences: list[dict], now: datetime) -> None:
    if not lineup or not absences:
        return
    for side, team in (("local", match.get("home", "")), ("visitante", match.get("away", ""))):
        rows = [dict(item, source_updated_at=now.isoformat()) for item in absences if _side_for(item.get("team", ""), team, "") == "local"]
        if rows:
            lineup[f"disponibilidad_{side}"] = rows
            lineup[f"bajas_{side}"] = [f"{row['jugador']} ({row['detalle']})" for row in rows]


def content_audit(matches: list[dict], players: dict | None, now: datetime) -> dict:
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


def _lineup_side_impact(lineup: dict, side: str) -> dict:
    props = [row for row in lineup.get(f"clave_{side}") or [] if isinstance(row, dict)]
    availability = [row for row in lineup.get(f"disponibilidad_{side}") or [] if isinstance(row, dict)]
    minutes = [float(row.get("min")) for row in props if row.get("min") is not None]
    starts = [float(row.get("tit")) for row in props if row.get("tit") is not None]
    attack_scores = []
    for row in props:
        try:
            minutes_weight = min(1.0, max(0.0, float(row.get("min", 0))) / 90)
            start_weight = min(1.0, max(0.0, float(row.get("tit", 0))))
            production = 3 * float(row.get("g", 0)) + 2 * float(row.get("a", 0)) + float(row.get("r", 0)) + 1.5 * float(row.get("rp", 0))
            attack_scores.append(production * minutes_weight * start_weight)
        except (TypeError, ValueError):
            continue
    absence_penalty = 0.0
    official_absences = 0
    for row in availability:
        state = str(row.get("estado") or "").casefold()
        official = bool(row.get("official"))
        official_absences += int(official)
        weight = 1.5 if "duda" in state or "doubt" in state else 2.0
        if "sanc" in state or "susp" in state:
            weight = 3.0
        elif "les" in state or "injur" in state:
            weight = 3.0
        elif "rota" in state:
            weight = 1.0
        absence_penalty += weight if official else weight * 0.35
    return {
        "key_players": len(props),
        "expected_minutes_avg": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "starter_probability_avg_pct": round(100 * sum(starts) / len(starts)) if starts else None,
        "attack_presence_index": round(sum(attack_scores), 2) if attack_scores else None,
        "listed_absences": len(availability),
        "official_absences": official_absences,
        "confidence_penalty_pp": round(min(12.0, absence_penalty), 1),
    }


def lineup_impact(lineup: dict) -> dict:
    home = _lineup_side_impact(lineup, "local")
    away = _lineup_side_impact(lineup, "visitante")
    status = lineup.get("status") or "estimado"
    status_penalty = {"confirmado": 0, "probable": 2, "estimado": 5}.get(status, 5)
    evidence = "alta" if status == "confirmado" else "media" if status == "probable" else "baja"
    total_penalty = min(20.0, status_penalty + home["confidence_penalty_pp"] + away["confidence_penalty_pp"])
    attack_edge = None
    if home["attack_presence_index"] is not None and away["attack_presence_index"] is not None:
        attack_edge = round(home["attack_presence_index"] - away["attack_presence_index"], 2)
    return {
        "status": status,
        "evidence": evidence,
        "home": home,
        "away": away,
        "attack_presence_edge": attack_edge,
        "confidence_penalty_pp": round(total_penalty, 1),
        "probability_adjustment": "not_applied",
        "method": "minutos × probabilidad de titularidad × producción observada; las bajas oficiales penalizan confianza. No altera el 1X2 sin validación histórica.",
    }


def attach_state_simulations(matches: list[dict]) -> int:
    attached = 0
    for match in matches:
        xg = match.get("xg")
        if match.get("finished") or not isinstance(xg, list) or len(xg) != 2:
            continue
        try:
            temperature = (match.get("weather") or {}).get("temperature_c")
            yellows = ((match.get("stats") or {}).get("yellows") or {}).get("total")
            match["state_simulation"] = simulate_match_states(
                float(xg[0]), float(xg[1]), seed=match.get("id") or match.get("kickoff") or "match",
                temperature_c=float(temperature) if temperature is not None else None,
                expected_yellows=float(yellows) if yellows is not None else None,
            )
            attached += 1
        except (TypeError, ValueError):
            continue
    return attached


def annotate_prediction_context(matches: list[dict]) -> None:
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
        tactical = match.get("tactical_matchup") or {}
        tactical_reliability = tactical.get("reliability")
        if tactical:
            factors.append({
                "factor": "ataque vs defensa",
                "impact": "incluido como contexto",
                "detail": "; ".join(tactical.get("notes") or []) + f" · fiabilidad {tactical_reliability or 'sin clasificar'}",
            })
        weather = match.get("weather") or {}
        heat = weather.get("heat_stress") or {}
        if weather:
            factors.append({
                "factor": "clima",
                "impact": "reduce confianza" if heat.get("level") == "alto" else "monitorizado",
                "detail": f"{weather.get('temperature_c')} °C, sensación {weather.get('apparent_temperature_c')} °C, viento {weather.get('wind_kmh')} km/h · estrés térmico {heat.get('level')}",
            })
        else:
            factors.append({"factor": "clima", "impact": "pendiente", "detail": "se captura en las revisiones 00:15 y 10:15 para partidos del día"})
        lineup = match.get("alineacion") or {}
        availability = (lineup.get("disponibilidad_local") or []) + (lineup.get("disponibilidad_visitante") or [])
        official_absences = sum(bool(row.get("official")) for row in availability if isinstance(row, dict))
        impact = lineup_impact(lineup) if lineup else None
        if impact:
            match["lineup_impact"] = impact
        if lineup.get("player_props_source"):
            real_n = (lineup.get("quality") or {}).get("real_player_props", 0)
            factors.append({
                "factor": "props de jugadores",
                "impact": "datos reales" if real_n else "provisional",
                "detail": f"{lineup['player_props_source']} · {real_n} jugadores con histórico individual real",
            })
        if availability:
            factors.append({
                "factor": "bajas y sanciones",
                "impact": "reduce confianza" if official_absences else "provisional",
                "detail": f"{len(availability)} incidencias; {official_absences} confirmadas por fuente oficial · penalización cuantificada {impact['confidence_penalty_pp']:.1f} pp",
            })
        else:
            factors.append({"factor": "bajas y sanciones", "impact": "sin incidencias verificadas", "detail": "se actualizará cuando la fuente publique cambios"})
        components = (match.get("model_meta") or {}).get("components") or {}
        dc, elo = components.get("dixon_coles") or {}, components.get("elo") or {}
        disagreement = max((abs(float(dc.get(key, 0)) - float(elo.get(key, 0))) for key in ("1", "X", "2")), default=0)
        penalty = min(20, (impact.get("confidence_penalty_pp", 5) if impact else 5) + (4 if heat.get("level") == "alto" else 0))
        score = max(0, min(100, round(max(probs) + 35 - disagreement * 100 - penalty)))
        evidence = {
            "probabilities": True,
            "model_agreement": bool(components),
            "form_and_splits": bool(trends),
            "tactical_profile": bool(tactical),
            "lineup": bool(lineup),
            "official_lineup": lineup.get("status") == "confirmado",
            "weather": bool(weather),
            "market_odds": isinstance(match.get("odds"), dict),
        }
        weights = {
            "probabilities": 25,
            "model_agreement": 20,
            "form_and_splits": 15,
            "tactical_profile": 15,
            "lineup": 10,
            "official_lineup": 5,
            "weather": 5,
            "market_odds": 5,
        }
        completeness = sum(weights[key] for key, present in evidence.items() if present)
        match["prediction_confidence"] = {
            "score": score,
            "level": "alta" if score >= 72 else "media" if score >= 55 else "baja",
            "model_disagreement_pp": round(disagreement * 100, 1),
            "availability_penalty_pp": penalty,
            "data_completeness_pct": completeness,
            "evidence": evidence,
        }
        match["prediction_factors"] = factors
        no_pick_reasons = []
        if score < 48:
            no_pick_reasons.append("confianza insuficiente")
        if disagreement >= 0.18:
            no_pick_reasons.append("desacuerdo alto entre modelos")
        if completeness < 55:
            no_pick_reasons.append("datos incompletos")
        match["recommendation"] = {
            "decision": "no_pick" if no_pick_reasons else "eligible",
            "label": "Sin apuesta recomendada" if no_pick_reasons else "Pronóstico publicable",
            "reasons": no_pick_reasons,
            "policy": "abstención automática por incertidumbre o falta de evidencia",
        }


def build_alerts(previous: dict | None, audit: dict, ai_events: list[dict], now: datetime) -> list[dict]:
    alerts = []
    stamp = _aware(now).astimezone(MADRID).isoformat()
    if audit.get("incomplete"):
        alerts.append({
            "severity": "critical",
            "code": "today_content_incomplete",
            "message": f"{len(audit['incomplete'])} partido(s) del día siguen incompletos",
            "match_ids": [item["id"] for item in audit["incomplete"]],
            "at": stamp,
        })
    configured_failed = {event.get("provider") for event in ai_events if event.get("status") == "failed"}
    if {"Gemini", "Groq"}.issubset(configured_failed):
        alerts.append({"severity": "critical", "code": "all_ai_providers_failed", "message": "Fallaron Gemini y Groq; se conserva caché o cálculo local", "at": stamp})
    elif configured_failed:
        alerts.append({"severity": "warning", "code": "ai_provider_failed", "message": f"Falló {', '.join(sorted(configured_failed))}; el fallback siguió activo", "at": stamp})
    old_time = _parse((previous or {}).get("generated_at"))
    if old_time and (_aware(now).astimezone(MADRID) - old_time).total_seconds() > 2 * 3600:
        alerts.append({"severity": "warning", "code": "previous_feed_stale", "message": "El feed anterior tenía más de 2 horas de antigüedad", "at": stamp})

    # Colector caído: un workflow puede terminar en verde y aun así llevar horas
    # sin refrescar una fuente concreta (cuota agotada, endpoint caído, gate mal
    # calibrado). Vigilamos la marca de tiempo de cada fuente para que un dato
    # parado NO pase desapercibido detrás de un check verde.
    alerts.extend(_source_staleness_alerts(previous, now, stamp))
    return alerts


# Horas máximas sin refresco antes de avisar, por fuente. Conservador: el margen
# cubre TTLs dinámicos y ventanas de baja actividad sin generar ruido.
_SOURCE_MAX_STALE_H = {
    "the_odds_api": 12.0,
    "api_football": 12.0,
    "current_squads": 30.0,
}
_SOURCE_LABEL = {
    "the_odds_api": "cuotas (The Odds API)",
    "api_football": "API-Football",
    "current_squads": "plantillas actuales",
}


def _source_staleness_alerts(previous: dict | None, now: datetime, stamp: str) -> list[dict]:
    out: list[dict] = []
    health = (previous or {}).get("source_health") or {}
    if not isinstance(health, dict):
        return out
    now_local = _aware(now).astimezone(MADRID)
    for source, max_hours in _SOURCE_MAX_STALE_H.items():
        node = health.get(source)
        if not isinstance(node, dict):
            continue
        stamp_value = node.get("checked_at") or node.get("last_success") or node.get("captured_at")
        checked = _parse(stamp_value)
        if checked is None:
            continue
        hours = (now_local - checked).total_seconds() / 3600.0
        if hours <= max_hours:
            continue
        out.append({
            "severity": "critical" if hours > max_hours * 2 else "warning",
            "code": f"source_stale_{source}",
            "message": (
                f"La fuente {_SOURCE_LABEL.get(source, source)} lleva {hours:.0f} h sin "
                f"actualizarse (umbral {max_hours:.0f} h): posible cuota agotada, endpoint "
                "caído o gate mal calibrado."
            ),
            "source": source,
            "stale_hours": round(hours, 1),
            "at": stamp,
        })
    return out
