import uuid
import numpy as np
from typing import List, Optional
from datetime import datetime

from alpha_platform.core.base_strategy import BaseStrategy
from alpha_platform.core.types import Bar, Tick, TradeCandidate, SignalType
from alpha_platform.alpha_research.hypothesis import AlphaHypothesis

class TrendFollowingStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "STRAT_TREND_01"):
        hypothesis = AlphaHypothesis(
            strategy_name="Multi-Timeframe Trend Following",
            market_hypothesis="Asset prices exhibit persistent directional momentum due to delayed news adoption and institutional order execution.",
            economic_reason="Institutional portfolio rebalancing and algorithmic trend execution create sustained buying/selling pressure over multiple sessions.",
            expected_conditions="Trending markets with high directional momentum and moderate volatility expansion.",
            failure_conditions="Tight range-bound consolidation or macro announcement whipsaws.",
            expected_holding_period_bars=24,
            expected_risk_reward_ratio=2.0,
            target_instruments=["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
        )
        super().__init__(strategy_id, hypothesis)

    def generate_candidates(self, symbol: str, bars: List[Bar], current_tick: Optional[Tick] = None) -> List[TradeCandidate]:
        if len(bars) < 50:
            return []

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        fast_ma = np.mean(closes[-10:])
        slow_ma = np.mean(closes[-30:])
        atr = np.mean(highs[-14:] - lows[-14:]) if len(highs) >= 14 else 0.001

        current_close = closes[-1]
        candidates = []

        # Bullish Trend Signal
        if fast_ma > slow_ma and current_close > fast_ma:
            sl = current_close - (1.5 * atr)
            tp = current_close + (3.0 * atr)
            candidate = TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=bars[-1].timestamp,
                signal_type=SignalType.BUY,
                entry_price=current_close,
                stop_loss=sl,
                take_profit=tp,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((fast_ma - slow_ma) / (atr + 1e-8)),
                features_snapshot={"fast_ma": float(fast_ma), "slow_ma": float(slow_ma), "atr": float(atr)}
            )
            candidates.append(candidate)

        # Bearish Trend Signal
        elif fast_ma < slow_ma and current_close < fast_ma:
            sl = current_close + (1.5 * atr)
            tp = current_close - (3.0 * atr)
            candidate = TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=bars[-1].timestamp,
                signal_type=SignalType.SELL,
                entry_price=current_close,
                stop_loss=sl,
                take_profit=tp,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((slow_ma - fast_ma) / (atr + 1e-8)),
                features_snapshot={"fast_ma": float(fast_ma), "slow_ma": float(slow_ma), "atr": float(atr)}
            )
            candidates.append(candidate)

        return candidates
