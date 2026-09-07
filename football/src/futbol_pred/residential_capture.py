"""P2.5: helpers transaccionales para la captura avanzada residencial/Colab.

Esta capa no scrapea FBref por sí sola. Recibe archivos que ya han pasado por
P2.4, verifica que cada captura corresponde exactamente a la liga/temporada
solicitada y solo entonces construye un candidato combinado.

Principio operativo: all-or-nothing. El archivo oficial nunca se toca si falta
una liga, una captura está vacía o aparece cualquier conflicto semántico.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Iterable

from .advanced_stats import ARCHIVE_SCHEMA, DEFAULT_PATH
from .advanced_stats_export import archive_digest, archive_manifest, write_archive
from .advanced_stats_intake import (
    IntakeError,
    empty_archive,
    load_archive_strict,
    plan_intake,
)

DEFAULT_CAPTURE_LEAGUES = ("laliga", "segunda")
ALLOWED_CAPTURE_LEAGUES = {"laliga", "segunda", "champions"}
CAPTURE_REPORT_SCHEMA = "advanced-residential-capture-report-v1"


class CaptureError(RuntimeError):
    """Una captura no puede publicarse de forma segura."""


def parse_leagues(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        rows = list(DEFAULT_CAPTURE_LEAGUES)
    elif isinstance(value, str):
        rows = [item.strip().lower() for item in value.split(",") if item.strip()]
    else:
        rows = [str(item).strip().lower() for item in value if str(item).strip()]
    if not rows:
        raise CaptureError("no_leagues_requested")
    unknown = sorted(set(rows) - ALLOWED_CAPTURE_LEAGUES)
    if unknown:
        raise CaptureError("unsupported_leagues:" + ",".join(unknown))
    # Mantiene el orden solicitado sin ejecutar una liga dos veces.
    return tuple(dict.fromkeys(rows))


def validate_capture_archive(archive: dict, *, league: str, season: int) -> dict:
    """Exige que un temporal contenga solo la liga/temporada solicitada."""
    snapshots = archive.get("snapshots") or []
    if not snapshots:
        raise CaptureError(f"empty_capture:{league}:{season}")
    foreign = [
        (row.get("league"), row.get("season"))
        for row in snapshots
        if row.get("league") != league or int(row.get("season") or 0) != int(season)
    ]
    if foreign:
        raise CaptureError(
            f"capture_scope_mismatch:{league}:{season}:" + json.dumps(foreign[:5])
        )
    teams = sorted({team for row in snapshots for team in (row.get("teams") or {})})
    if not teams:
        raise CaptureError(f"capture_without_teams:{league}:{season}")
    return {
        "league": league,
        "season": int(season),
        "snapshots": len(snapshots),
        "teams": len(teams),
        "first_available_at": snapshots[0].get("available_at"),
        "last_available_at": snapshots[-1].get("available_at"),
        "sha256": archive_digest(archive),
    }


def combine_capture_archives(
    existing: dict,
    captures: dict[str, dict],
    *,
    leagues: tuple[str, ...],
    season: int,
) -> tuple[dict, dict]:
    """Fusiona in-memory; cualquier fallo deja al llamador sin candidato parcial."""
    candidate = deepcopy(existing)
    per_league: dict[str, dict] = {}
    total_added = 0
    total_unchanged = 0

    for league in leagues:
        incoming = captures.get(league)
        if incoming is None:
            raise CaptureError(f"missing_capture:{league}:{season}")
        scope = validate_capture_archive(incoming, league=league, season=season)
        try:
            plan = plan_intake(candidate, incoming)
        except IntakeError as exc:
            raise CaptureError(f"intake_rejected:{league}:{exc}") from exc
        candidate = plan["archive"]
        total_added += int(plan.get("added") or 0)
        total_unchanged += int(plan.get("unchanged") or 0)
        per_league[league] = {
            **scope,
            "added": int(plan.get("added") or 0),
            "unchanged": int(plan.get("unchanged") or 0),
            "merge_status": plan.get("status"),
        }

    return candidate, {
        "status": "ready" if total_added else "no_change",
        "requested_leagues": list(leagues),
        "season": int(season),
        "added": total_added,
        "unchanged": total_unchanged,
        "before_sha256": archive_digest(existing),
        "after_sha256": archive_digest(candidate),
        "per_league": per_league,
        "manifest": archive_manifest(candidate),
        "affects_1x2": False,
    }


def load_existing_or_empty(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return empty_archive()
    try:
        return load_archive_strict(target, require_manifest=True)
    except IntakeError as exc:
        raise CaptureError(f"existing_archive_invalid:{exc}") from exc


def atomic_write_archive(path: str | Path, archive: dict) -> dict:
    """Escribe junto al target, valida y reemplaza con os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".candidate")
    try:
        payload = write_archive(temporary, archive)
        # P2.4 vuelve a validar el candidato serializado antes del replace.
        load_archive_strict(temporary, require_manifest=True)
        os.replace(temporary, target)
        return payload
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_capture_report(
    *,
    target: str | Path = DEFAULT_PATH,
    merge_summary: dict,
    challenger: dict | None = None,
    commands: list[dict] | None = None,
) -> dict:
    return {
        "schema": CAPTURE_REPORT_SCHEMA,
        "target": str(target),
        "status": merge_summary.get("status"),
        "season": merge_summary.get("season"),
        "requested_leagues": merge_summary.get("requested_leagues") or [],
        "archive": {
            "added": merge_summary.get("added", 0),
            "unchanged": merge_summary.get("unchanged", 0),
            "before_sha256": merge_summary.get("before_sha256"),
            "after_sha256": merge_summary.get("after_sha256"),
            "manifest": merge_summary.get("manifest"),
            "per_league": merge_summary.get("per_league") or {},
        },
        "commands": commands or [],
        "challenger": challenger,
        "affects_1x2": False,
        "production_wiring": False,
    }


def write_capture_report(path: str | Path, payload: dict) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


__all__ = [
    "ALLOWED_CAPTURE_LEAGUES",
    "CAPTURE_REPORT_SCHEMA",
    "CaptureError",
    "DEFAULT_CAPTURE_LEAGUES",
    "atomic_write_archive",
    "build_capture_report",
    "combine_capture_archives",
    "load_existing_or_empty",
    "parse_leagues",
    "validate_capture_archive",
    "write_capture_report",
]
