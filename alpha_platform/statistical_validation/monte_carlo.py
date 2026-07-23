import numpy as np
from typing import Dict

class MonteCarloSimulator:
    """
    Simulates 10,000 randomized resampled trade distribution paths 
    to estimate Maximum Drawdown, Value at Risk (VaR 99%), and Survival Probability.
    """

    def __init__(self, num_simulations: int = 10000):
        self.num_simulations = num_simulations

    def run_simulation(self, trade_returns: np.ndarray) -> Dict[str, float]:
        if len(trade_returns) < 10:
            return {
                "max_drawdown_p99": 1.0,
                "var_99": 1.0,
                "survival_rate": 0.0
            }

        n_trades = len(trade_returns)
        drawdowns = []
        final_returns = []

        for _ in range(self.num_simulations):
            # Block bootstrap / random choice with replacement
            sampled_returns = np.random.choice(trade_returns, size=n_trades, replace=True)
            equity_curve = np.cumprod(1.0 + sampled_returns)
            
            peak = np.maximum.accumulate(equity_curve)
            dd = (peak - equity_curve) / peak
            max_dd = float(np.max(dd))
            
            drawdowns.append(max_dd)
            final_returns.append(float(equity_curve[-1] - 1.0))

        drawdowns = np.array(drawdowns)
        max_dd_p99 = float(np.percentile(drawdowns, 99))
        var_99 = float(np.percentile(trade_returns, 1))
        survival_rate = float(np.mean(drawdowns < 0.20))  # Percentage of paths staying under 20% drawdown

        return {
            "max_drawdown_p99": max_dd_p99,
            "var_99": var_99,
            "survival_rate": survival_rate
        }
