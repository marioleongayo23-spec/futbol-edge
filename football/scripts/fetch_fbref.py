#!/usr/bin/env python3
"""Ingesta FBref para ejecutar EN LOCAL o Colab (no en el cron).

Además de conservar tablas raw, puede construir el archivo histórico causal que
consume Fútbol Edge en producción. FBref puede bloquear IPs cloud/datacenter,
por lo que esta adquisición se ejecuta desde una IP residencial/Colab y el cron
solo consume el JSON versionado resultante.

Ejemplos:
    pip install '.[xg]'
    python scripts/fetch_fbref.py --league laliga --season 2026 --export-archive
    python scripts/fetch_fbref.py --league segunda --season 2026 --export-archive \
        --archive data/advanced_stats_snapshots.json

El backfill NO finge timestamps históricos de publicación: cada partido se hace
disponible al día siguiente a las 12:00 UTC. Un challenger futuro podrá por ello
reproducir exactamente qué señales eran elegibles en cada corte.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from futbol_pred.advanced_stats import DEFAULT_PATH, load_archive  # noqa: E402
from futbol_pred.advanced_stats_export import (  # noqa: E402
    archive_manifest,
    build_historical_archive,
    fbref_frames_to_records,
    merge_archives,
    write_archive,
)
from futbol_pred.ingest.fbref import FBrefClient, soccerdata_available  # noqa: E402


def _soccerdata_version() -> str | None:
    try:
        import soccerdata

        return str(getattr(soccerdata, "__version__", "unknown"))
    except Exception:
        return None


def _safe_match_table(client: FBrefClient, league: str, season: int, stat_type: str, *, opponent=False):
    try:
        print(
            f"Descargando partidos {league} {season} :: {stat_type}"
            + (" (opponent)" if opponent else "")
            + " ..."
        )
        frame = client.team_match_stats(
            league,
            season,
            stat_type=stat_type,
            opponent_stats=opponent,
            force_cache=False,
        )
        suffix = "_opponent" if opponent else ""
        path = client.save_parquet(frame, f"{league}_{season}_match_{stat_type}{suffix}")
        print(f"  -> {len(frame)} filas guardadas en {path}")
        return frame
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  fallo en {stat_type}{' opponent' if opponent else ''}: {exc}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta FBref (local/Colab)")
    parser.add_argument(
        "--league",
        default="laliga",
        choices=["laliga", "segunda", "champions"],
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--stats",
        default="standard,shooting,keeper",
        help="tablas agregadas raw separadas por coma (opcionales)",
    )
    parser.add_argument(
        "--export-archive",
        action="store_true",
        help="genera/actualiza advanced_stats_snapshots.json con histórico causal",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_PATH,
        help="ruta del archivo versionado de snapshots",
    )
    parser.add_argument(
        "--min-team-matches",
        type=int,
        default=1,
        help="muestra mínima por equipo antes de emitirlo en un snapshot",
    )
    args = parser.parse_args()

    if not soccerdata_available():
        print("Falta 'soccerdata'. Instala con: pip install '.[xg]' o pip install soccerdata")
        sys.exit(1)

    client = FBrefClient()

    # Conservamos export raw para inspección/reprocesado. Una tabla que falle no
    # impide generar el archivo con las señales que sí estén disponibles.
    for stat_type in args.stats.split(","):
        stat_type = stat_type.strip()
        if not stat_type:
            continue
        print(f"Descargando agregado {args.league} {args.season} :: {stat_type} ...")
        try:
            df = client.team_season_stats(args.league, args.season, stat_type)
            path = client.save_parquet(
                df, f"{args.league}_{args.season}_team_{stat_type}"
            )
            print(f"  -> {len(df)} filas guardadas en {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  fallo en {stat_type}: {exc}")

    if not args.export_archive:
        return

    # Para el histórico causal solo hacemos críticas las tablas por partido.
    # schedule aporta fecha/equipo/xG; shooting/opponent shooting enriquecen npxG;
    # keeper aporta PSxG cuando FBref lo expone para esa competición/temporada.
    schedule = _safe_match_table(client, args.league, args.season, "schedule")
    shooting = _safe_match_table(client, args.league, args.season, "shooting")
    opponent_shooting = _safe_match_table(
        client, args.league, args.season, "shooting", opponent=True
    )
    keeper = _safe_match_table(client, args.league, args.season, "keeper")

    if schedule is None or getattr(schedule, "empty", True):
        print("No se puede generar el archivo: falta schedule por partido")
        sys.exit(2)

    records = fbref_frames_to_records(
        schedule,
        shooting_frame=shooting,
        opponent_shooting_frame=opponent_shooting,
        keeper_frame=keeper,
    )
    if not records:
        print("No se puede generar el archivo: no se extrajeron observaciones avanzadas")
        sys.exit(3)

    source_version = _soccerdata_version()
    generated_at = datetime.now(timezone.utc)
    incoming = build_historical_archive(
        records,
        league=args.league,
        season=args.season,
        source="FBref via soccerdata · offline/residential snapshot",
        source_version=source_version,
        generated_at=generated_at,
        min_team_matches=max(1, args.min_team_matches),
    )
    existing = load_archive(args.archive)
    merged = merge_archives(existing, incoming)
    payload = write_archive(args.archive, merged)
    manifest = payload["manifest"]

    print(
        "Archivo avanzado actualizado: "
        f"{args.archive} | snapshots={manifest['snapshot_count']} | "
        f"equipos={manifest['teams']} | sha256={manifest['sha256'][:16]}…"
    )
    print("Manifest:", archive_manifest(payload))


if __name__ == "__main__":
    main()
