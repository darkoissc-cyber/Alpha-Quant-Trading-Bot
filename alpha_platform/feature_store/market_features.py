import numpy as np
import pandas as pd
from typing import Dict, List
from alpha_platform.core.types import Bar

class MarketFeatureExtractor:
    @staticmethod
    def calculate_momentum_rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) <= period:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def calculate_garman_klass_volatility(highs: np.ndarray, lows: np.ndarray, opens: np.ndarray, closes: np.ndarray) -> float:
        if len(closes) < 2:
            return 0.0
        log_hl = np.log(highs / lows) ** 2
        log_co = np.log(closes / opens) ** 2
        gk_element = 0.5 * log_hl - (2.0 * np.log(2.0) - 1.0) * log_co
        return float(np.sqrt(np.maximum(0.0, np.mean(gk_element))))

    @staticmethod
    def calculate_trend_slope(closes: np.ndarray, period: int = 20) -> float:
        if len(closes) < period:
            return 0.0
        y = closes[-period:]
        x = np.arange(len(y))
        slope, _ = np.polyfit(x, y, 1)
        return float(slope / (closes[-1] + 1e-8))

    def extract_features(self, bars: List[Bar]) -> Dict[str, float]:
        if not bars or len(bars) < 20:
            return {
                "momentum_rsi": 50.0,
                "volatility_gk": 0.0,
                "trend_slope": 0.0,
                "liquidity_vol_ratio": 1.0
            }
            
        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        opens = np.array([b.open for b in bars])
        volumes = np.array([b.volume for b in bars])

        rsi = self.calculate_momentum_rsi(closes)
        gk_vol = self.calculate_garman_klass_volatility(highs, lows, opens, closes)
        slope = self.calculate_trend_slope(closes)
        
        recent_vol = volumes[-1] if len(volumes) > 0 else 1.0
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else 1.0
        vol_ratio = recent_vol / (avg_vol + 1e-5)

        return {
            "momentum_rsi": rsi,
            "volatility_gk": float(gk_vol),
            "trend_slope": float(slope),
            "liquidity_vol_ratio": float(vol_ratio)
        }
