"""Líneas justas teóricas para props individuales con muestra real.

Las probabilidades se calculan con un baseline Poisson sobre la expectativa
publicada para el jugador. No son cuotas de bookmaker ni constituyen value por
sí mismas: solo permiten comparar después contra una cuota real.
"""
from __future__ import annotations

import math
from typing import Any


FAIR_LINE_GRIDS = {
    "r": (0.5, 1.5, 2.5, 3.5, 4.5),
    "rp": (0.5, 1.5, 2.5),
    "fc": (0.5, 1.5, 2.5, 3.5),
    "fr": (0.5, 1.5, 2.5, 3.5),
    "t": (0.5,),
}

REAL_SOURCE_PREFIX = "API-Football"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def poisson_over(mean: float, line: float) -> float:
    """P(X > line) para un baseline Poisson de conteos individuales."""
    lam = max(0.0, _number(mean))
    cutoff = max(0, int(math.floor(float(line))))
    term = math.exp(-lam)
    cdf = term
    for k in range(1, cutoff + 1):
        term *= lam / k
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def fair_odds(probability: float) -> float | None:
    return round(1.0 / probability, 2) if probability > 0 else None


def fair_lines_for_prop(prop: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Genera probabilidades Over/Under y sus cuotas justas teóricas."""
    out: dict[str, list[dict[str, Any]]] = {}
    for metric, lines in FAIR_LINE_GRIDS.items():
        mean = max(0.0, _number(prop.get(metric)))
        rows = []
        for line in lines:
            over_raw = poisson_over(mean, line)
            under_raw = 1.0 - over_raw
            rows.append({
                "line": line,
                "over": round(over_raw, 4),
                "under": round(under_raw, 4),
                "fair_over_odds": fair_odds(over_raw),
                "fair_under_odds": fair_odds(under_raw),
            })
        out[metric] = rows
    return out


def enrich_player_rows(rows: list[dict[str, Any]]) -> tuple[bool, int]:
    """Añade fair_lines solo a filas respaldadas por API-Football."""
    changed = False
    enriched = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        if not source.startswith(REAL_SOURCE_PREFIX):
            continue
        fair = fair_lines_for_prop(row)
        if row.get("fair_lines") != fair:
            row["fair_lines"] = fair
            row["fair_model"] = "poisson_baseline"
            changed = True
        enriched += 1
    return changed, enriched


def enrich_payload(payload: dict[str, Any]) -> tuple[bool, int]:
    changed = False
    enriched = 0
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        lineup = match.get("alineacion")
        if not isinstance(lineup, dict):
            continue
        for key in ("clave_local", "clave_visitante"):
            rows = lineup.get(key) or []
            row_changed, count = enrich_player_rows(rows)
            changed = changed or row_changed
            enriched += count
    return changed, enriched
