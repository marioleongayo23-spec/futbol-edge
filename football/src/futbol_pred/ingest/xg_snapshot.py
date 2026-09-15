"""Lector de xG por partido para alimentar el retador xG del backtest.

FBref bloquea IPs cloud, así que el xG por partido no se scrapea en el cron: se
genera en local (o en una sesión con datos) y se publica un snapshot versionado
que el informe del modelo lee. Este módulo SOLO consume ese snapshot y adjunta
el xG del propio partido a cada match; la causalidad la garantiza el walk-forward
(el xG de un partido, como sus goles, solo se conoce después de jugarlo).

Formato del snapshot (``data/xg_match_snapshot.json``):

    {"schema": "xg-match-v1",
     "matches": [
        {"league": "laliga", "season": 2026, "date": "2026-09-13",
         "home": "FC Barcelona", "away": "Levante UD",
         "home_xg": 2.4, "away_xg": 0.9}
     ]}

``league``/``season`` por partido son opcionales (si el snapshot ya es de una
sola liga/temporada). El emparejado es por local canónico + visitante canónico +
fecha. Nunca lanza: ante cualquier problema devuelve 0 y el retador cae a goles.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR
from ..normalize import canonical_team

XG_SNAPSHOT_SCHEMA = "xg-match-v1"
DEFAULT_XG_SNAPSHOT = Path(DATA_DIR) / "xg_match_snapshot.json"


def _canon(name: str) -> str:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(name or ""))


def _date_key(value) -> str:
    text = str(value or "")
    return text[:10]


def _num(value):
    try:
        out = float(value)
        return out if out == out else None  # descarta NaN
    except (TypeError, ValueError):
        return None


def load_xg_snapshot(path: str | Path = DEFAULT_XG_SNAPSHOT) -> list[dict]:
    """Lee el snapshot; [] si no existe o es inválido (nunca lanza)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    rows = raw.get("matches") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    return rows if isinstance(rows, list) else []


def attach_xg_from_snapshot(
    matches: list[dict],
    league: str | None = None,
    season: int | None = None,
    path: str | Path = DEFAULT_XG_SNAPSHOT,
) -> int:
    """Adjunta ``match['stats']['xg'] = [home_xg, away_xg]`` desde el snapshot.

    Devuelve cuántos partidos quedaron con xG. Fail-safe: 0 ante cualquier fallo.
    """
    rows = load_xg_snapshot(path)
    if not rows:
        return 0
    index: dict[tuple[str, str, str], tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if league is not None and row.get("league") not in (None, league):
            continue
        if season is not None and row.get("season") not in (None, season):
            continue
        hx, ax = _num(row.get("home_xg")), _num(row.get("away_xg"))
        if hx is None or ax is None:
            continue
        key = (_canon(row.get("home")), _canon(row.get("away")), _date_key(row.get("date")))
        index[key] = (max(0.0, hx), max(0.0, ax))
    if not index:
        return 0

    covered = 0
    for match in matches:
        date = _date_key(match.get("date") or match.get("kickoff_date"))
        if not date:
            ko = match.get("kickoff")
            if isinstance(ko, (int, float)):
                from datetime import datetime, timezone
                date = datetime.fromtimestamp(ko, tz=timezone.utc).date().isoformat()
        key = (_canon(match.get("home")), _canon(match.get("away")), date)
        xg = index.get(key)
        if xg is not None:
            match.setdefault("stats", {})["xg"] = [xg[0], xg[1]]
            covered += 1
    return covered
