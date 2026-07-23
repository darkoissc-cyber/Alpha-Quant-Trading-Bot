from typing import Dict, Optional

class CrossAssetFeatureExtractor:
    def __init__(self):
        # Cache recent macro proxy values
        self.dxy_index: float = 104.5
        self.us10y_yield: float = 4.25
        self.risk_sentiment_vix: float = 15.0
        self.btc_funding_rate: float = 0.0001
        self.btc_open_interest: float = 15000000000.0

    def update_macro_proxies(self, dxy: float, yield_10y: float, vix: float, btc_funding: float = 0.0001, btc_oi: float = 15e9):
        self.dxy_index = dxy
        self.us10y_yield = yield_10y
        self.risk_sentiment_vix = vix
        self.btc_funding_rate = btc_funding
        self.btc_open_interest = btc_oi

    def extract_features(self, symbol: str) -> Dict[str, float]:
        base_features = {
            "macro_dxy": float(self.dxy_index),
            "macro_us10y": float(self.us10y_yield),
            "macro_vix": float(self.risk_sentiment_vix)
        }

        if symbol == "XAUUSD":
            # Gold cross-asset sensitivities
            base_features.update({
                "gold_dxy_beta": float(-0.85 * (self.dxy_index / 100.0)),
                "gold_real_yield_proxy": float(self.us10y_yield - 2.5),
                "gold_safe_haven_score": float(self.risk_sentiment_vix / 20.0)
            })
        elif symbol == "BTCUSD":
            # Crypto cross-asset metrics
            base_features.update({
                "btc_funding_rate": float(self.btc_funding_rate),
                "btc_open_interest_norm": float(self.btc_open_interest / 1e10),
                "btc_risk_on_ratio": float(100.0 / (self.risk_sentiment_vix + 1e-5))
            })

        return base_features
