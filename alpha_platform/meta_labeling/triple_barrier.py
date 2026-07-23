import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from alpha_platform.core.types import Bar, SignalType

class TripleBarrierLabeler:
    """
    Marcos Lopez de Prado's Triple Barrier Method.
    Labels candidate trade opportunities based on touch of:
    1. Profit Target Barrier (Label 1 = Win)
    2. Stop Loss Barrier (Label 0 = Loss)
    3. Vertical Holding Time Limit Barrier (Label 0 or PnL sign)
    """

    def label_candidate(
        self,
        entry_idx: int,
        bars: List[Bar],
        signal_type: SignalType,
        pt_multiplier: float = 2.0,
        sl_multiplier: float = 1.0,
        holding_bars: int = 20
    ) -> Tuple[int, float]:
        if entry_idx >= len(bars) - 1:
            return 0, 0.0

        entry_bar = bars[entry_idx]
        entry_price = entry_bar.close
        
        # Calculate volatility dynamically (ATR)
        lookback = bars[max(0, entry_idx - 14):entry_idx]
        if len(lookback) > 0:
            volatility = np.mean([b.high - b.low for b in lookback])
        else:
            volatility = entry_price * 0.005

        pt_price = entry_price + (pt_multiplier * volatility) if signal_type == SignalType.BUY else entry_price - (pt_multiplier * volatility)
        sl_price = entry_price - (sl_multiplier * volatility) if signal_type == SignalType.BUY else entry_price + (sl_multiplier * volatility)

        max_idx = min(len(bars), entry_idx + holding_bars + 1)
        future_bars = bars[entry_idx + 1:max_idx]

        for b in future_bars:
            if signal_type == SignalType.BUY:
                if b.high >= pt_price:
                    return 1, (pt_price - entry_price) / entry_price
                if b.low <= sl_price:
                    return 0, (sl_price - entry_price) / entry_price
            else:  # SELL
                if b.low <= pt_price:
                    return 1, (entry_price - pt_price) / entry_price
                if b.high >= sl_price:
                    return 0, (entry_price - sl_price) / entry_price

        # Vertical barrier hit (Holding period expired)
        final_price = future_bars[-1].close if future_bars else entry_price
        ret = (final_price - entry_price) / entry_price if signal_type == SignalType.BUY else (entry_price - final_price) / entry_price
        label = 1 if ret > 0 else 0
        return label, float(ret)
