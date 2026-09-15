"""Pi-ratings (Constantinou & Fenton, 2013) como retador del motor de resultado.

El pi-rating es un sistema de valoración dinámico que la literatura reciente
señala como el *input* de los modelos punteros (CatBoost/XGBoost sobre ratings)
y que suele batir al Elo clásico. A diferencia del Elo, da a cada equipo DOS
ratings —local y visitante— y aprende de la *discrepancia de goles* con un error
amortiguado logarítmicamente (una goleada mueve, pero no dispara, el rating).

Referencia: Constantinou & Fenton, "Determining the level of ability of football
teams by dynamic ratings based on the relative discrepancies in scores between
adversaries" (2013). Constantes y tasas por defecto del paquete de referencia
`piratings` (lambda=0.035, gamma=0.7, b=10, c=3).

Aquí el rating predice una diferencia de goles esperada; se convierte a 1X2 con
la distribución de Skellam (diferencia de dos Poisson) usando el total medio de
goles de la liga, de modo que encaja en el mismo contrato {"1","X","2"} que el
resto de predictores del backtest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.stats import skellam

PI_LAMBDA = 0.035   # tasa de aprendizaje (cuánto pesa el resultado reciente)
PI_GAMMA = 0.7      # transferencia local <-> visitante
PI_B = 10.0         # base logarítmica
PI_C = 3.0          # escala rating -> goles
DEFAULT_TOTAL_GOALS = 2.6   # total medio de goles si no hay muestra


def _expected_gd_side(rating: float) -> float:
    """Diferencia de goles esperada frente al rival medio para un rating."""
    value = PI_B ** (abs(rating) / PI_C) - 1.0
    return -value if rating < 0 else value


@dataclass
class PiRatings:
    """Ratings pi local/visitante por equipo, actualizados partido a partido."""

    lam: float = PI_LAMBDA
    gamma: float = PI_GAMMA
    home: dict[str, float] = field(default_factory=dict)
    away: dict[str, float] = field(default_factory=dict)

    def expected_goal_diff(self, home_team: str, away_team: str) -> float:
        """Diferencia de goles esperada (local - visitante) del partido."""
        rh = self.home.get(home_team, 0.0)
        ra = self.away.get(away_team, 0.0)
        return _expected_gd_side(rh) - _expected_gd_side(ra)

    def update(self, home_team: str, away_team: str, home_goals: int, away_goals: int) -> None:
        """Revisa los cuatro ratings implicados tras un resultado."""
        rhh = self.home.get(home_team, 0.0)
        rha = self.away.get(home_team, 0.0)
        raa = self.away.get(away_team, 0.0)
        rah = self.home.get(away_team, 0.0)

        score_diff = home_goals - away_goals
        e_score_diff = _expected_gd_side(rhh) - _expected_gd_side(raa)
        error = abs(score_diff - e_score_diff)
        weighted = PI_C * (0.0 if error <= 0 else math.log10(1.0 + error))
        # El equipo cuya expectativa quedó por debajo del resultado sube.
        if e_score_diff < score_diff:
            we_h, we_a = weighted, -weighted
        else:
            we_h, we_a = -weighted, weighted

        self.home[home_team] = rhh + we_h * self.lam
        self.away[home_team] = rha + (we_h * self.lam) * self.gamma
        self.away[away_team] = raa + we_a * self.lam
        self.home[away_team] = rah + (we_a * self.lam) * self.gamma


def goal_diff_to_1x2(expected_diff: float, total_goals: float = DEFAULT_TOTAL_GOALS) -> dict[str, float]:
    """Convierte una diferencia de goles esperada en P(1)/P(X)/P(2) vía Skellam.

    Reparte el total medio de goles según la diferencia esperada en dos medias
    Poisson y usa la distribución de su diferencia (Skellam), que da de forma
    natural la masa del empate (D=0) sin corrección ad-hoc.
    """
    total = max(1.2, float(total_goals))
    lam_h = max(0.05, (total + expected_diff) / 2.0)
    lam_a = max(0.05, (total - expected_diff) / 2.0)
    p_home = float(skellam.sf(0, lam_h, lam_a))      # P(D >= 1)
    p_draw = float(skellam.pmf(0, lam_h, lam_a))     # P(D == 0)
    p_away = max(0.0, 1.0 - p_home - p_draw)
    total_p = p_home + p_draw + p_away or 1.0
    return {"1": p_home / total_p, "X": p_draw / total_p, "2": p_away / total_p}
