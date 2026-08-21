"""Métricas de evaluación probabilística para 1X2.

En apuestas importa más una probabilidad BIEN CALIBRADA que acertar el ganador
(tu prompt #63). Por eso no nos fiamos del accuracy: usamos log loss, Brier y
RPS (Ranked Probability Score, estándar en forecasting de fútbol porque premia
acercarse al resultado ordenado 1-X-2).
"""

from __future__ import annotations

import math

CLASSES = ("1", "X", "2")


def _clip(p: float, eps: float = 1e-12) -> float:
    return min(1.0 - eps, max(eps, p))


def log_loss(probs: dict[str, float], actual: str) -> float:
    """Pérdida logarítmica de una predicción (menor es mejor)."""
    return -math.log(_clip(probs[actual]))


def brier_score(probs: dict[str, float], actual: str) -> float:
    """Brier multiclase: suma de (p_k - y_k)^2 (menor es mejor)."""
    return sum(
        (probs[c] - (1.0 if c == actual else 0.0)) ** 2 for c in CLASSES
    )


def rps(probs: dict[str, float], actual: str) -> float:
    """Ranked Probability Score sobre el orden 1-X-2 (menor es mejor)."""
    order = CLASSES
    cum_p = 0.0
    cum_o = 0.0
    total = 0.0
    for c in order[:-1]:  # r-1 términos
        cum_p += probs[c]
        cum_o += 1.0 if c == actual else 0.0
        total += (cum_p - cum_o) ** 2
    return total / (len(order) - 1)


def accuracy(probs: dict[str, float], actual: str) -> float:
    pred = max(CLASSES, key=lambda c: probs[c])
    return 1.0 if pred == actual else 0.0


def aggregate(predictions: list[tuple[dict[str, float], str]]) -> dict[str, float]:
    """Promedia todas las métricas sobre una lista de (probs, resultado)."""
    if not predictions:
        return {"n": 0}
    n = len(predictions)
    return {
        "n": n,
        "log_loss": sum(log_loss(p, a) for p, a in predictions) / n,
        "brier": sum(brier_score(p, a) for p, a in predictions) / n,
        "rps": sum(rps(p, a) for p, a in predictions) / n,
        "accuracy": sum(accuracy(p, a) for p, a in predictions) / n,
    }


def calibration_table(
    predictions: list[tuple[dict[str, float], str]],
    selection: str = "1",
    bins: int = 10,
) -> list[dict]:
    """Tabla de calibración para un signo: prob. media predicha vs frecuencia
    real observada por tramos. Bien calibrado => ambas columnas coinciden."""
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probs, actual in predictions:
        p = probs[selection]
        idx = min(bins - 1, int(p * bins))
        buckets[idx].append((p, 1 if actual == selection else 0))

    table = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        avg_pred = sum(p for p, _ in b) / len(b)
        obs_freq = sum(o for _, o in b) / len(b)
        table.append({
            "bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
            "n": len(b),
            "avg_pred": round(avg_pred, 3),
            "obs_freq": round(obs_freq, 3),
        })
    return table
