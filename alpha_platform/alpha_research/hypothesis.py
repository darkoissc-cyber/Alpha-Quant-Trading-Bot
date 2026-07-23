from dataclasses import dataclass

@dataclass
class AlphaHypothesis:
    strategy_name: str
    market_hypothesis: str
    economic_reason: str
    expected_conditions: str
    failure_conditions: str
    expected_holding_period_bars: int
    expected_risk_reward_ratio: float
    target_instruments: list

    def validate(self) -> bool:
        if not self.market_hypothesis or len(self.market_hypothesis.strip()) < 20:
            raise ValueError(f"Strategy '{self.strategy_name}' requires a detailed Market Hypothesis.")
        if not self.economic_reason or len(self.economic_reason.strip()) < 20:
            raise ValueError(f"Strategy '{self.strategy_name}' requires a clear Economic Reason.")
        if not self.expected_conditions or not self.failure_conditions:
            raise ValueError(f"Strategy '{self.strategy_name}' must explicitly state expected & failure conditions.")
        if self.expected_risk_reward_ratio <= 0.0:
            raise ValueError(f"Expected Risk/Reward ratio must be > 0.0.")
        return True
