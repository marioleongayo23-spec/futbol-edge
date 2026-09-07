#!/usr/bin/env python3
"""P2.5: captura transaccional FBref desde local/Colab/IP residencial.

Ejemplo recomendado desde ``football/``::

    pip install -e '.[xg]'
    python scripts/capture_advanced_stats.py --season 2026

Por defecto captura LaLiga + Segunda. Cada liga se genera en un archivo temporal
independiente mediante ``fetch_fbref.py`` (que ya aplica P2.4). Si cualquiera
falla, el archivo oficial NO se modifica. Solo después de validar todas las
capturas se hace una fusión in-memory y un reemplazo atómico.

Este script nunca hace commit/push y nunca conecta el challenger a producción.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from futbol_pred.advanced_outcome_report import build_report, write_report  # noqa: E402
from futbol_pred.advanced_stats import DEFAULT_PATH  # noqa: E402
from futbol_pred.advanced_stats_intake import IntakeError, load_archive_strict  # noqa: E402
from futbol_pred.config import DATA_DIR, settings  # noqa: E402
from futbol_pred.residential_capture import (  # noqa: E402
    CaptureError,
    atomic_write_archive,
    build_capture_report,
    combine_capture_archives,
    load_existing_or_empty,
    parse_leagues,
    write_capture_report,
)

FETCH_SCRIPT = ROOT / "scripts" / "fetch_fbref.py"
DEFAULT_REPORT = Path(DATA_DIR) / "advanced_stats_capture_report.json"
DEFAULT_CHALLENGER_REPORT = Path(DATA_DIR) / "advanced_outcome_challenger.local.json"


def _capture_one(
    *,
    league: str,
    season: int,
    output: Path,
    stats: str,
    min_team_matches: int,
) -> dict:
    command = [
        sys.executable,
        str(FETCH_SCRIPT),
        "--league",
        league,
        "--season",
        str(season),
        "--stats",
        stats,
        "--export-archive",
        "--archive",
        str(output),
        "--min-team-matches",
        str(min_team_matches),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    record = {
        "league": league,
        "returncode": result.returncode,
        "command": " ".join(command),
        "output": str(output),
    }
    if result.returncode != 0:
        raise CaptureError(f"capture_failed:{league}:returncode={result.returncode}")
    if not output.exists():
        raise CaptureError(f"capture_missing_output:{league}")
    return record


def _challenger_summary(report: dict) -> dict:
    rows = {}
    for league, row in (report.get("reports") or {}).items():
        challenger = row.get("challenger") if isinstance(row, dict) else None
        rows[league] = {
            "status": row.get("status") if isinstance(row, dict) else None,
            "accepted": bool(row.get("accepted")) if isinstance(row, dict) else False,
            "affects_1x2": bool(row.get("affects_1x2")) if isinstance(row, dict) else False,
            "archive_snapshots": row.get("archive_snapshots") if isinstance(row, dict) else None,
            "n": challenger.get("n") if isinstance(challenger, dict) else None,
            "n_validation": challenger.get("n_validation") if isinstance(challenger, dict) else None,
        }
    return {
        "schema": report.get("schema"),
        "season": report.get("season"),
        "affects_1x2": report.get("affects_1x2"),
        "reports": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2.5 transactional residential/Colab advanced-stat capture"
    )
    parser.add_argument(
        "--leagues",
        default="laliga,segunda",
        help="ligas separadas por coma; por defecto laliga,segunda",
    )
    parser.add_argument("--season", type=int, default=int(settings.season))
    parser.add_argument("--target", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--challenger-report",
        type=Path,
        default=DEFAULT_CHALLENGER_REPORT,
    )
    parser.add_argument(
        "--stats",
        default="standard,shooting,keeper",
        help="tablas raw adicionales que fetch_fbref conserva",
    )
    parser.add_argument("--min-team-matches", type=int, default=1)
    parser.add_argument(
        "--skip-challenger",
        action="store_true",
        help="solo captura/valida; no ejecuta el informe P2.3 local",
    )
    args = parser.parse_args(argv)

    try:
        leagues = parse_leagues(args.leagues)
        existing = load_existing_or_empty(args.target)
        captures: dict[str, dict] = {}
        commands: list[dict] = []

        with TemporaryDirectory(prefix="futbol-edge-advanced-") as tmp:
            temp_root = Path(tmp)
            for league in leagues:
                temp_archive = temp_root / f"{league}-{args.season}.json"
                commands.append(
                    _capture_one(
                        league=league,
                        season=args.season,
                        output=temp_archive,
                        stats=args.stats,
                        min_team_matches=max(1, args.min_team_matches),
                    )
                )
                try:
                    captures[league] = load_archive_strict(
                        temp_archive,
                        require_manifest=True,
                    )
                except IntakeError as exc:
                    raise CaptureError(f"strict_reload_failed:{league}:{exc}") from exc

            candidate, merge_summary = combine_capture_archives(
                existing,
                captures,
                leagues=leagues,
                season=args.season,
            )

            if merge_summary["status"] == "ready":
                atomic_write_archive(args.target, candidate)
            elif not Path(args.target).exists():
                # Con target inexistente un no_change sería incoherente.
                raise CaptureError("no_change_without_existing_target")

        challenger_summary = None
        if not args.skip_challenger:
            try:
                challenger_report = build_report(
                    leagues=leagues,
                    season=args.season,
                    archive_path=args.target,
                )
                write_report(challenger_report, args.challenger_report)
                challenger_summary = _challenger_summary(challenger_report)
            except Exception as exc:  # la evaluación no invalida una captura íntegra
                challenger_summary = {
                    "status": "evaluation_error",
                    "error": type(exc).__name__,
                    "affects_1x2": False,
                }

        report = build_capture_report(
            target=args.target,
            merge_summary=merge_summary,
            challenger=challenger_summary,
            commands=commands,
        )
        write_capture_report(args.report, report)
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    except CaptureError as exc:
        rejected = {
            "schema": "advanced-residential-capture-report-v1",
            "status": "rejected",
            "error": str(exc),
            "target": str(args.target),
            "affects_1x2": False,
            "production_wiring": False,
        }
        # El informe de rechazo sí puede escribirse; el archivo oficial no.
        try:
            write_capture_report(args.report, rejected)
        except OSError:
            pass
        print(json.dumps(rejected, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
