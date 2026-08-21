"""Detección robusta de la próxima jornada / fase a predecir.

Lecciones de tus prompts (#30, #47, #69-problema4):
  * En liga NO vale ``max(matchday)``: puede haber partidos adelantados
    (p. ej. J19 con 2 partidos jugados mientras la última jornada COMPLETA
    es la 15). La jornada actual es la última con su cupo de partidos.
  * En Champions la estructura cambia: fase de liga (matchdays 1..8) y luego
    eliminatorias (play-off, octavos, cuartos, semis, final). Ahí no se cuenta
    por cupo, sino por la fase con partidos aún no jugados más próxima.

``next_fixtures`` unifica ambos casos: devuelve el grupo de partidos NO jugados
que forma la próxima ronda coherente, ordenado por fecha.
"""

from __future__ import annotations

from collections import Counter

FINISHED_STATES = {"FINISHED", "AWARDED", "FT", "AET", "PEN"}


def is_finished(match: dict) -> bool:
    if match.get("home_goals") is not None and match.get("away_goals") is not None:
        return True
    return str(match.get("status", "")).upper() in FINISHED_STATES


def last_complete_matchday(matches: list[dict], teams_per_round: int) -> int | None:
    """Última jornada de liga que tiene su cupo completo de partidos jugados.

    ``teams_per_round`` = nº de partidos por jornada (10 en LaLiga de 20
    equipos; 18 en la fase de liga de Champions de 36 equipos).
    """
    played = Counter(
        m["matchday"] for m in matches if is_finished(m) and m.get("matchday")
    )
    complete = [md for md, n in played.items() if n >= teams_per_round]
    return max(complete) if complete else None


def next_league_matchday(matches: list[dict], teams_per_round: int) -> int:
    """Número de la próxima jornada de liga a predecir."""
    last = last_complete_matchday(matches, teams_per_round)
    return (last + 1) if last is not None else 1


def next_fixtures(
    matches: list[dict], teams_per_round: int | None = None
) -> list[dict]:
    """Devuelve los partidos de la próxima ronda a predecir.

    Estrategia unificada:
      1. Si hay 'stage' con eliminatorias, se agrupa por (stage, matchday).
      2. Entre los grupos con partidos NO jugados, se elige el de fecha más
         temprana (la ronda inminente).
      3. Como validación cruzada en liga, si se pasa ``teams_per_round`` y la
         próxima ronda es de fase regular, se prioriza matchday = último
         completo + 1.
    """
    pending = [m for m in matches if not is_finished(m)]
    if not pending:
        return []

    def group_key(m: dict) -> tuple:
        return (m.get("stage") or "REGULAR", m.get("matchday"))

    # Fecha más temprana de cada grupo pendiente.
    groups: dict[tuple, list[dict]] = {}
    for m in pending:
        groups.setdefault(group_key(m), []).append(m)

    def earliest(g: list[dict]):
        ks = [m.get("kickoff") for m in g if m.get("kickoff") is not None]
        return min(ks) if ks else None

    # Preferencia liga: si sabemos el cupo y existe la jornada esperada.
    if teams_per_round is not None:
        expected = next_league_matchday(matches, teams_per_round)
        regular = [
            m for m in pending
            if (m.get("stage") or "REGULAR") == "REGULAR"
            and m.get("matchday") == expected
        ]
        if regular:
            return sorted(regular, key=lambda m: (m.get("kickoff") or 0))

    # Caso general (incl. eliminatorias): grupo pendiente más próximo en fecha.
    best_key = min(
        groups,
        key=lambda k: (earliest(groups[k]) is None, earliest(groups[k])),
    )
    return sorted(groups[best_key], key=lambda m: (m.get("kickoff") or 0))
