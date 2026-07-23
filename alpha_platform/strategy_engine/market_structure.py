import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from alpha_platform.core.types import Bar, SignalType, MarketSession

@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    timestamp: datetime

@dataclass
class FairValueGap:
    index: int
    is_bullish: bool
    top_price: float
    bottom_price: float
    timestamp: datetime

@dataclass
class OrderBlock:
    index: int
    is_bullish: bool
    top_price: float
    bottom_price: float
    timestamp: datetime

@dataclass
class MarketStructureSnapshot:
    trend_bias: SignalType
    has_bos: bool
    has_choch: bool
    has_liquidity_sweep: bool
    active_fvgs: List[FairValueGap] = field(default_factory=list)
    active_order_blocks: List[OrderBlock] = field(default_factory=list)
    volatility_regime: str = "NORMAL"  # LOW, NORMAL, HIGH, EXPANSION
    atr_adaptive: float = 0.0
    current_session: MarketSession = MarketSession.LONDON
    trend_strength: float = 0.0

class InstitutionalMarketStructureAnalyzer:
    """
    Production-grade Smart Money Concepts (SMC) & Institutional Market Structure Analyzer.
    Detects Swing High/Low, Break of Structure (BOS), Change of Character (CHoCH),
    Fair Value Gaps (FVG), Order Blocks, Liquidity Sweeps, and Session/Volatility Regimes.
    """

    def __init__(self, swing_window: int = 3):
        self.swing_window = swing_window

    def detect_swings(self, bars: List[Bar]) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        n = len(bars)

        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []

        w = self.swing_window
        for i in range(w, n - w):
            # Swing High: highest in window left and right
            if all(highs[i] >= highs[i - k] for k in range(1, w + 1)) and all(highs[i] > highs[i + k] for k in range(1, w + 1)):
                swing_highs.append(SwingPoint(index=i, price=highs[i], is_high=True, timestamp=bars[i].timestamp))

            # Swing Low: lowest in window left and right
            if all(lows[i] <= lows[i - k] for k in range(1, w + 1)) and all(lows[i] < lows[i + k] for k in range(1, w + 1)):
                swing_lows.append(SwingPoint(index=i, price=lows[i], is_low=False, timestamp=bars[i].timestamp))

        return swing_highs, swing_lows

    def detect_fair_value_gaps(self, bars: List[Bar]) -> List[FairValueGap]:
        fvgs: List[FairValueGap] = []
        if len(bars) < 3:
            return fvgs

        for i in range(2, len(bars)):
            b1 = bars[i - 2]
            b3 = bars[i]

            # Bullish FVG: Bar 1 High < Bar 3 Low
            if b1.high < b3.low:
                fvgs.append(FairValueGap(
                    index=i,
                    is_bullish=True,
                    top_price=b3.low,
                    bottom_price=b1.high,
                    timestamp=b3.timestamp
                ))

            # Bearish FVG: Bar 1 Low > Bar 3 High
            elif b1.low > b3.high:
                fvgs.append(FairValueGap(
                    index=i,
                    is_bullish=False,
                    top_price=b1.low,
                    bottom_price=b3.high,
                    timestamp=b3.timestamp
                ))

        return fvgs

    def detect_order_blocks(self, bars: List[Bar], fvgs: List[FairValueGap]) -> List[OrderBlock]:
        order_blocks: List[OrderBlock] = []
        if len(bars) < 5 or not fvgs:
            return order_blocks

        for fvg in fvgs:
            idx = fvg.index
            if idx >= 2 and idx < len(bars):
                # Bullish OB: Last bearish candle before a bullish FVG impulse
                if fvg.is_bullish:
                    ob_bar = bars[idx - 2]
                    order_blocks.append(OrderBlock(
                        index=idx - 2,
                        is_bullish=True,
                        top_price=ob_bar.high,
                        bottom_price=ob_bar.low,
                        timestamp=ob_bar.timestamp
                    ))
                # Bearish OB: Last bullish candle before a bearish FVG impulse
                else:
                    ob_bar = bars[idx - 2]
                    order_blocks.append(OrderBlock(
                        index=idx - 2,
                        is_bullish=False,
                        top_price=ob_bar.high,
                        bottom_price=ob_bar.low,
                        timestamp=ob_bar.timestamp
                    ))

        return order_blocks

    def detect_liquidity_sweep(self, bars: List[Bar], swing_highs: List[SwingPoint], swing_lows: List[SwingPoint]) -> bool:
        if not bars or (not swing_highs and not swing_lows):
            return False

        last_bar = bars[-1]
        
        # Bullish Liquidity Sweep (spikes below recent swing low and closes above it)
        if swing_lows:
            recent_low = swing_lows[-1].price
            if last_bar.low < recent_low and last_bar.close > recent_low:
                return True

        # Bearish Liquidity Sweep (spikes above recent swing high and closes below it)
        if swing_highs:
            recent_high = swing_highs[-1].price
            if last_bar.high > recent_high and last_bar.close < recent_high:
                return True

        return False

    def classify_volatility_regime(self, bars: List[Bar]) -> Tuple[str, float]:
        if len(bars) < 20:
            return "NORMAL", 1.0

        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        closes = np.array([b.close for b in bars])

        tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
        atr_14 = float(np.mean(tr[-14:]))
        atr_50 = float(np.mean(tr[-50:])) if len(tr) >= 50 else atr_14

        vol_ratio = atr_14 / (atr_50 + 1e-8)

        if vol_ratio > 1.5:
            regime = "EXPANSION"
        elif vol_ratio > 1.1:
            regime = "HIGH"
        elif vol_ratio < 0.7:
            regime = "LOW"
        else:
            regime = "NORMAL"

        return regime, atr_14

    def identify_market_session(self, timestamp: datetime) -> MarketSession:
        hour = timestamp.hour
        if 0 <= hour < 7:
            return MarketSession.ASIAN
        elif 7 <= hour < 12:
            return MarketSession.LONDON
        elif 12 <= hour < 16:
            return MarketSession.OVERLAP
        else:
            return MarketSession.NEW_YORK

    def analyze_structure(self, bars: List[Bar]) -> MarketStructureSnapshot:
        if len(bars) < 20:
            return MarketStructureSnapshot(
                trend_bias=SignalType.FLAT,
                has_bos=False,
                has_choch=False,
                has_liquidity_sweep=False
            )

        swing_highs, swing_lows = self.detect_swings(bars)
        fvgs = self.detect_fair_value_gaps(bars)
        order_blocks = self.detect_order_blocks(bars, fvgs)
        has_sweep = self.detect_liquidity_sweep(bars, swing_highs, swing_lows)
        vol_regime, atr = self.classify_volatility_regime(bars)
        session = self.identify_market_session(bars[-1].timestamp)

        # Structure Direction
        last_close = bars[-1].close
        has_bos = False
        has_choch = False
        trend_bias = SignalType.FLAT
        trend_strength = 0.0

        if swing_highs and swing_lows:
            recent_sh = swing_highs[-1].price
            recent_sl = swing_lows[-1].price

            # Bullish Break of Structure (BOS)
            if last_close > recent_sh:
                has_bos = True
                trend_bias = SignalType.BUY
                trend_strength = float((last_close - recent_sh) / (atr + 1e-8))

            # Bearish Break of Structure (BOS)
            elif last_close < recent_sl:
                has_bos = True
                trend_bias = SignalType.SELL
                trend_strength = float((recent_sl - last_close) / (atr + 1e-8))

            # Change of Character (CHoCH) detection
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                prev_sh = swing_highs[-2].price
                prev_sl = swing_lows[-2].price
                if recent_sh > prev_sh and last_close < recent_sl:
                    has_choch = True
                    trend_bias = SignalType.SELL
                elif recent_sl < prev_sl and last_close > recent_sh:
                    has_choch = True
                    trend_bias = SignalType.BUY

        return MarketStructureSnapshot(
            trend_bias=trend_bias,
            has_bos=has_bos,
            has_choch=has_choch,
            has_liquidity_sweep=has_sweep,
            active_fvgs=fvgs[-5:],
            active_order_blocks=order_blocks[-5:],
            volatility_regime=vol_regime,
            atr_adaptive=atr,
            current_session=session,
            trend_strength=trend_strength
        )
