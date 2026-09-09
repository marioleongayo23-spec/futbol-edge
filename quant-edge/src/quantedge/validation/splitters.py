"""Particiones temporales SIN fuga de información.

Implementa (López de Prado, *Advances in Financial Machine Learning*):
  - Purga: se eliminan del entrenamiento las muestras cuya ventana de etiqueta
    solapa con el test.
  - Embargo: se descartan muestras justo posteriores al test para romper la
    autocorrelación serial.
  - Walk-forward anidado: bucle externo (train -> OOS) y, dentro de cada train,
    validación cruzada purgada para elegir hiperparámetros. El test final
    (holdout) queda reservado y NUNCA se usa para seleccionar.
  - CPCV: combinaciones de bloques test para estimar la Probabilidad de
    Sobreajuste del Backtest (PBO).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class Split:
    train_idx: np.ndarray
    test_idx: np.ndarray
    fold: int


def _embargo_count(n: int, embargo: float) -> int:
    return int(round(embargo * n))


def purged_kfold(
    n: int, n_splits: int = 5, embargo: float = 0.01, label_horizon: int = 1
) -> list[Split]:
    """K-Fold purgado con embargo sobre índices temporales 0..n-1 contiguos."""
    if n_splits < 2:
        raise ValueError("n_splits >= 2")
    indices = np.arange(n)
    folds = np.array_split(indices, n_splits)
    emb = _embargo_count(n, embargo)
    splits: list[Split] = []
    for k, test_idx in enumerate(folds):
        if test_idx.size == 0:
            continue
        t0, t1 = int(test_idx[0]), int(test_idx[-1])
        mask = np.ones(n, dtype=bool)
        mask[t0 : t1 + 1] = False  # el test nunca entrena
        # Purga a la izquierda: etiquetas que se extienden hasta dentro del test.
        mask[max(0, t0 - label_horizon) : t0] = False
        # Embargo a la derecha.
        mask[t1 + 1 : min(n, t1 + 1 + emb)] = False
        splits.append(Split(train_idx=indices[mask], test_idx=test_idx, fold=k))
    return splits


def walk_forward(
    n: int,
    n_folds: int = 6,
    mode: str = "expanding",
    embargo: float = 0.01,
    label_horizon: int = 1,
) -> list[Split]:
    """Walk-forward: primer bloque = train inicial; el resto = ventanas OOS.

    mode='expanding' amplía el train con cada paso; 'rolling' mantiene una
    ventana de tamaño similar al bloque previo. Siempre hay purga+embargo entre
    train y test.
    """
    if n_folds < 2:
        raise ValueError("n_folds >= 2")
    bounds = np.array_split(np.arange(n), n_folds)
    emb = _embargo_count(n, embargo)
    splits: list[Split] = []
    for k in range(1, n_folds):
        test_idx = bounds[k]
        if test_idx.size == 0:
            continue
        t0 = int(test_idx[0])
        train_end = max(0, t0 - label_horizon - emb)
        if mode == "expanding":
            train_start = 0
        elif mode == "rolling":
            train_start = int(bounds[k - 1][0])
        else:
            raise ValueError("mode debe ser 'expanding' o 'rolling'")
        train_idx = np.arange(train_start, train_end)
        if train_idx.size == 0:
            continue
        splits.append(Split(train_idx=train_idx, test_idx=test_idx, fold=k))
    return splits


def holdout_split(
    n: int, holdout_frac: float = 0.3, embargo: float = 0.01, label_horizon: int = 1
) -> tuple[np.ndarray, np.ndarray]:
    """Reserva el ÚLTIMO tramo como test oculto, con purga+embargo de separación.

    Devuelve (dev_idx, holdout_idx). `dev_idx` es lo único que puede tocarse
    para desarrollar/seleccionar; `holdout_idx` se evalúa una sola vez al final.
    """
    holdout_start = int(round(n * (1.0 - holdout_frac)))
    holdout_idx = np.arange(holdout_start, n)
    emb = _embargo_count(n, embargo)
    dev_end = max(0, holdout_start - label_horizon - emb)
    dev_idx = np.arange(0, dev_end)
    return dev_idx, holdout_idx


def cpcv_test_groups(n_groups: int = 10, k_test: int = 2) -> list[tuple[int, ...]]:
    """Combinaciones de grupos usadas como test en CPCV (para PBO)."""
    return list(combinations(range(n_groups), k_test))


def group_bounds(n: int, n_groups: int) -> list[np.ndarray]:
    return [g for g in np.array_split(np.arange(n), n_groups) if g.size]
