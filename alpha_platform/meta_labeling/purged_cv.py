import numpy as np
import pandas as pd
from typing import Generator, Tuple, List

class PurgedGroupTimeSeriesSplit:
    """
    Purged & Embargoed Cross-Validation to eliminate overlap leakage in meta-labeling.
    """
    def __init__(self, n_splits: int = 5, pct_embargo: float = 0.01):
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo

    def split(self, X: pd.DataFrame, y: pd.Series = None, groups: pd.Series = None) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        n_samples = len(X)
        indices = np.arange(n_samples)
        embargo = int(n_samples * self.pct_embargo)
        test_size = n_samples // self.n_splits

        for i in range(self.n_splits):
            test_start = i * test_size
            test_end = (i + 1) * test_size if i < self.n_splits - 1 else n_samples
            
            test_indices = indices[test_start:test_end]
            
            # Purge & Embargo train set
            train_indices = list(indices[:max(0, test_start - embargo)]) + list(indices[min(n_samples, test_end + embargo):])
            
            yield np.array(train_indices), test_indices
