from datetime import datetime
from typing import Dict, List, Optional
from alpha_platform.core.types import Bar, Tick
from alpha_platform.market_data.microstructure import MicrostructureAnalyzer
from alpha_platform.feature_store.market_features import MarketFeatureExtractor
from alpha_platform.feature_store.cross_asset import CrossAssetFeatureExtractor
from alpha_platform.feature_store.session_features import SessionFeatureExtractor

class CentralFeatureStore:
    VERSION: str = "v1.2.0"

    def __init__(self):
        self.market_extractor = MarketFeatureExtractor()
        self.cross_asset_extractor = CrossAssetFeatureExtractor()
        self.session_extractor = SessionFeatureExtractor()
        self.microstructure_analyzer = MicrostructureAnalyzer()

    def get_features(
        self,
        symbol: str,
        bars: List[Bar],
        ticks: Optional[List[Tick]] = None,
        as_of_time: Optional[datetime] = None
    ) -> Dict[str, float]:
        """
        Point-in-time feature computation interface.
        Crucial requirement: Training features and live execution features 
        MUST use identical logic derived from this method.
        """
        if not bars:
            return {}

        current_time = as_of_time or bars[-1].timestamp

        # 1. Market Technical Features
        features = self.market_extractor.extract_features(bars)

        # 2. Cross-Asset & Macro Features
        cross_features = self.cross_asset_extractor.extract_features(symbol)
        features.update(cross_features)

        # 3. Session Encodings
        session_features = self.session_extractor.extract_features(current_time)
        features.update(session_features)

        # 4. Microstructure Features (if tick data available)
        if ticks:
            micro_features = self.microstructure_analyzer.calculate_microstructure_features(ticks, bars)
            features.update(micro_features)

        # Attach Metadata tag
        features["feature_store_version"] = 1.2

        return features
