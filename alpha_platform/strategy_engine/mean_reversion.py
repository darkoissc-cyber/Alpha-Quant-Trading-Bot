import uuid
import numpy as np
from typing import List, Optional
from alpha_platform.core.base_strategy import BaseStrategy
from alpha_platform.core.types import Bar, Tick, TradeCandidate, SignalType
from alpha_platform.alpha_research.hypothesis import AlphaHypothesis

class MeanReversionStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "STRAT_MEAN_REV_01"):
        hypothesis = AlphaHypothesis(
            strategy_name="Statistical Bollinger Deviation Reversion",
            market_hypothesis="Asset prices temporarily overextend away from mean value due to liquidity imbalances and retail overreaction.",
            economic_reason="Market makers and institutional mean-reversion algorithms absorb extreme order imbalances, forcing price back to equilibrium.",
            expected_conditions="Ranging, low-to-medium volatility regimes without major news announcements.",
            failure_conditions="Strong trending regimes driven by fundamental structural shifts.",
            expected_holding_period_bars=8,
            expected_risk_reward_ratio=1.8,
            target_instruments=["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
        )
        super().__init__(strategy_id, hypothesis)

    def generate_candidates(self, symbol: str, bars: List[Bar], current_tick: Optional[Tick] = None) -> List[TradeCandidate]:
        if len(bars) < 30:
            return []

        closes = np.array([b.close for b in bars[-20:]])
        mean = np.mean(closes)
        std = np.std(closes)
        if std == 0:
            return []

        upper_band = mean + (2.0 * std)
        lower_band = mean - (2.0 * std)
        current_close = closes[-1]

        candidates = []
        # Oversold - Buy Candidate
        if current_close < lower_band:
            candidates.append(TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=bars[-1].timestamp,
                signal_type=SignalType.BUY,
                entry_price=current_close,
                stop_loss=current_close - (1.0 * std),
                take_profit=mean,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((lower_band - current_close) / std),
                features_snapshot={"mean": float(mean), "std": float(std), "z_score": float((current_close - mean) / std)}
            ))
        # Overbought - Sell Candidate
        elif current_close > upper_band:
            candidates.append(TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=bars[-1].timestamp,
                signal_type=SignalType.SELL,
                entry_price=current_close,
                stop_loss=current_close + (1.0 * std),
                take_profit=mean,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((current_close - upper_band) / std),
                features_snapshot={"mean": float(mean), "std": float(std), "z_score": float((current_close - mean) / std)}
            ))

        return candidates
