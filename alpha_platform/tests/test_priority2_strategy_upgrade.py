import unittest
from datetime import datetime, timedelta
from alpha_platform.core.types import Bar, SignalType
from alpha_platform.strategy_engine.market_structure import InstitutionalMarketStructureAnalyzer
from alpha_platform.strategy_engine.trend_following import TrendFollowingStrategy

class TestPriority2StrategyUpgrade(unittest.TestCase):
    def setUp(self):
        self.analyzer = InstitutionalMarketStructureAnalyzer(swing_window=3)
        self.strategy = TrendFollowingStrategy()

    def generate_synthetic_bars(self, count: int = 60, trend: str = "bullish") -> list:
        bars = []
        base_price = 100.0
        now = datetime.utcnow()
        for i in range(count):
            if trend == "bullish":
                base_price += 0.5 + (i % 3) * 0.1
            else:
                base_price -= 0.5 + (i % 3) * 0.1
            
            bar = Bar(
                symbol="XAUUSD",
                timestamp=now + timedelta(minutes=5 * i),
                open=base_price - 0.2,
                high=base_price + 0.4,
                low=base_price - 0.4,
                close=base_price + 0.2,
                volume=1000.0
            )
            bars.append(bar)
        return bars

    def test_market_structure_analysis(self):
        bars = self.generate_synthetic_bars(60, "bullish")
        snapshot = self.analyzer.analyze_structure(bars)
        self.assertIsNotNone(snapshot)
        self.assertIn(snapshot.volatility_regime, ["LOW", "NORMAL", "HIGH", "EXPANSION"])
        self.assertGreater(snapshot.atr_adaptive, 0.0)

    def test_trend_following_candidates_generation(self):
        bars = self.generate_synthetic_bars(60, "bullish")
        candidates = self.strategy.generate_candidates("XAUUSD", bars)
        self.assertIsInstance(candidates, list)
        if candidates:
            cand = candidates[0]
            self.assertEqual(cand.signal_type, SignalType.BUY)
            self.assertGreater(cand.take_profit, cand.entry_price)
            self.assertLess(cand.stop_loss, cand.entry_price)

if __name__ == "__main__":
    unittest.main()
