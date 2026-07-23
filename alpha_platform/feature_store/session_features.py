from datetime import datetime
from typing import Dict
from alpha_platform.core.types import MarketSession

class SessionFeatureExtractor:
    @staticmethod
    def get_current_session(dt: datetime) -> MarketSession:
        hour = dt.utctimetuple().tm_hour
        # Asian Session: 00:00 - 08:00 UTC
        # London Session: 08:00 - 16:00 UTC
        # NY Session: 13:00 - 21:00 UTC
        # Overlap (London + NY): 13:00 - 16:00 UTC
        if 13 <= hour < 16:
            return MarketSession.OVERLAP
        elif 8 <= hour < 16:
            return MarketSession.LONDON
        elif 13 <= hour < 21:
            return MarketSession.NEW_YORK
        else:
            return MarketSession.ASIAN

    def extract_features(self, dt: datetime) -> Dict[str, float]:
        session = self.get_current_session(dt)
        return {
            "is_asian_session": 1.0 if session == MarketSession.ASIAN else 0.0,
            "is_london_session": 1.0 if session in (MarketSession.LONDON, MarketSession.OVERLAP) else 0.0,
            "is_ny_session": 1.0 if session in (MarketSession.NEW_YORK, MarketSession.OVERLAP) else 0.0,
            "is_session_overlap": 1.0 if session == MarketSession.OVERLAP else 0.0,
            "hour_sin": float(np.sin(2 * np.pi * dt.hour / 24.0)),
            "hour_cos": float(np.cos(2 * np.pi * dt.hour / 24.0))
        }

import numpy as np
