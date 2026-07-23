from typing import Dict, Any, List
import numpy as np
from alpha_platform.config.logging_config import logger

class PaperTradingValidationRunner:
    """
    Mandatory paper trading sandbox module.
    Measures backtest vs live performance divergence, slippage impact, and model accuracy.
    """

    def __init__(self, min_paper_days: int = 14):
        self.min_paper_days = min_paper_days
        self.paper_trades: List[Dict[str, Any]] = []

    def log_paper_trade(
        self,
        strategy_id: str,
        backtest_expected_return: float,
        paper_actual_return: float,
        slippage_pips: float
    ):
        self.paper_trades.append({
            "strategy_id": strategy_id,
            "expected_ret": backtest_expected_return,
            "actual_ret": paper_actual_return,
            "slippage": slippage_pips
        })

    def evaluate_paper_validation(self, strategy_id: str) -> Dict[str, Any]:
        trades = [t for t in self.paper_trades if t["strategy_id"] == strategy_id]
        if len(trades) < 10:
            return {"ready_for_live": False, "reason": "Insufficient paper trades (<10)"}

        exp_rets = np.array([t["expected_ret"] for t in trades])
        act_rets = np.array([t["actual_ret"] for t in trades])

        divergence = float(np.mean(np.abs(exp_rets - act_rets)))
        avg_slippage = float(np.mean([t["slippage"] for t in trades]))

        ready = divergence < 0.02 and avg_slippage < 2.5
        
        return {
            "ready_for_live": ready,
            "divergence": divergence,
            "avg_slippage": avg_slippage,
            "paper_trade_count": len(trades)
        }
