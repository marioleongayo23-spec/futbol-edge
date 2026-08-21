"""Estadísticas de jugadores desde FBref (tablas HTML reales).

FBref esconde algunas tablas dentro de comentarios HTML (anti-scraping); se
quita el comentario y se parsea con pandas. De la tabla 'standard' salen goles,
asistencias, minutos y xG; de 'misc', las tarjetas.

Nota: FBref puede bloquear IPs de datacenter (403). Este módulo lo comprueba y
degrada a None sin romper el feed.

Diagnóstico:  python -m futbol_pred.ingest.fbref_players
"""

from __future__ import annotations

import io
import re

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# liga -> (comp_id, slug FBref)
COMP = {"laliga": ("12", "La-Liga"), "segunda": ("17", "Segunda-Division")}

# columna de la tabla -> (slug de categoría, etiqueta, ascendente?)
METRICS = [
    ("Gls", "goles", "Goleadores"),
    ("Ast", "asistencias", "Asistencias"),
    ("xG", "xg", "xG"),
    ("Min", "minutos", "Minutos"),
]


def _fetch(url: str, timeout: int = 25) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=timeout)


def _flatten(cols):
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(p) for p in c if str(p) and not str(p).startswith("Unnamed")]
            out.append(parts[-1] if parts else "")
        else:
            out.append(str(c))
    return out


def _player_table(html: str):
    import pandas as pd

    # Descomenta las tablas ocultas de FBref.
    clean = html.replace("<!--", "").replace("-->", "")
    for t in pd.read_html(io.StringIO(clean)):
        cols = _flatten(t.columns)
        if "Player" in cols:
            t = t.copy()
            t.columns = cols
            t = t[t["Player"] != "Player"]  # quita cabeceras repetidas
            return t
    return None


def get_top_players(season: int = 2026, league: str = "laliga", top: int = 15) -> dict | None:
    import os
    import sys

    import pandas as pd

    def log(m):
        if os.environ.get("DEBUG_INGEST"):
            print(f"[fbref] {m}", file=sys.stderr)

    cid, slug = COMP.get(league, ("12", "La-Liga"))
    url = f"https://fbref.com/en/comps/{cid}/stats/{slug}-Stats"
    try:
        r = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        log(f"{league}: error {type(exc).__name__}")
        return None
    if not r.ok:
        log(f"{league}: HTTP {r.status_code}")
        return None
    try:
        table = _player_table(r.text)
    except Exception as exc:  # noqa: BLE001
        log(f"{league}: parse error {type(exc).__name__}")
        return None
    if table is None:
        log(f"{league}: sin tabla de jugadores")
        return None
    log(f"{league}: filas={len(table)} cols={list(table.columns)[:20]}")

    team_col = "Squad" if "Squad" in table.columns else None
    out: dict = {}
    for col, cat, label in METRICS:
        if col not in table.columns:
            continue
        df = table[["Player"] + ([team_col] if team_col else []) + [col]].copy()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=[col]).sort_values(col, ascending=False).head(top)
        players = []
        for i, (_, row) in enumerate(df.iterrows()):
            v = float(row[col])
            players.append({
                "rank": i + 1,
                "player": str(row["Player"]),
                "team": str(row[team_col]) if team_col else "",
                "value": round(v, 1) if col == "xG" else int(v),
            })
        if players:
            out[cat] = {"label": label, "players": players}
    return out or None


if __name__ == "__main__":
    import os
    os.environ["DEBUG_INGEST"] = "1"
    for lg in ("laliga", "segunda"):
        res = get_top_players(league=lg)
        print(f"{lg}: {'OK ' + str(list(res)) if res else 'None'}")
        if res:
            first = next(iter(res.values()))
            print("  top3:", [(p["rank"], p["player"], p["team"], p["value"]) for p in first["players"][:3]])
