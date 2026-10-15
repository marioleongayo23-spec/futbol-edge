"""Captura snapshots auditables desde el feed intradía sin restaurar serving.

El pipeline pesado sigue siendo la autoridad del modelo, pero puede conservar el
last-known-good si un candidato completo no supera un gate. Este módulo evita que
esa protección interrumpa la recogida prospectiva de evidencia: aplica la lógica
normal de snapshots sobre una COPIA del feed ya refrescado y copia de vuelta solo
``prediction_history`` y ``prediction_snapshot``.

Por diseño nunca copia probabilidades, stats, cuotas, clima, XI ni ningún otro
campo de serving desde la copia restaurada. Así un snapshot histórico no puede
revertir información intradía más fresca.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .prediction_snapshots import apply_prediction_snapshots

OUTPUT = Path(DATA_DIR) / "dashboard.json"
_SNAPSHOT_META_FIELDS = ("prediction_history", "prediction_snapshot")


def _identity(match: dict) -> str:
    date = str(match.get("date") or match.get("kickoff") or "")[:10]
    return "|".join(
        str(value or "").strip().casefold()
        for value in (match.get("league"), match.get("home"), match.get("away"), date)
    )


def _index(matches: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id = {
        str(row.get("id")): row
        for row in matches
        if isinstance(row, dict) and row.get("id")
    }
    by_key = {
        _identity(row): row
        for row in matches
        if isinstance(row, dict)
    }
    return by_id, by_key


def refresh_payload(
    payload: dict,
    previous: dict,
    *,
    now: datetime | None = None,
) -> tuple[bool, dict]:
    """Añade solo metadata de snapshots; jamás restaura campos de predicción."""

    working = deepcopy(payload)
    current_matches = [row for row in (payload.get("matches") or []) if isinstance(row, dict)]
    working_matches = [row for row in (working.get("matches") or []) if isinstance(row, dict)]
    previous_matches = [row for row in (previous.get("matches") or []) if isinstance(row, dict)]
    stamp = now or datetime.now(timezone.utc)

    apply_prediction_snapshots(
        working_matches,
        previous_matches,
        stamp,
        capture=True,
    )

    work_by_id, work_by_key = _index(working_matches)
    changed = False
    snapshots_changed = 0
    history_changed = 0

    for match in current_matches:
        source = None
        if match.get("id"):
            source = work_by_id.get(str(match.get("id")))
        source = source or work_by_key.get(_identity(match))
        if not isinstance(source, dict):
            continue
        for field in _SNAPSHOT_META_FIELDS:
            if field not in source:
                continue
            value = deepcopy(source[field])
            if match.get(field) == value:
                continue
            match[field] = value
            changed = True
            if field == "prediction_snapshot":
                snapshots_changed += 1
            else:
                history_changed += 1

    return changed, {
        "matches": len(current_matches),
        "snapshots_changed": snapshots_changed,
        "histories_changed": history_changed,
        "serving_fields_changed": 0,
        "affects_1x2": False,
    }


def run(path: Path = OUTPUT, now: datetime | None = None) -> tuple[bool, dict]:
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing", "affects_1x2": False}
    candidate = deepcopy(previous)
    changed, stats = refresh_payload(candidate, previous, now=now)
    if not changed:
        return False, stats
    ok, report = write_feed_safely(path, candidate, previous=previous)
    stats["feed_valid"] = bool(ok)
    stats["feed_issues"] = report.get("issues") or []
    return ok, stats


def main() -> int:
    written, stats = run()
    print(json.dumps({"written": written, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
