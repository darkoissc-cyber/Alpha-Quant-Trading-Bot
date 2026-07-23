import numpy as np
from typing import List, Dict
from alpha_platform.core.types import Tick, Bar

class MicrostructureAnalyzer:
    def __init__(self, window_size: int = 50):
        self.window_size = window_size

    def calculate_tick_imbalance(self, ticks: List[Tick]) -> float:
        if len(ticks) < 2:
            return 0.0
        
        buy_volume = 0.0
        sell_volume = 0.0
        
        for i in range(1, len(ticks)):
            prev_mid = ticks[i-1].mid
            curr_mid = ticks[i].mid
            vol = ticks[i].volume if ticks[i].volume > 0 else 1.0
            
            if curr_mid > prev_mid:
                buy_volume += vol
            elif curr_mid < prev_mid:
                sell_volume += vol
                
        total_volume = buy_volume + sell_volume
        if total_volume == 0:
            return 0.0
            
        return (buy_volume - sell_volume) / total_volume

    def calculate_tick_velocity(self, ticks: List[Tick]) -> float:
        if len(ticks) < 2:
            return 0.0
        dt = (ticks[-1].timestamp - ticks[0].timestamp).total_seconds()
        if dt <= 0:
            return 0.0
        return len(ticks) / dt

    def calculate_microstructure_features(self, ticks: List[Tick], bars: List[Bar]) -> Dict[str, float]:
        if not ticks or not bars:
            return {
                "tick_imbalance": 0.0,
                "tick_velocity": 0.0,
                "spread_ratio": 1.0,
                "volatility_expansion": 1.0,
                "price_impact_estimate": 0.0
            }
            
        recent_ticks = ticks[-self.window_size:]
        recent_bars = bars[-20:]
        
        # 1. Tick Imbalance & Velocity
        tick_imb = self.calculate_tick_imbalance(recent_ticks)
        tick_vel = self.calculate_tick_velocity(recent_ticks)
        
        # 2. Spread Behavior Ratio
        current_spread = recent_ticks[-1].spread
        hist_spreads = [t.spread for t in recent_ticks]
        avg_spread = np.mean(hist_spreads) if hist_spreads else current_spread
        spread_ratio = current_spread / avg_spread if avg_spread > 0 else 1.0
        
        # 3. Volatility Expansion Ratio
        closes = np.array([b.close for b in recent_bars])
        if len(closes) >= 5:
            returns = np.diff(np.log(closes))
            recent_std = np.std(returns[-5:]) if len(returns) >= 5 else 0.001
            baseline_std = np.std(returns) if len(returns) > 1 else 0.001
            vol_expansion = recent_std / (baseline_std + 1e-8)
        else:
            vol_expansion = 1.0
            
        # 4. Price Impact Estimate
        price_change = abs(recent_ticks[-1].mid - recent_ticks[0].mid)
        total_vol = sum(t.volume if t.volume > 0 else 1.0 for t in recent_ticks)
        price_impact = price_change / (total_vol + 1e-5)
        
        return {
            "tick_imbalance": float(tick_imb),
            "tick_velocity": float(tick_vel),
            "spread_ratio": float(spread_ratio),
            "volatility_expansion": float(vol_expansion),
            "price_impact_estimate": float(price_impact)
        }
