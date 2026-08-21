"""Generador de quiniela española (14 partidos 1X2 + Pleno al 15).

Dada la probabilidad 1X2 de cada partido, produce:
  * la columna "simple" (signo más probable de cada partido),
  * una apuesta reducida/múltiple: coloca dobles y triples en los partidos
    más inciertos para maximizar aciertos esperados sin disparar el coste,
  * el Pleno al 15 (goles 0/1/2/M de cada equipo del partido 15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

SIGNS = ("1", "X", "2")


@dataclass
class MatchForecast:
    home: str
    away: str
    probs: dict[str, float]  # {'1':.., 'X':.., '2':..}

    def best_sign(self) -> str:
        return max(SIGNS, key=lambda s: self.probs[s])

    def entropy(self) -> float:
        """Incertidumbre del partido (mayor = más impredecible)."""
        import math

        return -sum(
            p * math.log(p) for p in self.probs.values() if p > 0
        )

    def signs_by_prob(self) -> list[str]:
        return sorted(SIGNS, key=lambda s: self.probs[s], reverse=True)


@dataclass
class PlenoForecast:
    home_goals: dict[str, float]  # claves '0','1','2','M'
    away_goals: dict[str, float]

    def best(self) -> tuple[str, str]:
        h = max(self.home_goals, key=lambda k: self.home_goals[k])
        a = max(self.away_goals, key=lambda k: self.away_goals[k])
        return h, a


@dataclass
class QuinielaColumn:
    signs: list[str]
    pleno: tuple[str, str] | None = None


@dataclass
class QuinielaBet:
    base: list[str] = field(default_factory=list)       # signo simple x14
    multiples: dict[int, list[str]] = field(default_factory=dict)  # idx -> signos
    pleno: tuple[str, str] | None = None

    @property
    def cost_columns(self) -> int:
        cost = 1
        for idx in range(14):
            cost *= len(self.multiples.get(idx, [self.base[idx]]))
        return cost

    def expected_hits(self, forecasts: list[MatchForecast]) -> float:
        """Aciertos esperados de la columna base (0-14)."""
        return sum(f.probs[self.base[i]] for i, f in enumerate(forecasts))

    def prob_all_correct(self, forecasts: list[MatchForecast]) -> float:
        """Prob. de acertar los 14 con al menos una columna del boleto."""
        p = 1.0
        for i, f in enumerate(forecasts):
            sel = self.multiples.get(i, [self.base[i]])
            p *= sum(f.probs[s] for s in sel)
        return p

    def columns(self) -> list[QuinielaColumn]:
        """Expande el boleto múltiple a todas sus columnas simples."""
        opts = [self.multiples.get(i, [self.base[i]]) for i in range(14)]
        return [QuinielaColumn(list(c), self.pleno) for c in product(*opts)]


def generate_quiniela(
    forecasts: list[MatchForecast],
    pleno: PlenoForecast | None = None,
    triples: int = 0,
    doubles: int = 0,
) -> QuinielaBet:
    """Genera un boleto colocando dobles/triples en los partidos más inciertos.

    triples: nº de partidos donde jugamos los 3 signos.
    doubles: nº de partidos donde jugamos los 2 signos más probables.
    El coste en columnas es 3**triples * 2**doubles.
    """
    if len(forecasts) != 14:
        raise ValueError("La quiniela requiere exactamente 14 partidos")

    base = [f.best_sign() for f in forecasts]
    bet = QuinielaBet(base=base, pleno=pleno.best() if pleno else None)

    # Ordenamos por incertidumbre (entropía) descendente.
    ranked = sorted(range(14), key=lambda i: forecasts[i].entropy(), reverse=True)

    used: set[int] = set()
    for idx in ranked[:triples]:
        bet.multiples[idx] = list(SIGNS)
        used.add(idx)
    for idx in ranked:
        if len([i for i in bet.multiples if len(bet.multiples[i]) == 2]) >= doubles:
            break
        if idx in used:
            continue
        bet.multiples[idx] = forecasts[idx].signs_by_prob()[:2]
        used.add(idx)

    return bet
