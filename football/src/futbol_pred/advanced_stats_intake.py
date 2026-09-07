"""P2.4: puerta de entrada estricta para snapshots avanzados reales.

El exportador P2.2 produce archivos reproducibles. Este módulo valida un archivo
externo antes de incorporarlo al histórico versionado que consume P2.3.

Reglas principales:
- nunca se descartan snapshots inválidos silenciosamente;
- el manifiesto y SHA256 semántico deben corresponder al contenido;
- una clave ya existente solo puede repetirse si el contenido semántico es
  idéntico; una reescritura distinta se considera conflicto y se rechaza;
- no se aceptan timestamps futuros ni valores estadísticos absurdos;
- la fusión es aditiva y determinista.

Nada de esta capa altera el 1X2. Solo gobierna la evidencia offline.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any

from .advanced_stats import ARCHIVE_SCHEMA, DEFAULT_PATH, SCHEMA, _dt, normalise_snapshot
from .advanced_stats_export import archive_digest, archive_manifest, merge_archives, write_archive

ALLOWED_LEAGUES = {"laliga", "segunda", "champions"}
MAX_FUTURE_SKEW = timedelta(minutes=5)
XG_MAX = 12.0
KEEPER_RATE_ABS_MAX = 8.0
KEEPER_MINUTES_MAX = 100_000.0


class IntakeError(ValueError):
    """Archivo avanzado no apto para entrar en el histórico."""


def _snapshot_key(snapshot: dict) -> tuple[str, int, str, str, str]:
    return (
        str(snapshot.get("league") or ""),
        int(snapshot.get("season") or 0),
        str(snapshot.get("available_at") or ""),
        str(snapshot.get("source") or ""),
        str(snapshot.get("source_version") or ""),
    )


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _semantic_snapshot_digest(snapshot: dict) -> str:
    return archive_digest({"schema": ARCHIVE_SCHEMA, "snapshots": [snapshot]})


def _domain_issues(snapshot: dict, *, now: datetime) -> list[str]:
    issues: list[str] = []
    league = str(snapshot.get("league") or "")
    if league not in ALLOWED_LEAGUES:
        issues.append(f"league_not_allowed:{league or 'empty'}")

    try:
        season = int(snapshot.get("season"))
    except (TypeError, ValueError):
        season = 0
    if season < 2000 or season > now.year + 1:
        issues.append(f"season_out_of_range:{season}")

    available = _dt(snapshot.get("available_at"))
    generated = _dt(snapshot.get("generated_at"))
    if available is not None and available > now + MAX_FUTURE_SKEW:
        issues.append("available_at_in_future")
    if generated is not None and generated > now + MAX_FUTURE_SKEW:
        issues.append("generated_at_in_future")

    teams = snapshot.get("teams") or {}
    if not teams:
        issues.append("teams_empty")
    for team, row in teams.items():
        if not isinstance(row, dict):
            continue
        matches = _finite(row.get("matches"))
        if matches is None or matches < 0 or matches > 1000 or not matches.is_integer():
            issues.append(f"matches_invalid:{team}")
        for field in ("xg_for90", "npxg_for90", "xg_against90", "npxg_against90"):
            if row.get(field) is None:
                continue
            value = _finite(row.get(field))
            if value is None or value < 0 or value > XG_MAX:
                issues.append(f"{field}_out_of_range:{team}")
        for keeper in row.get("goalkeepers") or []:
            if not isinstance(keeper, dict):
                issues.append(f"goalkeeper_row_invalid:{team}")
                continue
            minutes = _finite(keeper.get("minutes"))
            if minutes is None or minutes < 0 or minutes > KEEPER_MINUTES_MAX:
                issues.append(f"keeper_minutes_out_of_range:{team}")
            psxg = keeper.get("psxg90")
            if psxg is not None:
                value = _finite(psxg)
                if value is None or value < 0 or value > XG_MAX:
                    issues.append(f"keeper_psxg90_out_of_range:{team}")
            plusminus = keeper.get("psxg_plus_minus90")
            if plusminus is not None:
                value = _finite(plusminus)
                if value is None or abs(value) > KEEPER_RATE_ABS_MAX:
                    issues.append(f"keeper_psxg_plus_minus90_out_of_range:{team}")
    return issues


def _manifest_projection(manifest: dict | None) -> dict:
    manifest = manifest or {}
    return {
        key: manifest.get(key)
        for key in (
            "schema",
            "snapshot_count",
            "leagues",
            "seasons",
            "teams",
            "first_available_at",
            "last_available_at",
            "sha256",
        )
    }


def parse_archive_strict(payload: Any, *, now: datetime | None = None, require_manifest: bool = True) -> dict:
    """Valida sin la tolerancia de ``load_archive`` y devuelve forma canónica.

    ``load_archive`` está diseñado para consumo resiliente y omite filas rotas.
    El intake hace lo contrario: un único error invalida el archivo completo.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    if not isinstance(payload, dict) or payload.get("schema") != ARCHIVE_SCHEMA:
        raise IntakeError("archive_schema_invalid")
    raw_snapshots = payload.get("snapshots")
    if not isinstance(raw_snapshots, list):
        raise IntakeError("snapshots_invalid")

    snapshots: list[dict] = []
    keys: set[tuple] = set()
    previous_available: datetime | None = None
    issues: list[str] = []
    for index, raw in enumerate(raw_snapshots):
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            issues.append(f"snapshot[{index}]:schema_invalid")
            continue
        try:
            snapshot = normalise_snapshot(raw)
        except (TypeError, ValueError) as exc:
            issues.append(f"snapshot[{index}]:{exc}")
            continue
        key = _snapshot_key(snapshot)
        if key in keys:
            issues.append(f"snapshot[{index}]:duplicate_key")
        keys.add(key)

        available = _dt(snapshot.get("available_at"))
        if available is not None and previous_available is not None and available < previous_available:
            issues.append(f"snapshot[{index}]:archive_not_sorted")
        if available is not None:
            previous_available = available
        issues.extend(f"snapshot[{index}]:{issue}" for issue in _domain_issues(snapshot, now=current))
        snapshots.append(snapshot)

    if issues:
        raise IntakeError(";".join(issues))

    canonical = merge_archives({"schema": ARCHIVE_SCHEMA, "snapshots": snapshots})
    expected_manifest = archive_manifest(canonical)
    actual_manifest = payload.get("manifest")
    if require_manifest and not isinstance(actual_manifest, dict):
        raise IntakeError("manifest_missing")
    if isinstance(actual_manifest, dict):
        if _manifest_projection(actual_manifest) != _manifest_projection(expected_manifest):
            raise IntakeError("manifest_mismatch")
    return {**canonical, "manifest": expected_manifest}


