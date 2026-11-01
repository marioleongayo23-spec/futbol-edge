"""Huella estable del feed para evitar publicaciones por metadata volátil.

El dashboard se recalcula frecuentemente y renueva ``generated_at`` y el
``updatedAt`` de cada partido aunque el contenido deportivo no haya cambiado.
También publica algunos contadores que describen *lo que hizo esta ejecución*
(p. ej. cuántos forecasts refrescó), aunque el estado final resultante sea el
mismo. Ninguno de esos campos justifica por sí solo un commit/deployment.

La huella conserva los datos sustantivos: resultados, cuotas, snapshots, onces,
clima final, estadísticas, alertas, calidad, calibración, ranking value, etc.
Cualquier cambio real en ellos sigue publicándose.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Contadores derivados de la ejecución actual. El estado que representan vive
# en matches/players/value_ranking y, si cambia, seguirá cambiando la huella.
RUN_LOCAL_AUDIT_KEYS = {
    "selective_retries",
    "official_lineup_updates",
    "weather_updates",
    "weather_adjustments",
    "closing_snapshot_updates",
    "extended_market_updates",
    "archived_weather_updates",
    "state_simulations",
}


def semantic_feed(payload: dict) -> dict:
    """Devuelve una copia del feed sin metadata puramente volátil."""

    normalized = copy.deepcopy(payload)
    normalized.pop("generated_at", None)
    normalized.pop("postmatch_stats_updates", None)
    # ``picks`` es derivado y depende de la hora (ventana de 72 h deslizante):
    # no debe disparar por sí solo una republicación. Viaja con cualquier cambio
    # real de probs/mercado, que sí cuenta en la huella.
    normalized.pop("picks", None)

    audit = normalized.get("content_audit")
    if isinstance(audit, dict):
        for key in RUN_LOCAL_AUDIT_KEYS:
            audit.pop(key, None)

    matches = normalized.get("matches")
    if isinstance(matches, list):
        for match in matches:
            if isinstance(match, dict):
                match.pop("updatedAt", None)
    return normalized


def semantic_digest(payload: dict) -> str:
    """SHA-256 determinista del contenido que sí debe provocar publicación."""

    canonical = json.dumps(
        semantic_feed(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def digest_file(path: str | Path) -> str:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("El feed debe ser un objeto JSON")
    return semantic_digest(payload)


def _feed_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def publication_reason(current: dict, candidate: dict, heartbeat_minutes: int = 90) -> str:
    """Publish content changes or a bounded freshness heartbeat.

    A semantic digest alone ignores generated_at by design; without a heartbeat
    a successful run that recomputes unchanged sports data leaves the serving
    feed appearing stale. Skip regressions so concurrent jobs cannot replace a
    newer production snapshot with an older one.
    """
    if not isinstance(current, dict) or not isinstance(candidate, dict):
        return "invalid"
    new_time = _feed_timestamp(candidate.get("generated_at"))
    old_time = _feed_timestamp(current.get("generated_at"))
    if new_time is None:
        return "invalid"
    if old_time is not None and new_time <= old_time:
        return "stale_candidate"
    if semantic_digest(current) != semantic_digest(candidate):
        return "content_changed"
    if old_time is None:
        return "missing_previous_timestamp"
    if new_time - old_time >= timedelta(minutes=heartbeat_minutes):
        return "heartbeat"
    return "unchanged"


def publication_reason_files(current_path: str | Path, candidate_path: str | Path) -> str:
    with Path(current_path).open(encoding="utf-8") as old:
        previous = json.load(old)
    with Path(candidate_path).open(encoding="utf-8") as new:
        candidate = json.load(new)
    return publication_reason(previous, candidate)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 3 and args[0] == "publish-reason":
        try:
            reason = publication_reason_files(args[1], args[2])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"feed inválido: {exc}", file=sys.stderr)
            return 2
        print(reason)
        return 0 if reason != "invalid" else 2
    if len(args) != 1:
        print("uso: python -m futbol_pred.feed_semantic [publish-reason old.json new.json | dashboard.json]", file=sys.stderr)
        return 2
    try:
        print(digest_file(args[0]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"feed inválido: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
