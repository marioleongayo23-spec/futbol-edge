"""Modelo Dixon-Coles para estimar la matriz de goles de un partido.

Dixon & Coles (1997) parte de dos Poisson (goles local / visitante) y añade:
  * fuerza de ataque y defensa por equipo,
  * ventaja de jugar en casa,
  * una corrección ``rho`` para los resultados bajos (0-0, 1-0, 0-1, 1-1),
    donde la Poisson independiente ajusta mal,
  * ponderación temporal exponencial: los partidos recientes pesan más.

Es un modelo interpretable, rápido de ajustar y con buen rendimiento real.
Cuando integremos xG, alimentaremos ``lambdas`` con expected-goals en vez de
(o mezclado con) goles reales para reducir ruido.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from .score_matrix import ScoreMatrix


def _tau(x: np.ndarray, y: np.ndarray, lh: float, la: float, rho: float) -> np.ndarray:
    """Corrección Dixon-Coles para resultados bajos."""
    x, y, lh, la = np.broadcast_arrays(x, y, lh, la)
    out = np.ones_like(x, dtype=float)
    out = np.where((x == 0) & (y == 0), 1 - lh * la * rho, out)
    out = np.where((x == 0) & (y == 1), 1 + lh * rho, out)
    out = np.where((x == 1) & (y == 0), 1 + la * rho, out)
    out = np.where((x == 1) & (y == 1), 1 - rho, out)
    return out


@dataclass
class DixonColesModel:
    """Ajusta fuerzas de ataque/defensa y predice partidos."""

    xi: float = 0.0018  # decaimiento temporal (~medio año de vida útil)
    max_goals: int = 10
    # Regularización L2 (ridge) sobre ataque/defensa: estabiliza el ajuste y
    # evita que equipos con datos escasos o en un "componente desconectado"
    # (p. ej. un ascendido cuyo histórico es solo de Segunda, sin cruces con
    # Primera) disparen sus parámetros al límite y produzcan xG absurdos.
    l2: float = 0.5
    rho: float = 0.0
    home_adv: float = 0.0
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    fitted: bool = False
    # Prior para equipos sin histórico (recién ascendidos): en vez de "media de
    # liga" (0,0), se estiman con perfil de equipo de ascenso — ataque flojo y
    # defensa floja — a partir de la distribución ya ajustada.
    promoted_attack: float = 0.0
    promoted_defence: float = 0.0

    # ------------------------------------------------------------------
    def _weights(self, days_ago: np.ndarray) -> np.ndarray:
        return np.exp(-self.xi * np.asarray(days_ago, dtype=float))

    def fit(
        self,
        home_teams: list[str],
        away_teams: list[str],
        home_goals: list[int],
        away_goals: list[int],
        days_ago: list[float] | None = None,
    ) -> "DixonColesModel":
        """Ajusta el modelo por máxima verosimilitud ponderada.

        ``days_ago`` = días transcurridos desde cada partido hasta "hoy".
        Si es None, todos los partidos pesan igual.
        """
        teams = sorted(set(home_teams) | set(away_teams))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hg = np.asarray(home_goals, dtype=int)
        ag = np.asarray(away_goals, dtype=int)
        hi = np.asarray([idx[t] for t in home_teams])
        ai = np.asarray([idx[t] for t in away_teams])
        w = self._weights(days_ago) if days_ago is not None else np.ones(len(hg))

        # Parámetros: [attack(n), defence(n), home_adv, rho]
        # Restricción de identificabilidad: media de ataques = 0.
        init = np.concatenate([
            np.zeros(n),  # attack
            np.zeros(n),  # defence
            [0.25],       # home_adv
            [0.0],        # rho
        ])

        def neg_log_like(params: np.ndarray) -> float:
            att = params[:n]
            deff = params[n : 2 * n]
            home_adv = params[2 * n]
            rho = params[2 * n + 1]
            att = att - att.mean()  # centrado
            lh = np.exp(self.intercept + home_adv + att[hi] + deff[ai])
            la = np.exp(self.intercept + att[ai] + deff[hi])
            lh = np.clip(lh, 1e-6, 30)
            la = np.clip(la, 1e-6, 30)
            ll = poisson.logpmf(hg, lh) + poisson.logpmf(ag, la)
            # Each observation has its own intensities. League means fit a
            # different likelihood from the distribution used at prediction.
            tau = _tau(hg, ag, lh, la, rho)
            tau = np.clip(tau, 1e-9, None)
            ll = ll + np.log(tau)
            # Ridge: penaliza ataque (centrado) y defensa hacia 0 (media de liga).
            penalty = self.l2 * (float(att @ att) + float(deff @ deff))
            return -float((w * ll).sum()) + penalty

        bounds = [(-2, 2)] * (2 * n) + [(-1, 1), (-0.2, 0.2)]
        res = minimize(neg_log_like, init, method="L-BFGS-B", bounds=bounds)

        if not res.success or not np.isfinite(res.fun) or not np.isfinite(res.x).all():
            raise ValueError(f"Dixon-Coles no convergió: {res.message}")

        p = res.x
        att = p[:n] - p[:n].mean()
        self.attack = {t: float(att[idx[t]]) for t in teams}
        self.defence = {t: float(p[n : 2 * n][idx[t]]) for t in teams}
        self.home_adv = float(p[2 * n])
        self.rho = float(p[2 * n + 1])
        # Perfil de ascenso: ataque bajo (percentil 20) y defensa floja
        # (percentil 80 = concede más). Sirve de prior para equipos sin datos.
        att_vals = np.array(list(self.attack.values()))
        def_vals = np.array(list(self.defence.values()))
        if att_vals.size:
            self.promoted_attack = float(np.percentile(att_vals, 20))
            self.promoted_defence = float(np.percentile(def_vals, 80))
        self.fitted = True
        return self

    # ------------------------------------------------------------------
    def is_known(self, team: str) -> bool:
        return team in self.attack

    def _lambdas(self, home: str, away: str) -> tuple[float, float]:
        # Equipo sin histórico (p. ej. recién ascendido): prior con perfil de
        # ascenso (ataque flojo, defensa floja), no la media de liga. Así SIEMPRE
        # hay predicción y refleja que un ascendido suele ser más débil; el
        # modelo se afina según vaya jugando.
        ah = self.attack.get(home, self.promoted_attack)
        dh = self.defence.get(home, self.promoted_defence)
        aa = self.attack.get(away, self.promoted_attack)
        da = self.defence.get(away, self.promoted_defence)
        lh = np.exp(self.intercept + self.home_adv + ah + da)
        la = np.exp(self.intercept + aa + dh)
        return float(lh), float(la)

    def predict_matrix(
        self, home: str, away: str, lambdas: tuple[float, float] | None = None
    ) -> ScoreMatrix:
        """Genera la ScoreMatrix del partido.

        Si se pasan ``lambdas`` (p. ej. derivados de xG), se usan directamente
        en vez de las fuerzas ajustadas; útil para modelos híbridos.
        """
        if lambdas is None:
            lh, la = self._lambdas(home, away)
        else:
            lh, la = lambdas

        g = np.arange(self.max_goals + 1)
        ph = poisson.pmf(g, lh)
        pa = poisson.pmf(g, la)
        mat = np.outer(ph, pa)

        # Corrección Dixon-Coles en la esquina de resultados bajos.
        xx, yy = np.meshgrid(g, g, indexing="ij")
        mat = mat * _tau(xx, yy, lh, la, self.rho)
        mat = np.clip(mat, 0, None)
        return ScoreMatrix(mat)

    @staticmethod
    def matrix_from_lambdas(
        lh: float, la: float, rho: float = 0.0, max_goals: int = 10
    ) -> ScoreMatrix:
        """Atajo sin modelo ajustado: matriz a partir de dos lambdas y rho."""
        g = np.arange(max_goals + 1)
        mat = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
        xx, yy = np.meshgrid(g, g, indexing="ij")
        mat = np.clip(mat * _tau(xx, yy, lh, la, rho), 0, None)
        return ScoreMatrix(mat)
