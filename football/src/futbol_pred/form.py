"""Features de forma reciente, multi-competición y SIN data leakage.

Reglas absolutas (prompts #33, #48):
  * Para predecir el partido N solo se usan partidos ANTERIORES a N: aplicamos
    ``shift(1)`` dentro de cada equipo ANTES de cualquier media móvil.
  * El rolling se calcula por team_uid; nunca se mezclan equipos.
  * Para Champions, la forma de un equipo se nutre de TODAS sus competiciones
    (LaLiga + Champions...), opcionalmente ponderando doméstico vs europeo.

Trabajamos en formato "largo": una fila por equipo y partido. Así el rolling
es trivial y correcto.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TeamMatchRow:
    team: str
    opponent: str
    kickoff: object          # ordenable (datetime, int...)
    is_home: bool
    goals_for: int | None
    goals_against: int | None
    competition: str = "league"


def matches_to_long(matches: list[dict]) -> list[dict]:
    """Convierte partidos (una fila) a formato largo (dos filas: local/visit.)."""
    rows: list[dict] = []
    for m in matches:
        base = {
            "kickoff": m.get("kickoff"),
            "competition": m.get("competition", "league"),
        }
        rows.append({
            **base,
            "team": m["home"],
            "opponent": m["away"],
            "is_home": True,
            "goals_for": m.get("home_goals"),
            "goals_against": m.get("away_goals"),
        })
        rows.append({
            **base,
            "team": m["away"],
            "opponent": m["home"],
            "is_home": False,
            "goals_for": m.get("away_goals"),
            "goals_against": m.get("home_goals"),
        })
    return rows


def _points(gf: int | None, ga: int | None) -> int | None:
    if gf is None or ga is None:
        return None
    if gf > ga:
        return 3
    if gf == ga:
        return 1
    return 0


def rolling_form(
    rows: list[dict],
    windows: tuple[int, ...] = (3, 5, 10),
    competition_filter: str | None = None,
) -> list[dict]:
    """Añade medias móviles de forma por equipo, con shift(1) anti-leakage.

    ``competition_filter``: si se indica (p. ej. 'champions'), la forma se
    calcula solo con partidos de esa competición; si es None (recomendado para
    Champions), se usan TODAS las competiciones del equipo.
    Devuelve, para cada fila, columnas ``gf_avg_lastK``, ``ga_avg_lastK``,
    ``points_avg_lastK`` calculadas SOLO con partidos previos jugados.
    """
    src = rows
    if competition_filter is not None:
        src = [r for r in rows if r.get("competition") == competition_filter]

    # Historial por equipo, en orden cronológico.
    by_team: dict[str, list[dict]] = {}
    for r in sorted(src, key=lambda x: (x["team"], x["kickoff"])):
        by_team.setdefault(r["team"], []).append(r)

    out: list[dict] = []
    for team, team_rows in by_team.items():
        history: list[dict] = []  # partidos JUGADOS previos (ya con shift natural)
        for r in team_rows:
            row = dict(r)
            for w in windows:
                prev = history[-w:]
                gf = [p["goals_for"] for p in prev if p["goals_for"] is not None]
                ga = [p["goals_against"] for p in prev if p["goals_against"] is not None]
                pts = [
                    _points(p["goals_for"], p["goals_against"])
                    for p in prev
                    if p["goals_for"] is not None
                ]
                row[f"gf_avg_last{w}"] = sum(gf) / len(gf) if gf else None
                row[f"ga_avg_last{w}"] = sum(ga) / len(ga) if ga else None
                row[f"points_avg_last{w}"] = sum(pts) / len(pts) if pts else None
            out.append(row)
            # Solo tras registrar la fila añadimos ESTE partido al historial
            # => shift(1) garantizado: nunca se ve a sí mismo.
            if r["goals_for"] is not None and r["goals_against"] is not None:
                history.append(r)
    return out
