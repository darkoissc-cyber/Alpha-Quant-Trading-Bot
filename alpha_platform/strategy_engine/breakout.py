import uuid
import numpy as np
from typing import List, Optional
from alpha_platform.core.base_strategy import BaseStrategy
from alpha_platform.core.types import Bar, Tick, TradeCandidate, SignalType
from alpha_platform.alpha_research.hypothesis import AlphaHypothesis

class BreakoutStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "STRAT_BREAKOUT_01"):
        hypothesis = AlphaHypothesis(
            strategy_name="Volatility Compression Breakout",
            market_hypothesis="Extended volatility compression periods lead to explosive directional liquidity expansion.",
            economic_reason="Pending limit order clusters above/below ranges get triggered simultaneously, driving rapid order book imbalance.",
            expected_conditions="High compression following a consolidation period across session openings.",
            failure_conditions="False breakouts caused by liquidity sweeps before reversal.",
            expected_holding_period_bars=12,
            expected_risk_reward_ratio=2.5,
            target_instruments=["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
        )
        super().__init__(strategy_id, hypothesis)

    def generate_candidates(self, symbol: str, bars: List[Bar], current_tick: Optional[Tick] = None) -> List[TradeCandidate]:
        if len(bars) < 30:
            return []

        recent_bars = bars[-20:]
        highs = np.array([b.high for b in recent_bars[:-1]])
        lows = np.array([b.low for b in recent_bars[:-1]])
        
        range_high = np.max(highs)
        range_low = np.min(lows)
        channel_width = range_high - range_low

        current_bar = bars[-1]
        candidates = []

        # Bullish Breakout
        if current_bar.close > range_high:
            sl = range_high - (0.5 * channel_width)
            tp = current_bar.close + (1.5 * channel_width)
            candidates.append(TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=current_bar.timestamp,
                signal_type=SignalType.BUY,
                entry_price=current_bar.close,
                stop_loss=sl,
                take_profit=tp,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((current_bar.close - range_high) / (channel_width + 1e-8)),
                features_snapshot={"range_high": float(range_high), "range_low": float(range_low)}
            ))
        # Bearish Breakout
        elif current_bar.close < range_low:
            sl = range_low + (0.5 * channel_width)
            tp = current_bar.close - (1.5 * channel_width)
            candidates.append(TradeCandidate(
                candidate_id=str(uuid.uuid4()),
                strategy_id=self.strategy_id,
                symbol=symbol,
                timestamp=current_bar.timestamp,
                signal_type=SignalType.SELL,
                entry_price=current_bar.close,
                stop_loss=sl,
                take_profit=tp,
                holding_period_bars=self.hypothesis.expected_holding_period_bars,
                confidence_score=float((range_low - current_bar.close) / (channel_width + 1e-8)),
                features_snapshot={"range_high": float(range_high), "range_low": float(range_low)}
            ))

        return candidates
