import uuid
import numpy as np
from typing import List, Optional
from datetime import datetime

from alpha_platform.core.base_strategy import BaseStrategy
from alpha_platform.core.types import Bar, Tick, TradeCandidate, SignalType
from alpha_platform.alpha_research.hypothesis import AlphaHypothesis
from alpha_platform.strategy_engine.market_structure import InstitutionalMarketStructureAnalyzer

class TrendFollowingStrategy(BaseStrategy):
    """
    Upgraded Institutional Trend Following Strategy.
    Combines moving average momentum with Smart Money Concepts (BOS, CHoCH, Liquidity Sweeps, FVGs)
    and Adaptive ATR Risk Buffers.
    """
    def __init__(self, strategy_id: str = "STRAT_TREND_01"):
        hypothesis = AlphaHypothesis(
            strategy_name="Multi-Timeframe Trend & Structure Following",
            market_hypothesis="Asset prices exhibit persistent directional momentum due to delayed news adoption and institutional order execution.",
            economic_reason="Institutional portfolio rebalancing and algorithmic trend execution create sustained buying/selling pressure over multiple sessions.",
            expected_conditions="Trending markets with high directional momentum and moderate volatility expansion.",
            failure_conditions="Tight range-bound consolidation or macro announcement whipsaws.",
            expected_holding_period_bars=24,
            expected_risk_reward_ratio=2.0,
            target_instruments=["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
        )
        super().__init__(strategy_id, hypothesis)
        self.ms_analyzer = InstitutionalMarketStructureAnalyzer(swing_window=3)

    def generate_candidates(self, symbol: str, bars: List[Bar], current_tick: Optional[Tick] = None) -> List[TradeCandidate]:
        if len(bars) < 50:
            return []

        closes = np.array([b.close for b in bars])
        fast_ma = np.mean(closes[-10:])
        slow_ma = np.mean(closes[-30:])

        # Market Structure Analysis
        struct = self.ms_analyzer.analyze_structure(bars)
        atr = struct.atr_adaptive if struct.atr_adaptive > 0 else (np.mean(np.abs(np.diff(closes[-14:]))) + 0.001)

        # Dynamic ATR Multipliers based on Volatility Regime
        if struct.volatility_regime == "EXPANSION":
            atr_sl_mult, atr_tp_mult = 2.0, 4.0
        elif struct.volatility_regime == "HIGH":
            atr_sl_mult, atr_tp_mult = 1.8, 3.6
        else:
            atr_sl_mult, atr_tp_mult = 1.5, 3.0

        current_close = closes[-1]
        candidates = []

        # Bullish Trend Signal with Market Structure Confirmation (BOS / CHoCH or Liquidity Sweep)
        bullish_ma = fast_ma > slow_ma and current_close > fast_ma
        bullish_structure = struct.trend_bias == SignalType.BUY or struct.has_bos or struct.has_liquidity_sweep

        if bullish_ma and bullish_structure:
            sl = current_close - (atr_sl_mult * atr)
            tp = current_close + (atr_tp_mult * atr)
            confidence = float((fast_ma - slow_ma) / (atr + 1e-8)) + (0.2 if struct.has_bos else 0.0) + (0.3 if struct.has_liquidity_sweep else 0.0)
            
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
                confidence_score=float(confidence),
                features_snapshot={
                    "fast_ma": float(fast_ma),
                    "slow_ma": float(slow_ma),
                    "atr": float(atr),
                    "has_bos": 1.0 if struct.has_bos else 0.0,
                    "has_choch": 1.0 if struct.has_choch else 0.0,
                    "volatility_regime": 1.0 if struct.volatility_regime == "EXPANSION" else 0.0
                }
            )
            candidates.append(candidate)

        # Bearish Trend Signal
        bearish_ma = fast_ma < slow_ma and current_close < fast_ma
        bearish_structure = struct.trend_bias == SignalType.SELL or struct.has_bos or struct.has_liquidity_sweep

        if bearish_ma and bearish_structure:
            sl = current_close + (atr_sl_mult * atr)
            tp = current_close - (atr_tp_mult * atr)
            confidence = float((slow_ma - fast_ma) / (atr + 1e-8)) + (0.2 if struct.has_bos else 0.0) + (0.3 if struct.has_liquidity_sweep else 0.0)
            
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
                confidence_score=float(confidence),
                features_snapshot={
                    "fast_ma": float(fast_ma),
                    "slow_ma": float(slow_ma),
                    "atr": float(atr),
                    "has_bos": 1.0 if struct.has_bos else 0.0,
                    "has_choch": 1.0 if struct.has_choch else 0.0,
                    "volatility_regime": 1.0 if struct.volatility_regime == "EXPANSION" else 0.0
                }
            )
            candidates.append(candidate)

        return candidates
