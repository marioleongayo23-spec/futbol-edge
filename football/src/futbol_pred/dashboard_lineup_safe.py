"""Generador pesado seguro: reconstruye el XI antes del guard de calidad.

``dashboard.build_dashboard`` prepara el candidato completo pero no debe decidir
por sí solo si se publica: antes aplicamos la política universal de alineaciones
(último XI oficial / híbrido / probable / oficial). Así un XI model-only o vacío
no provoca una regresión artificial antes de que la capa autoritativa pueda
repararlo.

Si una fuente externa devuelve temporalmente un candidato peor, el guard sigue
bloqueando su escritura, pero un último feed válido se conserva sin convertir
esa protección en un ``Run failed``. Los errores de código inesperados NO se
silencian.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from . import dashboard
from .feed_quality import load_feed, write_feed_safely
from .matchday_lineup_baseline import refresh_payload as refresh_lineup_baseline


def _usable_previous(previous: dict | None) -> bool:
    if not isinstance(previous, dict) or not (previous.get("matches") or []):
        return False
    quality = previous.get("feed_quality") or {}
    return quality.get("valid") is not False


def build_candidate(now: datetime | None = None) -> tuple[dict, dict]:
    now = now or datetime.now(timezone.utc)
    previous = load_feed(dashboard.OUTPUT)
    payload = dashboard.build_dashboard(now=now)

    # ``source_health`` es operativo y no forma parte del LKG top-level. Se
    # conserva aquí para que el backfill de XI respete la cuota diaria conocida.
    if previous and not payload.get("source_health") and previous.get("source_health"):
        payload["source_health"] = deepcopy(previous["source_health"])

    _, baseline_stats = refresh_lineup_baseline(payload, now=now)
    return payload, baseline_stats


def main() -> int:
    football_data = dashboard.FootballDataClient()
    api_football = dashboard.ApiFootballClient()
    previous = load_feed(dashboard.OUTPUT)
    previous_usable = _usable_previous(previous)

    if football_data.offline and api_football.offline:
        if previous_usable:
            print("[feed] fuentes principales sin clave; se conserva last-known-good")
            return 0
        print("Feed no actualizado: faltan FOOTBALL_DATA_API_KEY o API_FOOTBALL_KEY")
        return 2

    payload, baseline_stats = build_candidate()
    print("[lineup-baseline] " + json.dumps(baseline_stats, ensure_ascii=False, sort_keys=True))

    if not payload.get("matches"):
        if previous_usable:
            print("[feed] fuentes sin partidos; se conserva last-known-good")
            return 0
        print("Feed no actualizado: las fuentes no devolvieron próximos partidos")
        return 3

    ok, report = write_feed_safely(dashboard.OUTPUT, payload, previous=previous)
    if not ok:
        issues = ", ".join((report.get("issues") or [])[:8])
        if previous_usable:
            print("[feed] candidato rechazado por calidad; last-known-good sigue publicado: " + issues)
            return 0
        print("Feed no actualizado: guard de calidad rechazó la regresión: " + issues)
        return 4

    metrics = report["metrics"]
    print(
        f"Feed actualizado: {metrics['matches']} partidos en {dashboard.OUTPUT} "
        f"(predicciones={metrics['predictions']}, previas={metrics['previews']}, "
        f"onces={metrics['lineups']}, calidad={report['score']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
