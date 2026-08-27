"""Cobertura predictiva 22/22 para props individuales en día de partido.

La prioridad es siempre una proyección basada en muestra individual REAL de
API-Football. Cuando uno de los 22 titulares/probables todavía no tiene muestra
suficiente, NO dejamos la UI vacía: repartimos las expectativas de equipo entre
los once según su rol táctico y lo etiquetamos explícitamente como estimación de
modelo. Nunca se presenta una estimación como dato real.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, OUTPUT, _aware, _parse, _key
from .ingest import api_football_players as player_api
from .ingest.lineups_ai import _best_props
from .lineup_authority import is_authoritative_official_lineup

FROM_MIN = 120
UNTIL_MIN = -5
MODEL_SOURCE = "Modelo · rol + predicción de equipo"
REAL_SOURCE_PREFIX = "API-Football"

# Pesos relativos por rol. Se normalizan dentro del XI real/probable, de modo que
# la suma de las props de jugadores permanece coherente con el total del equipo.
ROLE_WEIGHTS = {
    "POR": {"g": .01, "a": .02, "r": .01, "rp": .01, "fc": .18, "fr": .08, "t": .10},
    "LI":  {"g": .12, "a": .50, "r": .38, "rp": .25, "fc": .85, "fr": .65, "t": .85},
    "LD":  {"g": .12, "a": .50, "r": .38, "rp": .25, "fc": .85, "fr": .65, "t": .85},
    "CAI": {"g": .20, "a": .65, "r": .55, "rp": .42, "fc": .78, "fr": .80, "t": .72},
    "CAD": {"g": .20, "a": .65, "r": .55, "rp": .42, "fc": .78, "fr": .80, "t": .72},
    "DFC": {"g": .15, "a": .08, "r": .32, "rp": .20, "fc": 1.00, "fr": .42, "t": 1.15},
    "MCD": {"g": .22, "a": .38, "r": .50, "rp": .35, "fc": 1.10, "fr": .78, "t": 1.10},
    "MC":  {"g": .34, "a": .60, "r": .70, "rp": .52, "fc": .88, "fr": .95, "t": .78},
    "MI":  {"g": .48, "a": .70, "r": .92, "rp": .75, "fc": .70, "fr": 1.05, "t": .60},
    "MD":  {"g": .48, "a": .70, "r": .92, "rp": .75, "fc": .70, "fr": 1.05, "t": .60},
    "MP":  {"g": .72, "a": 1.00, "r": 1.15, "rp": 1.00, "fc": .55, "fr": 1.25, "t": .45},
    "EI":  {"g": .90, "a": .78, "r": 1.35, "rp": 1.25, "fc": .50, "fr": 1.30, "t": .38},
    "ED":  {"g": .90, "a": .78, "r": 1.35, "rp": 1.25, "fc": .50, "fr": 1.30, "t": .38},
    "DC":  {"g": 1.25, "a": .55, "r": 1.65, "rp": 1.55, "fc": .72, "fr": 1.10, "t": .42},
    "UNK": {"g": .45, "a": .45, "r": .75, "rp": .60, "fc": .80, "fr": .80, "t": .70},
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _position(value) -> str:
    raw = str(value or "").upper().strip()
    return raw if raw in ROLE_WEIGHTS else "UNK"


def _side_stat(match: dict, stat: str, side: str, default: float) -> float:
    row = (match.get("stats") or {}).get(stat)
    key = "home" if side == "local" else "away"
    if isinstance(row, dict):
        value = _num(row.get(key), default)
        if value >= 0:
            return value
    return default


def _team_totals(match: dict, side: str) -> dict[str, float]:
    idx = 0 if side == "local" else 1
    xg = match.get("xg") if isinstance(match.get("xg"), list) else []
    goal_total = max(.15, _num(xg[idx] if idx < len(xg) else None, 1.25))
    shots = max(4.0, _side_stat(match, "shots", side, goal_total * 7.6))
    sot = max(1.0, min(shots, _side_stat(match, "sot", side, shots * .37)))
    fouls = max(6.0, _side_stat(match, "fouls", side, 12.0))
    opp = "visitante" if side == "local" else "local"
    fouls_received = max(6.0, _side_stat(match, "fouls", opp, 12.0))
    yellows = max(.5, _side_stat(match, "yellows", side, 2.2))
    # Las asistencias no pueden superar razonablemente los goles esperados.
    assists = max(.08, goal_total * .72)
    return {
        "g": goal_total,
        "a": assists,
        "r": shots,
        "rp": sot,
        "fc": fouls,
        "fr": fouls_received,
        "t": yellows,
    }


def _allocate(total: float, positions: list[str], metric: str) -> list[float]:
    weights = [ROLE_WEIGHTS[_position(pos)][metric] for pos in positions]
    denom = sum(weights) or 1.0
    return [round(total * weight / denom, 2) for weight in weights]


def _real_row(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return False
    return str(row.get("source") or "").startswith(REAL_SOURCE_PREFIX) and _num(row.get("sample_minutes"), 0) > 0


def _real_from_cache(match: dict, side: str, names: list[str]) -> list[dict]:
    cache = match.get("matchday_player_rates") if isinstance(match.get("matchday_player_rates"), dict) else {}
    rates = cache.get(side) or []
    if not rates:
        return []
    return player_api.props_for_official_starters(names, rates, limit=11)


def _hybrid_side(match: dict, lineup: dict, side: str) -> tuple[list[dict], int]:
    names = list(lineup.get(side) or [])
    positions = list(lineup.get(f"posiciones_{side}") or [])
    if len(names) != 11:
        return [], 0
    positions = [(positions[i] if i < len(positions) else "UNK") for i in range(11)]

    # 1) Preservar cualquier proyección ya sustentada por historia individual real.
    existing = {
        _key(row.get("jugador")): dict(row)
        for row in (lineup.get(f"clave_{side}") or [])
        if _real_row(row)
    }
    # 2) Explotar el caché intradía real si el probable/official cambió después.
    for row in _real_from_cache(match, side, names):
        if _real_row(row):
            existing[_key(row.get("jugador"))] = dict(row)

    totals = _team_totals(match, side)
    allocations = {metric: _allocate(total, positions, metric) for metric, total in totals.items()}
    official = is_authoritative_official_lineup(lineup)
    status = str(lineup.get("status") or "estimado").casefold()
    starter_probability = 1.0 if official else .88 if status == "probable" else .74

    rows = []
    real_count = 0
    for index, name in enumerate(names):
        key = _key(name)
        if key in existing:
            row = dict(existing[key])
            row["evidence_type"] = "real_history_projection"
            row["prediction_kind"] = "individual_history"
            rows.append(row)
            real_count += 1
            continue

        pos = _position(positions[index])
        minutes = 90.0 if official and pos == "POR" else 86.0 if official else 82.0 if status == "probable" else 76.0
        row = {
            "jugador": name,
            "position": pos if pos != "UNK" else None,
            "g": allocations["g"][index],
            "a": allocations["a"][index],
            "r": allocations["r"][index],
            "rp": allocations["rp"][index],
            "fc": allocations["fc"][index],
            "fr": allocations["fr"][index],
            "t": allocations["t"][index],
            "min": minutes,
            "tit": starter_probability,
            "sample_minutes": 0,
            "sample_quality": "sin_muestra_individual",
            "source": MODEL_SOURCE,
            "evidence_type": "model_estimate",
            "prediction_kind": "role_team_allocation",
            "team_prediction_totals": {k: round(v, 2) for k, v in totals.items()},
        }
        rows.append(row)
    return rows, real_count


def _critical(match: dict, now_local: datetime) -> bool:
    if match.get("finished"):
        return False
    kickoff = _parse(match.get("kickoff"))
    if not kickoff or kickoff.date() != now_local.date():
        return False
    minutes = (kickoff - now_local).total_seconds() / 60.0
    return UNTIL_MIN <= minutes <= FROM_MIN


def refresh_payload(payload: dict, now: datetime | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    changed = False
    stats = {"matches": 0, "covered_players": 0, "real_players": 0, "model_players": 0}
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or not _critical(match, now_local):
            continue
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
        if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11:
            continue
        local, local_real = _hybrid_side(match, lineup, "local")
        away, away_real = _hybrid_side(match, lineup, "visitante")
        if len(local) != 11 or len(away) != 11:
            continue
        before = (lineup.get("clave_local"), lineup.get("clave_visitante"), lineup.get("best_props"))
        lineup["clave_local"] = local
        lineup["clave_visitante"] = away
        lineup["best_props"] = _best_props(local, away)
        real_count = local_real + away_real
        lineup["numeric_props_source"] = (
            "API-Football · players" if real_count == 22
            else f"Predictivo híbrido · {real_count}/22 con muestra individual real"
        )
        lineup["player_props_source"] = lineup["numeric_props_source"]
        lineup["player_props_checked_at"] = now_local.isoformat()
        lineup["player_props_lineup_status"] = lineup.get("status")
        quality = dict(lineup.get("quality") or {})
        quality.update({
            "props_players": 22,
            "predicted_player_props": 22,
            "real_player_props": real_count,
            "model_player_props": 22 - real_count,
            "player_props_source": lineup["player_props_source"],
        })
        lineup["quality"] = quality
        match["alineacion"] = lineup
        checks = dict(match.get("operational_checks") or {})
        checks["player_props_checked_at"] = now_local.isoformat()
        checks["player_props_check_result"] = "complete_real" if real_count == 22 else "complete_hybrid"
        match["operational_checks"] = checks
        after = (lineup.get("clave_local"), lineup.get("clave_visitante"), lineup.get("best_props"))
        changed = changed or before != after
        stats["matches"] += 1
        stats["covered_players"] += 22
        stats["real_players"] += real_count
        stats["model_players"] += 22 - real_count
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
