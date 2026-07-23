import numpy as np
from typing import Dict, List, Any
from alpha_platform.config.logging_config import logger

class ExecutionQualityTracker:
    def __init__(self, max_slippage_tolerance_pips: float = 3.0):
        self.max_slippage_tolerance = max_slippage_tolerance_pips
        self.execution_records: List[Dict[str, Any]] = []

    def record_execution(
        self,
        strategy_id: str,
        symbol: str,
        expected_price: float,
        actual_fill_price: float,
        spread_at_fill: float,
        latency_ms: float
    ) -> Dict[str, Any]:
        slippage_pips = abs(actual_fill_price - expected_price)
        record = {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "expected_price": expected_price,
            "actual_fill": actual_fill_price,
            "slippage_pips": slippage_pips,
            "spread_cost": spread_at_fill,
            "latency_ms": latency_ms
        }
        self.execution_records.append(record)

        if slippage_pips > self.max_slippage_tolerance:
            logger.warning(
                f"High slippage warning for '{strategy_id}' on {symbol}: "
                f"Expected {expected_price}, Filled {actual_fill_price} (Slippage: {slippage_pips:.2f} pips)"
            )

        return record

    def get_strategy_execution_score(self, strategy_id: str) -> float:
        strat_records = [r for r in self.execution_records if r["strategy_id"] == strategy_id]
        if not strat_records:
            return 1.0  # Perfect score default

        avg_slippage = float(np.mean([r["slippage_pips"] for r in strat_records]))
        avg_latency = float(np.mean([r["latency_ms"] for r in strat_records]))

        # Quality Score ranges from 0.0 to 1.0
        slippage_penalty = max(0.0, 1.0 - (avg_slippage / self.max_slippage_tolerance))
        latency_penalty = max(0.0, 1.0 - (avg_latency / 500.0))

        score = 0.7 * slippage_penalty + 0.3 * latency_penalty
        return float(score)
