"""Estadísticas de jugadores desde as.com (rankings de la temporada).

Fuente: https://as.com/resultados/futbol/primera/<TEMP>/ranking/jugadores/ y sus
subramas (goleadores, asistencias, tarjetas...). Las páginas de as.com son
tablas HTML, así que se parsean con pandas.read_html.

Uso como diagnóstico:  python -m futbol_pred.ingest.players_as
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}

LEAGUE_PATH = {"laliga": "primera", "segunda": "segunda"}
BASE_TMPL = "https://as.com/resultados/futbol/{comp}/{season}/ranking/jugadores"
BASE = "https://as.com/resultados/futbol/primera/{season}/ranking/jugadores"
# Slugs reales de as.com (descubiertos de la página base). Se usa barra final.
SUBRANKINGS = ["goles/", "asistencias/", "tarjetas/", "minutos/", "regates/"]

# Categorías que exponemos en la app: slug de as.com -> etiqueta.
CATEGORIES = {
    "goles": "Goleadores",
    "asistencias": "Asistencias",
    "tarjetas": "Tarjetas",
    "minutos": "Minutos",
}


def season_slug(season: int) -> str:
    """2026 -> '2026_2027'."""
    return f"{season}_{season + 1}"


@dataclass
class PlayerStat:
    ranking: str          # goleadores, asistencias...
    rank: int
    player: str
    team: str
    value: float


def _fetch(url: str, timeout: int = 20) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=timeout)


def _log(msg: str) -> None:
    import sys
    print(f"[players_as] {msg}", file=sys.stderr)


def _pick_player_table(tables):
    """Elige la tabla de ranking (más filas y con una columna de texto/nombre)."""
    best, best_rows = None, 0
    for t in tables:
        if t.shape[0] < 3 or t.shape[1] < 2:
            continue
        has_text = any(str(t[c].dtype) == "object" for c in t.columns)
        if has_text and t.shape[0] > best_rows:
            best, best_rows = t, t.shape[0]
    return best


def _rows_from(table, slug: str, top: int):
    """Extrae (rank, jugador, equipo, valor) de la tabla de as.com de forma
    heurística: la columna de jugador es la primera de texto larga, la de equipo
    la siguiente de texto, y el valor la última columna numérica."""
    import pandas as pd

    cols = list(table.columns)
    lc = {c: str(c).strip().lower() for c in cols}
    text_cols = [c for c in cols if str(table[c].dtype) == "object"]
    num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(table[c])]

    def find(*keys):
        for c in cols:
            if any(k in lc[c] for k in keys):
                return c
        return None

    player_col = find("jugador", "nombre") or (text_cols[0] if text_cols else None)
    team_col = find("equipo", "club") or next((c for c in text_cols if c != player_col), None)
    value_col = find(slug, "total") or (num_cols[-1] if num_cols else None)
    if player_col is None or value_col is None:
        return []

    out = []
    for i, (_, row) in enumerate(table.iterrows()):
        if i >= top:
            break
        player = str(row[player_col]).strip()
        if not player or player.lower() == "nan":
            continue
        team = str(row[team_col]).strip() if team_col is not None else ""
        try:
            value = float(row[value_col])
        except (TypeError, ValueError):
            value = None
        out.append({"rank": i + 1, "player": player, "team": team, "value": value})
    return out


def get_top_players(season: int = 2026, league: str = "laliga", top: int = 15) -> dict | None:
    """Rankings de jugadores de as.com por categoría. {slug: {label, players[]}}."""
    import io

    import pandas as pd

    comp = LEAGUE_PATH.get(league, "primera")
    base = BASE_TMPL.format(comp=comp, season=season_slug(season))
    out: dict = {}
    for slug, label in CATEGORIES.items():
        url = f"{base}/{slug}/"
        try:
            r = _fetch(url)
            if not r.ok:
                _log(f"{slug}: HTTP {r.status_code}")
                continue
            tables = pd.read_html(io.StringIO(r.text))
        except Exception as exc:  # noqa: BLE001
            _log(f"{slug}: error {type(exc).__name__}: {exc}")
            continue
        table = _pick_player_table(tables)
        if table is None:
            _log(f"{slug}: sin tabla de jugadores (tablas={len(tables)})")
            continue
        _log(f"{slug}: cols={[str(c) for c in table.columns][:8]}")
        rows = _rows_from(table, slug, top)
        if rows:
            out[slug] = {"label": label, "players": rows}
            _log(f"{slug}: {len(rows)} jugadores, top={rows[0]}")
    return out or None


def _diagnose(season: int = 2026) -> None:
    import re

    import pandas as pd

    slug = season_slug(season)
    base = BASE.format(season=slug)
    # 1) descubre las categorías reales enlazadas desde la página base.
    try:
        r0 = _fetch(base)
        cats = sorted(set(re.findall(r"/ranking/jugadores/([a-z_]+)", r0.text)))
        print(f"[AS] categorías encontradas en base: {cats}")
    except Exception as exc:  # noqa: BLE001
        print(f"[AS] no pude leer categorías: {exc}")

    urls = [base] + [f"{base}/{sub}" for sub in SUBRANKINGS]
    for url in urls:
        try:
            r = _fetch(url)
            print(f"[AS] {url}\n  status={r.status_code} type={r.headers.get('content-type','')} len={len(r.text)}")
            if not r.ok:
                print(f"  head={r.text[:160]!r}")
                continue
            try:
                import io
                tables = pd.read_html(io.StringIO(r.text))
                print(f"  tablas={len(tables)}")
                for i, t in enumerate(tables[:3]):
                    cols = [str(c) for c in t.columns][:8]
                    print(f"   tabla[{i}] shape={t.shape} cols={cols}")
                    if not t.empty:
                        print(f"     fila0={list(t.iloc[0])[:8]}")
            except ValueError as exc:
                print(f"  sin tablas legibles: {exc}")
                # ¿hay JSON embebido / next data?
                for marker in ("__NEXT_DATA__", "application/json", "window.__", "ranking"):
                    if marker in r.text:
                        idx = r.text.find(marker)
                        print(f"   marcador {marker!r} en pos {idx}: {r.text[idx:idx+140]!r}")
                        break
        except Exception as exc:  # noqa: BLE001 - diagnóstico
            print(f"[AS] {url}\n  ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    _diagnose()
