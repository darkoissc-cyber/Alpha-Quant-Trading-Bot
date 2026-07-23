from typing import Dict, Any, List
from alpha_platform.core.types import StrategyStage
from alpha_platform.config.logging_config import logger

class StrategyLifecycleManager:
    """
    Automates strategy lifecycle management:
    Research -> Backtest -> Validation -> Paper -> Small Live -> Production -> Retired
    Automatically pauses or retires strategies exhibiting performance decay or model drift.
    """

    def __init__(self):
        self.strategy_states: Dict[str, StrategyStage] = {}

    def set_stage(self, strategy_id: str, stage: StrategyStage):
        self.strategy_states[strategy_id] = stage
        logger.info(f"Strategy '{strategy_id}' lifecycle stage updated to '{stage}'")

    def check_decay_and_autopause(
        self,
        strategy_id: str,
        rolling_sharpe: float,
        recent_drawdown_pct: float,
        model_accuracy: float
    ) -> bool:
        current_stage = self.strategy_states.get(strategy_id, StrategyStage.RESEARCH)
        
        # If rolling Sharpe drops below 0.0 or drawdown exceeds 5%, pause strategy
        if rolling_sharpe < 0.0 or recent_drawdown_pct > 5.0 or model_accuracy < 0.45:
            logger.warning(
                f"STRATEGY DECAY DETECTED for '{strategy_id}': "
                f"Rolling Sharpe={rolling_sharpe:.2f}, DD={recent_drawdown_pct:.2f}%, Accuracy={model_accuracy:.2f}. "
                f"AUTOMATICALLY PAUSING STRATEGY."
            )
            self.set_stage(strategy_id, StrategyStage.RETIRED)
            return True

        return False
