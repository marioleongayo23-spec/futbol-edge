"""Genera el snapshot de xG por partido (data/xg_match_snapshot.json) desde FBref.

FBref bloquea IPs cloud/datacenter, así que esto NO corre en el cron: se ejecuta
en LOCAL (donde FBref responde), produce un snapshot versionado y se publica. El
informe del modelo lo lee (:mod:`futbol_pred.ingest.xg_snapshot`) y activa el
retador xG, que el gate promociona solo si mejora.

Uso local:

    pip install soccerdata
    python -m futbol_pred.build_xg_snapshot --league laliga --season 2026
    python -m futbol_pred.build_xg_snapshot --league segunda --season 2026 --merge

``--merge`` fusiona con el snapshot existente en vez de reemplazarlo (para
acumular varias ligas/temporadas en un solo fichero).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ingest.xg_snapshot import DEFAULT_XG_SNAPSHOT, XG_SNAPSHOT_SCHEMA, load_xg_snapshot


def _col(df, *candidates):
    """Primera columna cuyo nombre (aplanado, en minúsculas) casa un candidato."""
    lowered = {}
    for c in df.columns:
        name = " ".join(str(p) for p in c) if isinstance(c, tuple) else str(c)
        lowered[name.strip().lower()] = c
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    # coincidencia laxa: la primera que contiene el candidato
    for cand in candidates:
        for key, original in lowered.items():
            if cand in key:
                return original
    return None


def build_from_fbref(league: str, season: int) -> list[dict]:
    """Filas {league, season, date, home, away, home_xg, away_xg} desde FBref.

    Cada partido se toma UNA vez, desde la fila del equipo local (venue=Home).
    Lanza RuntimeError si soccerdata no está disponible.
    """
    from .ingest.fbref import FBrefClient  # importa aquí: exige soccerdata

    df = FBrefClient().team_match_stats(league, season, stat_type="schedule")
    df = df.reset_index()
    c_team = _col(df, "team_canonical", "team")
    c_opp = _col(df, "opponent")
    c_venue = _col(df, "venue")
    c_date = _col(df, "date")
    c_xg = _col(df, "xg")
    c_xga = _col(df, "xga")
    if not all((c_team, c_opp, c_venue, c_date, c_xg, c_xga)):
        raise RuntimeError(f"FBref schedule sin columnas esperadas: {list(df.columns)[:12]}")

    out: list[dict] = []
    for _, row in df.iterrows():
        if str(row[c_venue]).strip().lower() != "home":
            continue
        hx, ax = row[c_xg], row[c_xga]
        try:
            hx, ax = float(hx), float(ax)
        except (TypeError, ValueError):
            continue
        if hx != hx or ax != ax:  # NaN
            continue
        out.append({
            "league": league, "season": int(season),
            "date": str(row[c_date])[:10],
            "home": str(row[c_team]), "away": str(row[c_opp]),
            "home_xg": round(hx, 3), "away_xg": round(ax, 3),
        })
    return out


def _merge(existing: list[dict], fresh: list[dict], league: str, season: int) -> list[dict]:
    """Reemplaza las filas de esa liga+temporada, conserva el resto."""
    kept = [r for r in existing if not (r.get("league") == league and r.get("season") == season)]
    return kept + fresh


def write_snapshot(rows: list[dict], path: str | Path = DEFAULT_XG_SNAPSHOT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": XG_SNAPSHOT_SCHEMA, "matches": rows},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera el snapshot de xG por partido desde FBref.")
    ap.add_argument("--league", required=True, choices=("laliga", "segunda", "champions"))
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--merge", action="store_true", help="fusiona con el snapshot existente")
    ap.add_argument("--path", default=str(DEFAULT_XG_SNAPSHOT))
    args = ap.parse_args()

    fresh = build_from_fbref(args.league, args.season)
    rows = _merge(load_xg_snapshot(args.path), fresh, args.league, args.season) if args.merge else fresh
    out = write_snapshot(rows, args.path)
    print(f"xG snapshot: {len(fresh)} partidos de {args.league} {args.season} -> {out} "
          f"({len(rows)} en total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
