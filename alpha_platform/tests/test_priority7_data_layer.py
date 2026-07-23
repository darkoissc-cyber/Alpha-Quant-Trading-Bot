import unittest
import os
from datetime import datetime, timedelta
from alpha_platform.core.types import Bar, Tick
from alpha_platform.feature_store.time_series_db import (
    TimeSeriesDataStore,
    FeatureCacheEngine,
    HistoricalReplayEngine
)
from alpha_platform.feature_store.store import CentralFeatureStore

class TestPriority7DataLayerUpgrade(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_time_series.db"
        self.data_store = TimeSeriesDataStore(db_path=self.db_path)
        self.cache_engine = FeatureCacheEngine()
        self.feature_store = CentralFeatureStore()

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_candle_storage_and_query(self):
        now = datetime.utcnow()
        bars = [
            Bar(symbol="XAUUSD", timestamp=now - timedelta(minutes=5 * i), open=2000.0, high=2005.0, low=1995.0, close=2002.0, volume=100.0, tick_count=50)
            for i in range(10)
        ]
        self.data_store.insert_candles(bars)
        queried = self.data_store.query_candles("XAUUSD", limit=5)
        self.assertEqual(len(queried), 5)
        self.assertEqual(queried[0].symbol, "XAUUSD")

    def test_feature_cache(self):
        now = datetime.utcnow()
        self.cache_engine.put("XAUUSD", now, {"rsi": 55.0, "atr": 2.5})
        cached = self.cache_engine.get("XAUUSD", now)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["rsi"], 55.0)

    def test_historical_replay(self):
        now = datetime.utcnow()
        bars = [
            Bar(symbol="EURUSD", timestamp=now - timedelta(minutes=5 * i), open=1.10, high=1.11, low=1.09, close=1.105, volume=500.0, tick_count=30)
            for i in range(5)
        ]
        self.data_store.insert_candles(bars)
        replay = HistoricalReplayEngine(self.data_store)

        replayed_count = 0
        def on_bar_slice(symbol, slice_bars):
            nonlocal replayed_count
            replayed_count += 1

        replay.replay_bars("EURUSD", on_bar_slice, limit=5)
        self.assertEqual(replayed_count, 5)

if __name__ == "__main__":
    unittest.main()
