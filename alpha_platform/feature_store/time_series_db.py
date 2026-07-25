import os
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from alpha_platform.core.types import Bar, Tick
from alpha_platform.config.logging_config import logger

class TimeSeriesDataStore:
    """
    Production-grade Scalable Time-Series Data Store for Ticks, Candles, and Feature Snapshots.
    Uses SQLite WAL mode with index optimizations for sub-millisecond range queries.
    """
    def __init__(self, db_path: str = "time_series_data.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # Ticks Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ticks (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_sym_ts ON ticks(symbol, timestamp);")

            # Candles Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    tick_count INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_sym_ts ON candles(symbol, timestamp);")

            # Feature Snapshots Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_snapshots (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_features_sym_ts ON feature_snapshots(symbol, timestamp);")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    ticket INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    type INTEGER NOT NULL,
                    volume REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL,
                    sl REAL,
                    tp REAL,
                    timestamp TEXT NOT NULL,
                    profit REAL,
                    magic INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_open_positions_symbol ON open_positions(symbol);")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    peak_equity REAL NOT NULL,
                    day_start_equity REAL NOT NULL,
                    week_start_equity REAL NOT NULL,
                    month_start_equity REAL NOT NULL,
                    emergency_kill_active INTEGER NOT NULL
                )
            """)

    def insert_ticks(self, ticks: List[Tick]):
        if not ticks:
            return
        data = [(t.symbol, t.timestamp.isoformat(), t.bid, t.ask, t.volume) for t in ticks]
        with self._get_connection() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO ticks (symbol, timestamp, bid, ask, volume)
                VALUES (?, ?, ?, ?, ?)
            """, data)

    def insert_candles(self, bars: List[Bar]):
        if not bars:
            return
        data = [(b.symbol, b.timestamp.isoformat(), b.open, b.high, b.low, b.close, b.volume, b.tick_count) for b in bars]
        with self._get_connection() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO candles (symbol, timestamp, open, high, low, close, volume, tick_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            # Checkpoint WAL to keep the -wal file bounded. Without this
            # checkpoint, the WAL grows unbounded over days/weeks of
            # continuous operation and can fill the disk.
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass

    def prune_old_candles(self, keep_last_n: int = 5000):
        """
        Cap the candles table to the most recent N rows per symbol to
        prevent unbounded growth. Safe because the live system only reads
        the last ~100 bars per symbol anyway.
        """
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT symbol FROM candles")
            for (sym,) in cur.fetchall():
                cur.execute(
                    """
                    DELETE FROM candles
                    WHERE symbol = ?
                      AND rowid NOT IN (
                        SELECT rowid FROM candles
                        WHERE symbol = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                      )
                    """,
                    (sym, sym, int(keep_last_n)),
                )
            conn.commit()
            try:
                conn.execute("VACUUM;")
            except Exception:
                pass
            logger.info(f"[TimeSeriesDB] Pruned candles to last {keep_last_n} per symbol.")

    def query_candles(self, symbol: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, limit: int = 1000) -> List[Bar]:
        query = "SELECT symbol, timestamp, open, high, low, close, volume, tick_count FROM candles WHERE symbol = ?"
        params: List[Any] = [symbol]

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        bars = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            for r in reversed(rows):
                ts = datetime.fromisoformat(r[1])
                bars.append(Bar(
                    symbol=r[0], timestamp=ts, open=r[2], high=r[3], low=r[4], close=r[5], volume=r[6], tick_count=r[7]
                ))
        return bars

    def insert_open_position(self, position: Dict[str, Any]):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO open_positions (
                    ticket, symbol, type, volume, entry_price, current_price, sl, tp, timestamp, profit, magic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.get("ticket"), position.get("symbol"), position.get("type"), position.get("volume"),
                position.get("price_open"), position.get("price_current"), position.get("sl"), position.get("tp"),
                position.get("time_open"), position.get("profit"), position.get("magic")
            ))

    def delete_open_position(self, ticket: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM open_positions WHERE ticket = ?", (ticket,))

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ticket, symbol, type, volume, entry_price, current_price, sl, tp, timestamp, profit, magic FROM open_positions")
            rows = cursor.fetchall()
            positions = []
            for r in rows:
                positions.append({
                    "ticket": r[0], "symbol": r[1], "type": r[2], "volume": r[3], "price_open": r[4],
                    "price_current": r[5], "sl": r[6], "tp": r[7], "time_open": r[8], "profit": r[9], "magic": r[10]
                })
            return positions

    def save_risk_state(self, peak_equity: float, day_start_equity: float, week_start_equity: float, month_start_equity: float, emergency_kill_active: bool):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO risk_state (
                    id, peak_equity, day_start_equity, week_start_equity, month_start_equity, emergency_kill_active
                ) VALUES (1, ?, ?, ?, ?, ?)
            """, (peak_equity, day_start_equity, week_start_equity, month_start_equity, int(emergency_kill_active)))

    def load_risk_state(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT peak_equity, day_start_equity, week_start_equity, month_start_equity, emergency_kill_active FROM risk_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {
                    "peak_equity": row[0],
                    "day_start_equity": row[1],
                    "week_start_equity": row[2],
                    "month_start_equity": row[3],
                    "emergency_kill_active": bool(row[4])
                }
            return None

class FeatureCacheEngine:
    """
    High-performance LRU Cache Engine for computed feature vectors.
    """
    def __init__(self, max_entries: int = 5000):
        self.max_entries = max_entries
        self.cache: Dict[str, Dict[str, float]] = {}

    def _make_key(self, symbol: str, timestamp: datetime) -> str:
        return f"{symbol}_{timestamp.isoformat()}"

    def get(self, symbol: str, timestamp: datetime) -> Optional[Dict[str, float]]:
        key = self._make_key(symbol, timestamp)
        return self.cache.get(key)

    def put(self, symbol: str, timestamp: datetime, features: Dict[str, float]):
        key = self._make_key(symbol, timestamp)
        if len(self.cache) >= self.max_entries:
            # Remove oldest key
            oldest = next(iter(self.cache))
            del self.cache[oldest]
        self.cache[key] = features

class HistoricalReplayEngine:
    """
    Event-driven Historical Replay Engine for realistic tick/bar backtesting simulations.
    """
    def __init__(self, data_store: TimeSeriesDataStore):
        self.data_store = data_store

    def replay_bars(self, symbol: str, callback_func, limit: int = 100):
        bars = self.data_store.query_candles(symbol, limit=limit)
        logger.info(f"Historical Replay initiated for {symbol}: {len(bars)} bars.")
        
        for i in range(1, len(bars) + 1):
            historical_slice = bars[:i]
            callback_func(symbol, historical_slice)
        
        logger.info(f"Historical Replay finished for {symbol}.")
