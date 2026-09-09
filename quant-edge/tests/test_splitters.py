import numpy as np

from quantedge.validation.splitters import (
    holdout_split,
    purged_kfold,
    walk_forward,
)


def test_purged_kfold_no_overlap_and_embargo():
    n = 1000
    for sp in purged_kfold(n, n_splits=5, embargo=0.02, label_horizon=3):
        # El test nunca aparece en el train.
        assert len(np.intersect1d(sp.train_idx, sp.test_idx)) == 0
        t1 = int(sp.test_idx[-1])
        emb = int(round(0.02 * n))
        # Zona de embargo posterior al test excluida del train.
        forbidden = set(range(t1 + 1, min(n, t1 + 1 + emb)))
        assert forbidden.isdisjoint(set(sp.train_idx.tolist()))
        # Purga previa: no hay train en [t0-h, t0).
        t0 = int(sp.test_idx[0])
        purged = set(range(max(0, t0 - 3), t0))
        assert purged.isdisjoint(set(sp.train_idx.tolist()))


def test_walk_forward_is_causal():
    # El train siempre precede al test (no mira el futuro).
    for sp in walk_forward(600, n_folds=6, mode="expanding", embargo=0.01):
        assert sp.train_idx.max() < sp.test_idx.min()


def test_holdout_is_last_and_separated():
    dev, hold = holdout_split(1000, holdout_frac=0.3, embargo=0.01, label_horizon=2)
    assert hold.min() > dev.max()          # holdout al final
    assert hold.min() - dev.max() >= 2      # separación por purga/embargo
    assert len(hold) == 300
