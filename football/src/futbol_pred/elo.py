"""Ratings Elo para fútbol, actualizados cronológicamente y sin leakage.

Elo da un rating de fuerza común a TODOS los equipos, aunque jueguen en ligas
distintas — justo lo que necesita la Champions (prompt #46, #48). La regla de
oro contra el leakage (prompt #33, #46): el Elo pre-partido se lee ANTES de
jugar y solo se actualiza DESPUÉS del resultado. Nunca se usa el Elo
post-partido para predecir ese mismo encuentro.

Ponderación por diferencia de goles al estilo del rating de clubes (538/
clubelo): una goleada mueve más el rating que un 1-0.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _goal_diff_multiplier(goal_diff: int) -> float:
    """Multiplicador de K según margen de victoria (partidos ajustados < K)."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8.0


@dataclass
class EloRatings:
    """Mantiene el rating de cada equipo y lo actualiza partido a partido."""

    k: float = 20.0
    home_adv: float = 65.0        # ventaja de campo en puntos Elo
    base: float = 1500.0
    ratings: dict[str, float] = field(default_factory=dict)

    def get(self, team: str) -> float:
        return self.ratings.get(team, self.base)

    def expected_home(self, home: str, away: str, neutral: bool = False) -> float:
        """Probabilidad Elo de que gane el local (empate repartido apart)."""
        adv = 0.0 if neutral else self.home_adv
        diff = self.get(away) - self.get(home) - adv
        return 1.0 / (1.0 + 10 ** (diff / 400.0))

    def match_probabilities(
        self, home: str, away: str, neutral: bool = False, draw_factor: float = 0.28
    ) -> dict[str, float]:
        """Convierte el Elo en P(1), P(X), P(2).

        ``draw_factor`` calibra cuánta masa va al empate; se afinará por
        backtesting. La probabilidad de empate es mayor cuanto más parejos.
        """
        e_home = self.expected_home(home, away, neutral)
        # Empate máximo cuando e_home ~ 0.5, decae hacia los extremos.
        p_draw = draw_factor * (1.0 - 2.0 * abs(e_home - 0.5))
        p_draw = max(0.05, min(0.40, p_draw))
        p_home = e_home * (1.0 - p_draw)
        p_away = (1.0 - e_home) * (1.0 - p_draw)
        total = p_home + p_draw + p_away
        return {"1": p_home / total, "X": p_draw / total, "2": p_away / total}

    def update(
        self,
        home: str,
        away: str,
        home_goals: int,
        away_goals: int,
        neutral: bool = False,
    ) -> tuple[float, float]:
        """Actualiza los ratings tras un partido. Devuelve (elo_home, elo_away)
        PRE-partido (los que valían para predecirlo)."""
        pre_home = self.get(home)
        pre_away = self.get(away)
        e_home = self.expected_home(home, away, neutral)

        if home_goals > away_goals:
            s_home = 1.0
        elif home_goals < away_goals:
            s_home = 0.0
        else:
            s_home = 0.5

        mult = _goal_diff_multiplier(home_goals - away_goals)
        delta = self.k * mult * (s_home - e_home)
        self.ratings[home] = pre_home + delta
        self.ratings[away] = pre_away - delta
        return pre_home, pre_away


def compute_pre_match_elo(matches: list[dict], **kwargs) -> list[dict]:
    """Recorre partidos en orden cronológico y anota el Elo pre-partido.

    ``matches``: lista de dicts con al menos home, away, home_goals, away_goals
    y (recomendado) una clave 'kickoff' ordenable. Devuelve la misma lista con
    'elo_home_pre', 'elo_away_pre', 'elo_diff' añadidos SIN leakage.
    Los partidos sin resultado (futuros) reciben el Elo actual y no actualizan.
    """
    elo = EloRatings(**kwargs)
    ordered = sorted(matches, key=lambda m: m.get("kickoff", 0))
    out = []
    for m in ordered:
        row = dict(m)
        neutral = bool(m.get("neutral", False))
        pre_h = elo.get(m["home"])
        pre_a = elo.get(m["away"])
        row["elo_home_pre"] = pre_h
        row["elo_away_pre"] = pre_a
        row["elo_diff"] = pre_h - pre_a
        hg, ag = m.get("home_goals"), m.get("away_goals")
        if hg is not None and ag is not None:
            elo.update(m["home"], m["away"], hg, ag, neutral=neutral)
        out.append(row)
    return out
