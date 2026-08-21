"""Actualización COMPLETA desde una IP no bloqueada (tu máquina en España).

En los runners de GitHub, FBref (jugadores) y Loterías y Apuestas (quiniela)
devuelven 403. Ejecutado en local, con IP residencial española, sí responden.
Este módulo:

1. Baja los rankings de jugadores (FBref → as.com de reserva) y escribe
   football/data/players.json (override que luego usa el feed).
2. Baja la combinación oficial de la quiniela (LAE) y escribe
   football/data/quiniela.json.
3. Regenera football/data/dashboard.json con todo integrado.

Uso:
    python -m futbol_pred.refresh_local            # todo
    python -m futbol_pred.refresh_local --no-quiniela
    python -m futbol_pred.refresh_local --season 2026

Cada paso es tolerante a fallos: si una fuente no responde, conserva el
override anterior (no lo borra) y sigue con el resto.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import DATA_DIR
from .dashboard import current_season

PLAYERS_PATH = Path(DATA_DIR) / "players.json"
QUINIELA_PATH = Path(DATA_DIR) / "quiniela.json"
DASHBOARD_PATH = Path(DATA_DIR) / "dashboard.json"

LIGAS = (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_players(season: int) -> bool:
    """Escribe players.json con FBref (o as.com). True si consiguió datos."""
    fetchers = []
    for mod, fn in (("fbref_players", "get_top_players"), ("players_as", "get_top_players")):
        try:
            m = __import__(f"futbol_pred.ingest.{mod}", fromlist=[fn])
            fetchers.append((mod, getattr(m, fn)))
        except Exception as exc:  # noqa: BLE001
            print(f"[jugadores] no pude importar {mod}: {exc}", file=sys.stderr)

    out: dict = {}
    for league, label in LIGAS:
        got = None
        for mod, fetch in fetchers:
            try:
                got = fetch(season, league=league)
            except Exception as exc:  # noqa: BLE001
                print(f"[jugadores] {mod} {league}: {type(exc).__name__}", file=sys.stderr)
                got = None
            if got:
                print(f"[jugadores] {league}: OK vía {mod} ({', '.join(got)})")
                break
        if got:
            out[league] = {"label": label, "rankings": got}
    if out:
        _write_json(PLAYERS_PATH, out)
        print(f"[jugadores] escrito {PLAYERS_PATH} ({', '.join(out)})")
        return True
    print("[jugadores] ninguna fuente respondió; se conserva el override anterior", file=sys.stderr)
    return False


def refresh_quiniela() -> bool:
    """Escribe quiniela.json con la combinación oficial de LAE. True si OK."""
    try:
        from .ingest.quiniela_lae import get_current_quiniela
    except Exception as exc:  # noqa: BLE001
        print(f"[quiniela] no pude importar el cliente LAE: {exc}", file=sys.stderr)
        return False
    try:
        q = get_current_quiniela()
    except Exception as exc:  # noqa: BLE001
        print(f"[quiniela] error: {type(exc).__name__}", file=sys.stderr)
        q = None
    if not q:
        print("[quiniela] LAE no respondió; se conserva el override anterior", file=sys.stderr)
        return False
    data = {
        "jornada": q.jornada,
        "fecha": q.fecha,
        "partidos": [
            {"orden": m.orden, "local": m.local, "visitante": m.visitante}
            for m in q.partidos
        ],
    }
    _write_json(QUINIELA_PATH, data)
    print(f"[quiniela] escrito {QUINIELA_PATH} (jornada {q.jornada}, {len(q.partidos)} partidos)")
    return True


def refresh_dashboard() -> bool:
    """Regenera dashboard.json integrando los overrides recién escritos."""
    from .dashboard import build_dashboard

    payload = build_dashboard()
    if not payload.get("matches"):
        print("[feed] las fuentes no devolvieron partidos; no se sobrescribe", file=sys.stderr)
        return False
    _write_json(DASHBOARD_PATH, payload)
    c = payload.get("counts", {})
    print(f"[feed] escrito {DASHBOARD_PATH}: {c.get('total', '?')} partidos, "
          f"{c.get('con_prediccion', '?')} con predicción")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresco completo local (sin bloqueos de IP)")
    ap.add_argument("--season", type=int, default=None, help="Temporada (por defecto, la actual)")
    ap.add_argument("--no-players", action="store_true", help="No actualizar jugadores")
    ap.add_argument("--no-quiniela", action="store_true", help="No actualizar quiniela")
    ap.add_argument("--no-feed", action="store_true", help="No regenerar dashboard.json")
    args = ap.parse_args(argv)

    season = args.season or current_season()
    print(f"== Refresco local · temporada {season} ==")

    if not args.no_players:
        refresh_players(season)
    if not args.no_quiniela:
        refresh_quiniela()
    if not args.no_feed:
        ok = refresh_dashboard()
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
