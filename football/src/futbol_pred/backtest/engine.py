"""Motor de validación walk-forward para fútbol (tus #59, #60).

PROHIBIDO el split aleatorio: entrenamos con el pasado y predecimos el futuro,
avanzando ronda a ronda. Cada predicción usa EXCLUSIVAMENTE partidos anteriores
a esa ronda, así que el backtest refleja lo que habrías vivido en real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import aggregate, calibration_table
from .predictors import _outcome
from ..scheduling import is_finished


def _round_key(m: dict) -> tuple:
    return (m.get("competition", "league"), m.get("stage") or "REGULAR",
            m.get("matchday"))


def _rounds_in_order(matches: list[dict]) -> list[tuple]:
    """Rondas ordenadas por la fecha más temprana de sus partidos."""
    earliest: dict[tuple, float] = {}
    for m in matches:
        k = _round_key(m)
        ko = m.get("kickoff")
        if ko is not None and (k not in earliest or ko < earliest[k]):
            earliest[k] = ko
    return sorted(earliest, key=lambda k: earliest[k])


@dataclass
class BacktestResult:
    predictions: list[tuple[dict, str]] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)

    def metrics(self) -> dict:
        return aggregate(self.predictions)

    def calibration(self, selection: str = "1", bins: int = 10) -> list[dict]:
        return calibration_table(self.predictions, selection, bins)


def walk_forward(
    matches: list[dict],
    predictor,
    min_train_rounds: int = 3,
) -> BacktestResult:
    """Ejecuta walk-forward: por cada ronda, entrena con lo anterior y predice.

    ``predictor`` debe implementar fit(matches) y predict(home, away).
    Se reentrena en cada ronda con la ventana expandida (todo el pasado).
    """
    rounds = _rounds_in_order(matches)
    by_round: dict[tuple, list[dict]] = {}
    for m in matches:
        by_round.setdefault(_round_key(m), []).append(m)

    seen: list[dict] = []
    result = BacktestResult()

    for i, rk in enumerate(rounds):
        round_matches = by_round[rk]
        if i >= min_train_rounds:
            predictor.fit(seen)
            for m in round_matches:
                if not is_finished(m):
                    continue
                probs = predictor.predict(m["home"], m["away"])
                if probs is None:
                    continue
                actual = _outcome(m)
                result.predictions.append((probs, actual))
                result.records.append({
                    "round": rk,
                    "home": m["home"],
                    "away": m["away"],
                    "probs": probs,
                    "actual": actual,
                    "odds": m.get("odds"),
                })
        # Solo después de predecir, la ronda pasa a ser "pasado".
        seen.extend(m for m in round_matches if is_finished(m))

    return result


def compare_predictors(
    matches: list[dict], predictors: dict[str, object], min_train_rounds: int = 3
) -> dict[str, dict]:
    """Corre varios predictores sobre el mismo backtest y compara métricas."""
    out = {}
    for name, pred in predictors.items():
        res = walk_forward(matches, pred, min_train_rounds=min_train_rounds)
        out[name] = res.metrics()
    return out
