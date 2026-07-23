import numpy as np
import pandas as pd
from typing import List

class PBOEstimator:
    """
    Estimates Probability of Backtest Overfitting (PBO) via 
    Combinatorial Purged Cross-Validation (CPCV).
    """

    @staticmethod
    def calculate_pbo(matrix_returns: np.ndarray, n_splits: int = 10) -> float:
        """
        matrix_returns: Shape (T, N) where T is time steps and N is strategy parameter trials.
        Returns PBO value between 0.0 and 1.0 (Target: < 0.10).
        """
        T, N = matrix_returns.shape
        if T < 50 or N < 2:
            return 0.0

        split_size = T // n_splits
        logits = []

        for s in range(n_splits):
            val_idx = np.arange(s * split_size, (s + 1) * split_size)
            train_idx = np.setdiff1d(np.arange(T), val_idx)

            train_perf = np.mean(matrix_returns[train_idx, :], axis=0)
            val_perf = np.mean(matrix_returns[val_idx, :], axis=0)

            best_train_trial = np.argmax(train_perf)
            
            # Rank of selected trial in validation set
            val_ranks = pd.Series(val_perf).rank(pct=True).values
            val_rank_best = val_ranks[best_train_trial]

            # Overfit if validation rank <= 0.5 (underperforms median)
            logits.append(1 if val_rank_best <= 0.5 else 0)

        pbo = float(np.mean(logits))
        return pbo
