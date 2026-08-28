"""Fusiona un feed pesado recién generado con el estado matchday más reciente.

El pipeline pesado recalcula modelos/históricos desde su checkout inicial. Durante
ese tiempo el hot-refresh puede haber publicado XI, bajas, clima, cuotas o estado
más recientes. Antes de publicar el feed pesado, este módulo preserva esos campos
volátiles cuando el feed actual de main es más fresco para el mismo partido.

Después se recomienda ejecutar matchday_prediction_refresh + freshness_gate +
coverage sobre el resultado fusionado para recalcular derivados y trazabilidad.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .hot_refresh import MADRID, _aware, _parse

VOLATILE_FIELDS = (
    "alineacion",
    "weather",
    "weather_adjustment",
    "venue",
    "venue_meta",
    "operational_checks",
    "odds",
    "market_hot_refresh",
    "status",
    "live_score",
    "finished",
    "result",
    "updatedAt",
    "matchday_player_rates",
    "matchday_freshness",
)


def _stamp(value) -> datetime | None:
    if isinstance(value, dict):
        candidates = [
            value.get("source_updated_at"), value.get("checked_at"), value.get("generated_at"),
            value.get("ts"), value.get("official_poll_at"), value.get("player_props_checked_at"),
        ]
        for item in candidates:
            parsed = _parse(item)
            if parsed:
                return parsed
        return None
    return _parse(value)


def _match_freshness(match: dict) -> datetime | None:
    values = []
    for key in ("updatedAt",):
        parsed = _stamp(match.get(key))
        if parsed:
            values.append(parsed)
    checks = match.get("operational_checks") if isinstance(match.get("operational_checks"), dict) else {}
    for key, value in checks.items():
        if key.endswith("_checked_at"):
            parsed = _stamp(value)
            if parsed:
                values.append(parsed)
    for key in ("alineacion", "weather", "market_hot_refresh", "matchday_freshness"):
        parsed = _stamp(match.get(key))
        if parsed:
            values.append(parsed)
    return max(values) if values else None


def _key(match: dict) -> str:
    return str(match.get("id") or "")


def merge_payload(generated: dict, current: dict) -> tuple[dict, dict]:
    out = deepcopy(generated)
    current_by_id = {_key(m): m for m in current.get("matches") or [] if isinstance(m, dict) and _key(m)}
    preserved = 0
    fields = 0
    for target in out.get("matches") or []:
        if not isinstance(target, dict):
            continue
        latest = current_by_id.get(_key(target))
        if not latest:
            continue
        latest_stamp = _match_freshness(latest)
        generated_stamp = _match_freshness(target)
        if latest_stamp is None:
            continue
        if generated_stamp is not None and latest_stamp <= generated_stamp:
            continue
        copied = 0
        for field in VOLATILE_FIELDS:
            if field in latest:
                target[field] = deepcopy(latest[field])
                copied += 1
        if copied:
            preserved += 1
            fields += copied

    # Conservamos la telemetría API del feed más reciente si es posterior.
    current_generated = _parse(current.get("generated_at"))
    out_generated = _parse(out.get("generated_at"))
    if current_generated and (not out_generated or current_generated > out_generated):
        if "source_health" in current:
            out["source_health"] = deepcopy(current["source_health"])
    return out, {"matches_preserved": preserved, "fields_preserved": fields}


def main(argv=None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 3:
        print("uso: merge_matchday_freshness GENERATED CURRENT OUTPUT", file=sys.stderr)
        return 2
    generated_path, current_path, output_path = map(Path, args)
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    current = json.loads(current_path.read_text(encoding="utf-8"))
    merged, stats = merge_payload(generated, current)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
