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

BASE = "https://as.com/resultados/futbol/primera/{season}/ranking/jugadores"
# Subramas típicas del ranking de as.com.
SUBRANKINGS = ["goleadores", "asistencias", "tarjetas_amarillas", "tarjetas_rojas", "minutos"]


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


def _diagnose(season: int = 2026) -> None:
    import pandas as pd

    slug = season_slug(season)
    urls = [BASE.format(season=slug)] + [
        f"{BASE.format(season=slug)}/{sub}" for sub in SUBRANKINGS
    ]
    for url in urls:
        try:
            r = _fetch(url)
            print(f"[AS] {url}\n  status={r.status_code} type={r.headers.get('content-type','')} len={len(r.text)}")
            if not r.ok:
                print(f"  head={r.text[:160]!r}")
                continue
            try:
                tables = pd.read_html(r.text)
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
