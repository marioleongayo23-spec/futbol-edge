#!/usr/bin/env python3
"""Enriquece dashboard.json con calidad auditable por partido.

La calidad es una señal de cobertura, no una modificación de probabilidades.
Solo se calcula cuando el pipeline ya ha generado ``coverage`` para el partido;
no se inventan estados para partidos fuera de la ventana operativa.
"""
from __future__ import annotations

import json
from pathlib import Path

from futbol_pred.match_quality import calculate_match_quality


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "football" / "data" / "dashboard.json"


def enrich(path: Path = DASHBOARD) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        coverage = match.get("coverage")
        if not isinstance(coverage, dict):
            continue
        quality = calculate_match_quality(match, coverage)
        if match.get("match_quality") != quality:
            match["match_quality"] = quality
            changed = True

    if changed:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


if __name__ == "__main__":
    print("match_quality changed:", enrich())
