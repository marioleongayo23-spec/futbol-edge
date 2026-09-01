"""Modelo curado de la Liga F (Primera División femenina).

No hay fuente gratuita con calendario/resultados de la Liga F (football-data.org
free solo da LaLiga; co.uk y openfootball no publican la femenina), así que los
partidos femeninos de la quiniela no pueden pasar por el mismo ajuste
Dixon-Coles que el resto. Para que NUNCA salgan "sin predicción" ni —peor— con la
predicción del equipo masculino homónimo, aquí va un prior TRANSPARENTE y
editable: una tabla de fuerzas ataque/defensa que refleja la jerarquía
competitiva conocida de la liga, convertida a goles esperados y de ahí a 1X2 y
marcador con la MISMA matriz Poisson (Dixon-Coles) que usa el motor principal.

Es un prior fundamentado, no un ajuste sobre datos: en cuanto exista una fuente
real de resultados femeninos se sustituye ``RATINGS`` por un ajuste como el de
las demás ligas. Un equipo que no esté en la tabla usa fuerza neutra (prior de
igualdad + ventaja de campo), de modo que siempre hay un pronóstico razonado.
"""

from __future__ import annotations

import re
import unicodedata

from .model.dixon_coles import DixonColesModel

# Medias de goles de la Liga F (más goleadora que la masculina por el dominio de
# los grandes). ``att`` > 1 = ataque fuerte; ``dfc`` > 1 = defensa que encaja
# más. Goles_local = HOME_MEAN * att_local * dfc_visitante, y simétrico fuera.
HOME_MEAN = 1.55
AWAY_MEAN = 1.15
RHO = -0.08  # corrección Dixon-Coles de resultados bajos (empates/1-0).

# Jerarquía curada de la Liga F (temporada 2025-26 / 2026-27). Clave = nombre
# normalizado sin acentos ni el sufijo "(F)"/"femenino".
RATINGS: dict[str, tuple[float, float]] = {
    "barcelona": (2.05, 0.35),
    "real madrid": (1.55, 0.55),
    "atletico madrid": (1.35, 0.68),
    "atletico de madrid": (1.35, 0.68),
    "levante": (1.15, 0.85),
    "levante las planas": (0.88, 1.18),
    "real sociedad": (1.08, 0.92),
    "athletic club": (1.05, 0.90),
    "athletic": (1.05, 0.90),
    "madrid cff": (0.98, 1.02),
    "sevilla": (0.95, 1.05),
    "valencia": (0.92, 1.08),
    "granada": (0.90, 1.10),
    "espanyol": (0.90, 1.10),
    "real betis": (0.92, 1.06),
    "betis": (0.92, 1.06),
    "deportivo": (0.85, 1.15),
    "deportivo abanca": (0.85, 1.15),
    "tenerife": (0.85, 1.15),
    "costa adeje tenerife": (0.85, 1.15),
    "eibar": (0.78, 1.25),
    "alaves": (0.75, 1.32),
    "logrono": (0.78, 1.26),
    "edf logrono": (0.78, 1.26),
    "sporting huelva": (0.76, 1.28),
}

NEUTRAL = (1.0, 1.0)


def _key(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    # Fuera el marcador de femenino y ruido de club.
    n = re.sub(r"\(\s*f\s*\)|\bfemenino\b|\bfem\b", " ", n)
    n = re.sub(r"\b(cf|fc|cd|ud|sd|club|de|cff)\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def is_femenino(name: str) -> bool:
    """¿El nombre viene marcado como equipo femenino? (sufijo (F)/femenino)."""
    return bool(re.search(r"\(\s*[fF]\s*\)|femenin", name or ""))


def _rating(name: str) -> tuple[float, float]:
    return RATINGS.get(_key(name), NEUTRAL)


def predict(home: str, away: str) -> dict:
    """Pronóstico 1X2 + marcador para un partido de Liga F desde el prior curado."""
    att_h, dfc_h = _rating(home)
    att_a, dfc_a = _rating(away)
    lh = max(0.15, HOME_MEAN * att_h * dfc_a)
    la = max(0.12, AWAY_MEAN * att_a * dfc_h)
    matrix = DixonColesModel.matrix_from_lambdas(lh, la, rho=RHO, max_goals=8)
    probs = matrix.one_x_two()
    top = matrix.top_correct_scores(1)[0]
    eh, ea = matrix.expected_goals()
    return {
        "probs": probs,
        "xg": (round(eh, 2), round(ea, 2)),
        "marcador": f"{top[0]}-{top[1]}",
        "over_2_5": round(matrix.over(2.5), 3),
        "btts": round(matrix.btts()["yes"], 3),
        "curado": _key(home) in RATINGS and _key(away) in RATINGS,
    }
