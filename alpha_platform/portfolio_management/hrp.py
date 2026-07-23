import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from typing import Dict

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
        inv_diag = 1.0 / np.diag(sub_cov)
        weights = inv_diag / np.sum(inv_diag)
        return float(np.dot(np.dot(weights, sub_cov), weights))

    def allocate(self, cov_matrix: pd.DataFrame) -> Dict[str, float]:
        if cov_matrix.empty or len(cov_matrix) == 1:
            return {col: 1.0 for col in cov_matrix.columns}

        cov = cov_matrix.values
        corr = cov_matrix.corr().values

        # Distance matrix
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0, 1))

        # Hierarchical Clustering Linkage
        link = linkage(dist, method="single")
        
        # Quasi-Diagonalization sorting
        sort_ix = list(range(len(cov_matrix)))

        # Recursive Bisection Risk Allocation
        weights = pd.Series(1.0, index=sort_ix)
        cluster_items = [sort_ix]

        while len(cluster_items) > 0:
            cluster_items = [
                i[j:k] for i in cluster_items for j, k in ((0, len(i) // 2), (len(i) // 2, len(i))) if len(i) > 1
            ]
            for i in range(0, len(cluster_items), 2):
                c0 = cluster_items[i]
                c1 = cluster_items[i + 1]
                v0 = self.get_cluster_var(cov, c0)
                v1 = self.get_cluster_var(cov, c1)
                alpha = 1.0 - v0 / (v0 + v1 + 1e-8)
                weights[c0] *= alpha
                weights[c1] *= 1.0 - alpha

        res = {cov_matrix.columns[i]: float(weights[i]) for i in range(len(cov_matrix))}
        total_w = sum(res.values())
        return {k: v / total_w for k, v in res.items()}
