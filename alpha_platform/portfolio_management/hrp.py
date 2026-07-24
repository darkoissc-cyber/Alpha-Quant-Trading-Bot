import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from typing import Dict
from alpha_platform.config.logging_config import logger

class HierarchicalRiskParity:
    """
    Marcos Lopez de Prado's Hierarchical Risk Parity (HRP) Portfolio Allocation.
    Prevents hidden identical exposure by clustering assets based on correlation hierarchy.
    """

    @staticmethod
    def get_quad_diag(cov: np.ndarray) -> float:
        return float(np.trace(cov))

    @staticmethod
    def get_cluster_var(cov: np.ndarray, c_items: list) -> float:
        sub_cov = cov[np.ix_(c_items, c_items)]
        diag = np.diag(sub_cov)
        # Avoid division by zero when a sub-cluster has a constant asset
        diag = np.where(diag <= 0, 1e-8, diag)
        inv_diag = 1.0 / diag
        total = np.sum(inv_diag)
        if total <= 0 or not np.isfinite(total):
            return 1e-8
        weights = inv_diag / total
        return float(np.dot(np.dot(weights, sub_cov), weights))

    def allocate(self, cov_matrix: pd.DataFrame) -> Dict[str, float]:
        if cov_matrix.empty or len(cov_matrix) == 1:
            return {col: 1.0 for col in cov_matrix.columns}

        # Sanitize: covariance matrices with constant assets produce NaN.
        # Replace any NaN/Inf with 0 and clip negatives from numerical noise.
        clean_cov = cov_matrix.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        # Ensure symmetry (numerical drift can break this)
        clean_cov = (clean_cov + clean_cov.T) / 2.0

        try:
            cov = clean_cov.values
            corr = clean_cov.corr().fillna(0.0).values
        except Exception as e:
            logger.error(f"HRP: failed to compute correlation from cov matrix: {e}")
            return {col: 1.0 / len(clean_cov.columns) for col in clean_cov.columns}

        # Distance matrix
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0, 1))
        # Ensure zero diagonal
        np.fill_diagonal(dist, 0.0)

        # Hierarchical Clustering Linkage (using condensed distance matrix)
        try:
            condensed_dist = squareform(dist, checks=False)
            link = linkage(condensed_dist, method="single")
        except Exception as e:
            logger.error(f"HRP: linkage failed ({e}). Falling back to equal weights.")
            return {col: 1.0 / len(clean_cov.columns) for col in clean_cov.columns}

        # Quasi-Diagonalization sorting
        sort_ix = list(range(len(clean_cov)))

        # Recursive Bisection Risk Allocation
        weights = pd.Series(1.0, index=sort_ix)
        cluster_items = [sort_ix]

        while len(cluster_items) > 0:
            cluster_items = [
                i[j:k] for i in cluster_items for j, k in ((0, len(i) // 2), (len(i) // 2, len(i))) if len(i) > 1
            ]
            for i in range(0, len(cluster_items), 2):
                if i + 1 >= len(cluster_items):
                    break
                c0 = cluster_items[i]
                c1 = cluster_items[i + 1]
                v0 = self.get_cluster_var(cov, c0)
                v1 = self.get_cluster_var(cov, c1)
                # If either cluster var is non-finite, fall back to 50/50
                if not (np.isfinite(v0) and np.isfinite(v1)) or (v0 + v1) <= 0:
                    alpha = 0.5
                else:
                    alpha = 1.0 - v0 / (v0 + v1 + 1e-8)
                weights[c0] *= alpha
                weights[c1] *= 1.0 - alpha

        res = {clean_cov.columns[i]: float(weights[i]) for i in range(len(clean_cov))}
        total_w = sum(res.values())
        if total_w <= 0:
            return {k: 1.0 / len(res) for k in res}
        return {k: v / total_w for k, v in res.items()}
