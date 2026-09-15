"""Impacto cuantificado de las bajas, con datos reales de la temporada.

Las bajas del once (``bajas_local``/``bajas_visitante``) eran solo una lista de
nombres. Aquí se cruzan con el ranking real de jugadores (goles + asistencias de
la temporada) para estimar CUÁNTA producción se pierde cada equipo y clasificar
el impacto. Es una señal INFORMATIVA para la lectura del usuario: no altera la
probabilidad del modelo (ese ajuste exigiría validación out-of-sample que no se
puede hacer aquí sin datos, y cambiarla a ciegas sería contraproducente).
"""

from __future__ import annotations

import unicodedata

from .normalize import canonical_team

# Peso de cada aportación al "impacto" (un gol pesa más que una asistencia).
GOAL_WEIGHT = 1.0
ASSIST_WEIGHT = 0.5
LEVEL_ALTO = 2.5   # goles+asist ponderados de los ausentes por encima de esto
LEVEL_MEDIO = 1.5

_LEAGUE_KEY = {"LaLiga": "laliga", "LaLiga Hypermotion": "segunda",
               "Champions League": "champions"}


def _norm_player(name: str) -> str:
    text = str(name or "").split("(")[0].strip()   # quita "(Lesión...)"
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _canon(team: str) -> str:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(team or ""))


def _build_lookup(players: dict | None) -> dict[tuple[str, str], dict]:
    """{(equipo_canon, jugador_norm): {goals, assists}} desde el listado real."""
    out: dict[tuple[str, str], dict] = {}
    if not isinstance(players, dict):
        return out
    for league_block in players.values():
        rows = league_block.get("players") if isinstance(league_block, dict) else None
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = (_canon(row.get("team")), _norm_player(row.get("player")))
            if key[1]:
                out[key] = {"goals": float(row.get("goals") or 0.0),
                            "assists": float(row.get("assists") or 0.0),
                            "player": row.get("player")}
    return out


def _side_impact(team: str, bajas: list, lookup: dict) -> dict:
    team_canon = _canon(team)
    clave = []
    score = 0.0
    for baja in bajas or []:
        info = lookup.get((team_canon, _norm_player(baja)))
        if not info:
            continue
        contrib = GOAL_WEIGHT * info["goals"] + ASSIST_WEIGHT * info["assists"]
        if contrib > 0:
            score += contrib
            clave.append({"jugador": info["player"],
                          "goles": int(info["goals"]), "asistencias": int(info["assists"])})
    clave.sort(key=lambda c: c["goles"] + 0.5 * c["asistencias"], reverse=True)
    nivel = "alto" if score >= LEVEL_ALTO else "medio" if score >= LEVEL_MEDIO else "bajo"
    return {"score": round(score, 2), "nivel": nivel, "clave": clave[:3],
            "n_bajas": len(bajas or [])}


def attach_absence_impact(matches: list[dict], players: dict | None) -> int:
    """Añade ``alineacion['impacto_bajas']`` con el impacto por lado. Informativo."""
    lookup = _build_lookup(players)
    if not lookup:
        return 0
    updated = 0
    for match in matches:
        alineacion = match.get("alineacion")
        if not isinstance(alineacion, dict):
            continue
        bl = alineacion.get("bajas_local") or []
        bv = alineacion.get("bajas_visitante") or []
        if not bl and not bv:
            continue
        impacto = {
            "local": _side_impact(match.get("home"), bl, lookup),
            "visitante": _side_impact(match.get("away"), bv, lookup),
            "fuente": "goles+asistencias reales de la temporada · informativo, no altera la probabilidad",
        }
        alineacion["impacto_bajas"] = impacto
        updated += 1
    return updated
