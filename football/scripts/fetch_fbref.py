#!/usr/bin/env python3
"""Ingesta FBref para ejecutar EN LOCAL o Colab (no en el cron).

Descarga stats de equipo de FBref vía soccerdata y las vuelca a Parquet, que
luego el modelo consume como capa xg. FBref bloquea IPs de datacenter, así que
esto debe correr desde una IP residencial.

Uso:
    pip install soccerdata
    python scripts/fetch_fbref.py --league laliga --season 2025

Después, sube los .parquet generados (o su carpeta) para que el pipeline los use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from futbol_pred.ingest.fbref import FBrefClient, soccerdata_available  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta FBref (local)")
    parser.add_argument("--league", default="laliga",
                        choices=["laliga", "segunda", "champions"])
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--stats", default="standard,shooting,passing,gca",
                        help="tipos de tabla separados por coma")
    args = parser.parse_args()

    if not soccerdata_available():
        print("Falta 'soccerdata'. Instala con: pip install soccerdata")
        sys.exit(1)

    client = FBrefClient()
    for stat_type in args.stats.split(","):
        stat_type = stat_type.strip()
        print(f"Descargando {args.league} {args.season} :: {stat_type} ...")
        try:
            df = client.team_season_stats(args.league, args.season, stat_type)
            path = client.save_parquet(
                df, f"{args.league}_{args.season}_team_{stat_type}"
            )
            print(f"  -> {len(df)} filas guardadas en {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  fallo en {stat_type}: {exc}")


if __name__ == "__main__":
    main()
