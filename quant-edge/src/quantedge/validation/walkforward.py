"""Walk-forward anidado: selección interna por CV purgada + evaluación OOS.

Para cada tramo externo (train -> test):
  1. Sobre el TRAIN se elige la mejor configuración por validación cruzada
     purgada con embargo (nunca se mira el test del tramo).
  2. La configuración elegida se evalúa en el TEST externo.
  3. Se concatenan los tests externos -> pista de resultados fuera de muestra.

Además se construye la matriz (T x N) de retornos de TODOS los candidatos sobre
el conjunto de desarrollo, base para PBO y para la varianza de Sharpe del DSR.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..backtest.engine import run_backtest
from ..costs.model import InstrumentCosts
from ..strategies.base import Strategy
from .metrics import sharpe_per_observation
from .splitters import purged_kfold, walk_forward


def _cv_score(df: pd.DataFrame, cand: Strategy, costs: InstrumentCosts, n_splits: int,
              embargo: float, label_horizon: int) -> float:
    bt = run_backtest(df, cand, costs)
    r = bt.net_returns_after_tax.to_numpy()
    scores = []
    for sp in purged_kfold(len(df), n_splits, embargo, label_horizon):
        seg = r[sp.test_idx]
        if np.isfinite(seg).sum() >= 5:
            scores.append(sharpe_per_observation(seg))
    return float(np.nanmean(scores)) if scores else -np.inf


def select_best_on_train(df: pd.DataFrame, candidates: list[Strategy], costs: InstrumentCosts,
                         n_splits: int = 4, embargo: float = 0.01, label_horizon: int = 1) -> Strategy:
    best, best_sr = candidates[0], -np.inf
    for cand in candidates:
        sr = _cv_score(df, cand, costs, n_splits, embargo, label_horizon)
        if sr > best_sr:
            best_sr, best = sr, cand
    return best


@dataclass
class WalkForwardResult:
    oos_returns: pd.Series
    selected_per_fold: list[str] = field(default_factory=list)
    selected_objs: list[Strategy] = field(default_factory=list)
    test_idx_per_fold: list = field(default_factory=list)


def nested_walk_forward(df: pd.DataFrame, candidates: list[Strategy], costs: InstrumentCosts,
                        n_outer: int = 6, inner_splits: int = 4, embargo: float = 0.01,
                        label_horizon: int = 1) -> WalkForwardResult:
    oos_parts: list[pd.Series] = []
    selected: list[str] = []
    selected_objs: list[Strategy] = []
    test_idxs: list = []
    for sp in walk_forward(len(df), n_outer, "expanding", embargo, label_horizon):
        train_df = df.iloc[sp.train_idx]
        best = select_best_on_train(train_df, candidates, costs, inner_splits, embargo, label_horizon)
        # Backtest sobre el prefijo hasta el fin del test para respetar el warmup,
        # y se toman sólo las filas del test externo.
        prefix = df.iloc[: int(sp.test_idx[-1]) + 1]
        bt = run_backtest(prefix, best, costs)
        oos_parts.append(bt.net_returns_after_tax.iloc[sp.test_idx])
        selected.append(best.key())
        selected_objs.append(best)
        test_idxs.append(sp.test_idx)
    oos = pd.concat(oos_parts) if oos_parts else pd.Series(dtype=float)
    return WalkForwardResult(
        oos_returns=oos,
        selected_per_fold=selected,
        selected_objs=selected_objs,
        test_idx_per_fold=test_idxs,
    )


def replay_oos(df: pd.DataFrame, wf: WalkForwardResult, costs: InstrumentCosts) -> pd.Series:
    """Reproduce la pista OOS con las MISMAS estrategias seleccionadas pero otros
    costes (escenario de estrés). No re-selecciona: mide la misma decisión bajo
    peor fricción, que es exactamente lo que exige el test de robustez de costes.
    """
    parts: list[pd.Series] = []
    for best, test_idx in zip(wf.selected_objs, wf.test_idx_per_fold):
        prefix = df.iloc[: int(test_idx[-1]) + 1]
        bt = run_backtest(prefix, best, costs)
        parts.append(bt.net_returns_after_tax.iloc[test_idx])
    return pd.concat(parts) if parts else pd.Series(dtype=float)


@dataclass
class CandidateMatrix:
    returns_matrix: np.ndarray     # (T x N) retornos netos de cada candidato
    sharpes: np.ndarray            # Sharpe por observación de cada candidato
    names: list[str]

    @property
    def n_trials(self) -> int:
        return len(self.names)

    @property
    def sr_variance(self) -> float:
        s = self.sharpes[np.isfinite(self.sharpes)]
        return float(np.var(s, ddof=1)) if s.size > 1 else 0.0


def candidate_matrix(df: pd.DataFrame, candidates: list[Strategy], costs: InstrumentCosts) -> CandidateMatrix:
    cols, names, sharpes = [], [], []
    for cand in candidates:
        r = run_backtest(df, cand, costs).net_returns_after_tax.to_numpy()
        cols.append(r)
        names.append(cand.key())
        sharpes.append(sharpe_per_observation(r))
    mat = np.column_stack(cols)
    return CandidateMatrix(returns_matrix=mat, sharpes=np.array(sharpes), names=names)
