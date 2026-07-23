import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from alpha_platform.config.logging_config import logger

@dataclass
class ExpectancyMetrics:
    expectancy_per_trade: float
    win_rate: float
    profit_factor: float
    recovery_factor: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_dollars: float
    gross_profit: float
    gross_loss: float

@dataclass
class BootstrapMetrics:
    expectancy_ci_lower: float
    expectancy_ci_upper: float
    win_rate_ci_lower: float
    win_rate_ci_upper: float
    max_dd_ci_95: float

class ExpectancyCalculator:
    """
    Calculates institutional trading performance metrics: Expectancy, Profit Factor,
    Recovery Factor, Sortino Ratio, Calmar Ratio, and Drawdown Distribution.
    """
    def compute_metrics(self, returns: np.ndarray, initial_capital: float = 10000.0) -> ExpectancyMetrics:
        if len(returns) == 0:
            return ExpectancyMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        wins = returns[returns > 0]
        losses = returns[returns < 0]

        win_rate = len(wins) / len(returns) if len(returns) > 0 else 0.0
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(np.mean(losses))) if len(losses) > 0 else 0.0

        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)

        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 0.0
        profit_factor = gross_profit / (gross_loss + 1e-8)

        # Cumulative equity curve for drawdown calculation
        cum_returns = np.cumsum(returns)
        equity_curve = initial_capital + cum_returns
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = running_max - equity_curve
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        net_profit = float(np.sum(returns))
        recovery_factor = net_profit / (max_dd + 1e-8)

        # Sortino Ratio (Downside volatility)
        downside_returns = returns[returns < 0]
        downside_std = float(np.std(downside_returns)) if len(downside_returns) > 0 else 1e-8
        sortino = (float(np.mean(returns)) / (downside_std + 1e-8)) * np.sqrt(252)

        # Calmar Ratio (Annualized return / Max Drawdown %)
        annualized_return = float(np.mean(returns)) * 252.0
        max_dd_pct = (max_dd / initial_capital) if initial_capital > 0 else 1e-8
        calmar = annualized_return / (max_dd_pct + 1e-8)

        return ExpectancyMetrics(
            expectancy_per_trade=round(expectancy, 4),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            recovery_factor=round(recovery_factor, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            max_drawdown_dollars=round(max_dd, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2)
        )

class BootstrapResampler:
    """
    Bootstrap Analysis (10,000 iterations) with replacement to compute 95% Confidence Intervals.
    """
    def __init__(self, num_bootstraps: int = 2000):
        self.num_bootstraps = num_bootstraps
        self.expectancy_calc = ExpectancyCalculator()

    def run_bootstrap(self, returns: np.ndarray) -> BootstrapMetrics:
        if len(returns) < 10:
            return BootstrapMetrics(0.0, 0.0, 0.0, 0.0, 0.0)

        n = len(returns)
        expectancies = []
        win_rates = []
        max_dds = []

        for _ in range(self.num_bootstraps):
            sample = np.random.choice(returns, size=n, replace=True)
            metrics = self.expectancy_calc.compute_metrics(sample)
            expectancies.append(metrics.expectancy_per_trade)
            win_rates.append(metrics.win_rate)
            max_dds.append(metrics.max_drawdown_dollars)

        exp_low = float(np.percentile(expectancies, 2.5))
        exp_high = float(np.percentile(expectancies, 97.5))
        wr_low = float(np.percentile(win_rates, 2.5))
        wr_high = float(np.percentile(win_rates, 97.5))
        dd_95 = float(np.percentile(max_dds, 95.0))

        return BootstrapMetrics(
            expectancy_ci_lower=round(exp_low, 4),
            expectancy_ci_upper=round(exp_high, 4),
            win_rate_ci_lower=round(wr_low, 4),
            win_rate_ci_upper=round(wr_high, 4),
            max_dd_ci_95=round(dd_95, 2)
        )

class WalkForwardOOSEfficiencyAnalyzer:
    """
    Evaluates In-Sample (IS) vs Out-Of-Sample (OOS) Walk-Forward Efficiency ratio.
    """
    def compute_oos_efficiency(self, is_returns: np.ndarray, oos_returns: np.ndarray) -> Dict[str, Any]:
        is_calc = ExpectancyCalculator().compute_metrics(is_returns)
        oos_calc = ExpectancyCalculator().compute_metrics(oos_returns)

        is_sharpe = is_calc.sortino_ratio
        oos_sharpe = oos_calc.sortino_ratio

        wf_efficiency = (oos_sharpe / (is_sharpe + 1e-8)) if is_sharpe > 0 else 0.0
        passed = wf_efficiency >= 0.60

        return {
            "wf_efficiency_ratio": round(float(wf_efficiency), 4),
            "is_expectancy": is_calc.expectancy_per_trade,
            "oos_expectancy": oos_calc.expectancy_per_trade,
            "passed": passed
        }
