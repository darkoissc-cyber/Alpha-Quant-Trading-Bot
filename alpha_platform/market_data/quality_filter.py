import numpy as np
from typing import List, Optional
from datetime import datetime
from alpha_platform.core.types import Tick, Bar
from alpha_platform.config.logging_config import logger

class DataQualityFilter:
    def __init__(self, max_spread_multiplier: float = 5.0, outlier_std_threshold: float = 4.0):
        self.max_spread_multiplier = max_spread_multiplier
        self.outlier_std_threshold = outlier_std_threshold
        self.last_tick: Optional[Tick] = None
        self.historical_spreads: List[float] = []

    def clean_tick(self, raw_tick: Tick) -> Optional[Tick]:
        # 1. Timestamp Normalization
        if not isinstance(raw_tick.timestamp, datetime):
            logger.warning(f"Rejecting tick with invalid timestamp type: {raw_tick.timestamp}")
            return None

        # 2. Bad Price & Non-Positive Verification
        if raw_tick.bid <= 0 or raw_tick.ask <= 0 or raw_tick.ask < raw_tick.bid:
            logger.warning(f"Rejecting bad price tick for {raw_tick.symbol}: Bid={raw_tick.bid}, Ask={raw_tick.ask}")
            return None

        # 3. Duplicate Tick Removal
        if self.last_tick and raw_tick.symbol == self.last_tick.symbol:
            if raw_tick.timestamp == self.last_tick.timestamp and raw_tick.bid == self.last_tick.bid and raw_tick.ask == self.last_tick.ask:
                # Duplicate tick silently ignored
                return None

        # 4. Spread Anomaly Detection
        spread = raw_tick.spread
        if self.historical_spreads:
            median_spread = float(np.median(self.historical_spreads[-100:]))
            if median_spread > 0 and spread > median_spread * self.max_spread_multiplier:
                logger.warning(f"Spread anomaly detected on {raw_tick.symbol}: Spread={spread}, Median={median_spread}")
                return None

        self.historical_spreads.append(spread)
        if len(self.historical_spreads) > 1000:
            self.historical_spreads.pop(0)

        self.last_tick = raw_tick
        return raw_tick

    def clean_bars(self, bars: List[Bar]) -> List[Bar]:
        cleaned = []
        for bar in bars:
            if bar.high < bar.low or bar.open <= 0 or bar.close <= 0:
                logger.warning(f"Rejecting invalid bar: {bar}")
                continue
            cleaned.append(bar)
        return cleaned