def load_archive_strict(path: str | Path, *, now: datetime | None = None, require_manifest: bool = True) -> dict:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IntakeError(f"archive_not_found:{target}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"archive_unreadable:{target}") from exc
    return parse_archive_strict(payload, now=now, require_manifest=require_manifest)


def empty_archive() -> dict:
    base = {"schema": ARCHIVE_SCHEMA, "snapshots": []}
    return {**base, "manifest": archive_manifest(base)}


def plan_intake(existing: dict, incoming: dict) -> dict:
    """Calcula una fusión sin permitir reescrituras semánticas."""
    existing_rows = existing.get("snapshots") or []
    incoming_rows = incoming.get("snapshots") or []
    existing_by_key = {_snapshot_key(row): row for row in existing_rows}

    added: list[dict] = []
    unchanged = 0
    conflicts: list[dict] = []
    for row in incoming_rows:
        key = _snapshot_key(row)
        previous = existing_by_key.get(key)
        if previous is None:
            added.append(row)
            continue
        previous_digest = _semantic_snapshot_digest(previous)
        incoming_digest = _semantic_snapshot_digest(row)
        if previous_digest == incoming_digest:
            unchanged += 1
        else:
            conflicts.append({
                "key": list(key),
                "existing_sha256": previous_digest,
                "incoming_sha256": incoming_digest,
            })

    if conflicts:
        raise IntakeError("semantic_key_conflict:" + json.dumps(conflicts, sort_keys=True))

    merged = merge_archives(existing, {"schema": ARCHIVE_SCHEMA, "snapshots": added})
    return {
        "status": "ready" if added else "no_change",
        "added": len(added),
        "unchanged": unchanged,
        "existing": len(existing_rows),
        "incoming": len(incoming_rows),
        "total": len(merged.get("snapshots") or []),
        "before_sha256": archive_digest(existing),
        "incoming_sha256": archive_digest(incoming),
        "after_sha256": archive_digest(merged),
        "manifest": archive_manifest(merged),
        "archive": merged,
        "affects_1x2": False,
    }


def intake_file(
    incoming_path: str | Path,
    *,
    existing_path: str | Path = DEFAULT_PATH,
    output_path: str | Path = DEFAULT_PATH,
    apply: bool = False,
    now: datetime | None = None,
) -> dict:
    incoming = load_archive_strict(incoming_path, now=now, require_manifest=True)
    existing_target = Path(existing_path)
    existing = (
        load_archive_strict(existing_target, now=now, require_manifest=True)
        if existing_target.exists()
        else empty_archive()
    )
    plan = plan_intake(existing, incoming)
    if apply and plan["status"] == "ready":
        write_archive(output_path, plan["archive"])
    return {key: deepcopy(value) for key, value in plan.items() if key != "archive"} | {
        "applied": bool(apply and plan["status"] == "ready"),
        "output": str(output_path),
    }


def validate_repository_archive(path: str | Path = DEFAULT_PATH, *, now: datetime | None = None) -> dict:
    archive = load_archive_strict(path, now=now, require_manifest=True)
    return {
        "status": "valid",
        "path": str(path),
        "snapshot_count": len(archive.get("snapshots") or []),
        "manifest": archive["manifest"],
        "affects_1x2": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2.4 strict advanced snapshot intake")
    parser.add_argument("incoming", nargs="?", type=Path)
    parser.add_argument("--existing", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-repository", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.validate_repository:
            result = validate_repository_archive(args.existing)
        else:
            if args.incoming is None:
                parser.error("incoming es obligatorio salvo con --validate-repository")
            result = intake_file(
                args.incoming,
                existing_path=args.existing,
                output_path=args.output,
                apply=args.apply,
            )
    except IntakeError as exc:
        print(json.dumps({"status": "rejected", "error": str(exc), "affects_1x2": False}, ensure_ascii=False, sort_keys=True))
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
