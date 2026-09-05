"""Distribución conjunta de goles y todos los mercados derivados.

La idea central del sistema: una vez tenemos la matriz de probabilidad
P(goles_local = x, goles_visitante = y), CUALQUIER mercado es un simple
sumatorio sobre esa matriz. Eso hace que 1X2, over/under de cualquier línea,
hándicaps asiáticos, BTTS, resultado exacto, etc. sean todos "paramétricos":
se piden con la línea que quieras (+/- lo que sea) y se calculan al vuelo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ScoreMatrix:
    """Matriz de probabilidad conjunta de goles local x visitante.

    ``matrix[x, y]`` = P(local marca x, visitante marca y).
    """

    matrix: np.ndarray

    def __post_init__(self) -> None:
        self.matrix = np.asarray(self.matrix, dtype=float)
        if (self.matrix.ndim != 2 or not self.matrix.size
                or not np.isfinite(self.matrix).all() or (self.matrix < 0).any()):
            raise ValueError("La matriz debe ser bidimensional, finita y no negativa")
        total = self.matrix.sum()
        if total <= 0:
            raise ValueError("La matriz de probabilidad no puede sumar 0")
        # Normalizamos por si el truncado de goles perdió una cola de masa.
        self.matrix = self.matrix / total

    @property
    def max_goals(self) -> int:
        return self.matrix.shape[0] - 1

    # ---- Mercado 1X2 ------------------------------------------------------
    def one_x_two(self) -> dict[str, float]:
        home = np.tril(self.matrix, -1).sum()  # x > y
        draw = np.trace(self.matrix)  # x == y
        away = np.triu(self.matrix, 1).sum()  # x < y
        return {"1": float(home), "X": float(draw), "2": float(away)}

    def prob_sign(self, sign: str) -> float:
        return self.one_x_two()[sign]

    # ---- Doble oportunidad -----------------------------------------------
    def double_chance(self) -> dict[str, float]:
        p = self.one_x_two()
        return {
            "1X": p["1"] + p["X"],
            "12": p["1"] + p["2"],
            "X2": p["X"] + p["2"],
        }

    # ---- Totales (over/under) para CUALQUIER línea ------------------------
    def total_goals_dist(self) -> np.ndarray:
        """Distribución del total de goles (índice = nº de goles)."""
        n = self.matrix.shape[0] + self.matrix.shape[1] - 1
        dist = np.zeros(n)
        for x in range(self.matrix.shape[0]):
            for y in range(self.matrix.shape[1]):
                dist[x + y] += self.matrix[x, y]
        return dist

    def over(self, line: float) -> float:
        """P(total de goles > line). Línea .5 => sin push."""
        dist = self.total_goals_dist()
        goals = np.arange(len(dist))
        return float(dist[goals > line].sum())

    def under(self, line: float) -> float:
        return float(1.0 - self.over(line) - self._push_total(line))

    def _push_total(self, line: float) -> float:
        """Masa exactamente en la línea (líneas enteras => posible push)."""
        if abs(line - round(line)) < 1e-9:
            dist = self.total_goals_dist()
            k = int(round(line))
            if 0 <= k < len(dist):
                return float(dist[k])
        return 0.0

    # ---- Ambos marcan (BTTS) ---------------------------------------------
    def btts(self) -> dict[str, float]:
        yes = float(self.matrix[1:, 1:].sum())
        return {"yes": yes, "no": 1.0 - yes}

    # ---- Hándicap asiático (paramétrico) ---------------------------------
    def asian_handicap(self, line: float, side: str = "home") -> dict[str, float]:
        """Hándicap asiático para local/visitante con línea arbitraria.

        Devuelve prob. de ganar, empatar (push, se devuelve la apuesta) y
        perder la apuesta. Soporta líneas cuartos (p. ej. -0.25) partiéndolas.
        """
        side = side.lower()
        if side not in ("home", "away"):
            raise ValueError("side debe ser 'home' o 'away'")

        # Las líneas de cuarto (.25/.75) son medias de dos líneas contiguas.
        frac = round((line * 2) % 1, 6)
        if abs(frac - 0.5) < 1e-9:
            low = line - 0.25
            high = line + 0.25
            a = self.asian_handicap(low, side)
            b = self.asian_handicap(high, side)
            return {k: (a[k] + b[k]) / 2 for k in a}

        win = lose = push = 0.0
        for x in range(self.matrix.shape[0]):
            for y in range(self.matrix.shape[1]):
                p = self.matrix[x, y]
                if p == 0:
                    continue
                margin = (x - y) if side == "home" else (y - x)
                adj = margin + line
                if adj > 1e-9:
                    win += p
                elif adj < -1e-9:
                    lose += p
                else:
                    push += p
        return {"win": float(win), "push": float(push), "lose": float(lose)}

    # ---- Resultado exacto -------------------------------------------------
    def correct_score(self, home: int, away: int) -> float:
        if home < 0 or away < 0 or home >= self.matrix.shape[0] or away >= self.matrix.shape[1]:
            return 0.0
        return float(self.matrix[home, away])

    def top_correct_scores(self, n: int = 5) -> list[tuple[int, int, float]]:
        flat = [
            (x, y, float(self.matrix[x, y]))
            for x in range(self.matrix.shape[0])
            for y in range(self.matrix.shape[1])
        ]
        flat.sort(key=lambda t: t[2], reverse=True)
        return flat[:n]

    def distribution_summary(self) -> dict:
        """Rangos exactos de la distribución; evita vender un marcador puntual como certeza."""

        total = self.total_goals_dist()
        cumulative = np.cumsum(total)

        def quantile(probability: float) -> int:
            return int(np.searchsorted(cumulative, probability, side="left"))

        scores = self.top_correct_scores(6)
        return {
            "total_goals_p10_p50_p90": [quantile(0.10), quantile(0.50), quantile(0.90)],
            "top_scores": [
                {"score": f"{home}-{away}", "probability": round(probability, 4)}
                for home, away, probability in scores
            ],
            "top_six_probability": round(sum(row[2] for row in scores), 4),
            "method": "distribución Dixon-Coles completa; sin muestreo Monte Carlo",
        }

    # ---- Goles esperados (para sanity checks) ----------------------------
    def expected_goals(self) -> tuple[float, float]:
        xs = np.arange(self.matrix.shape[0])
        ys = np.arange(self.matrix.shape[1])
        eh = float((self.matrix.sum(axis=1) * xs).sum())
        ea = float((self.matrix.sum(axis=0) * ys).sum())
        return eh, ea
