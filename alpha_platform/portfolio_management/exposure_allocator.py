import numpy as np
import pandas as pd
from typing import Dict, List
from alpha_platform.portfolio_management.hrp import HierarchicalRiskParity
from alpha_platform.config.logging_config import logger

class PortfolioExposureAllocator:
    def __init__(self, target_portfolio_volatility: float = 0.10, max_asset_exposure: float = 0.35):
        self.target_vol = target_portfolio_volatility
        self.max_asset_exposure = max_asset_exposure
        self.hrp = HierarchicalRiskParity()

    def compute_portfolio_weights(
        self,
        returns_df: pd.DataFrame,
        current_volatilities: Dict[str, float]
    ) -> Dict[str, float]:
        if returns_df.empty or len(returns_df.columns) == 0:
            return {}

        # 1. HRP Allocation
        cov_matrix = returns_df.cov()
        raw_weights = self.hrp.allocate(cov_matrix)

        # 2. Apply max individual asset cap
        capped_weights = {}
        for k, w in raw_weights.items():
            capped_weights[k] = min(w, self.max_asset_exposure)

        # Normalize
        total_w = sum(capped_weights.values())
        if total_w > 0:
            capped_weights = {k: v / total_w for k, v in capped_weights.items()}

        # 3. Volatility Targeting Scaling Factor
        weighted_vol = sum(capped_weights[asset] * current_volatilities.get(asset, 0.15) for asset in capped_weights)
        vol_scalar = self.target_vol / (weighted_vol + 1e-8)
        vol_scalar = min(vol_scalar, 1.5)  # Cap leverage multiplier at 1.5x

        final_weights = {k: float(v * vol_scalar) for k, v in capped_weights.items()}
        logger.info(f"Portfolio HRP Allocation computed with Vol Targeting scalar {vol_scalar:.2f}: {final_weights}")

        return final_weights
