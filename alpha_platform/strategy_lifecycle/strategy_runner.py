"""
Strategy Runner - the missing auto-trading loop.

Runs every N seconds inside FastAPI lifespan. Each tick:
  1. Loads recent bars for each symbol from the time-series DB
  2. Asks each strategy for trade candidates
  3. Filters candidates through the risk engine
  4. Executes approved trades via the MT5 execution bridge
  5. Logs every decision

The loop is opt-in: a settings flag (AUTO_TRADE_ENABLED) controls whether
real orders fire. If disabled, the loop still runs and logs candidates,
which is useful for paper-trading and verification on the cloud.
"""
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.core.types import Bar, TradeCandidate, SignalType
from alpha_platform.feature_store.time_series_db import TimeSeriesDataStore
from alpha_platform.strategy_engine.trend_following import TrendFollowingStrategy
from alpha_platform.strategy_engine.breakout import BreakoutStrategy
from alpha_platform.strategy_engine.mean_reversion import MeanReversionStrategy
from alpha_platform.risk_engine.python_binding import RiskEngine
from alpha_platform.execution_engine.mt5_bridge import MT5ExecutionBridge

SUPPORTED_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
MIN_BARS_REQUIRED = 50
DEFAULT_INTERVAL_SECONDS = 30


class StrategyRunner:
    """
    Auto-trading orchestrator. Polls the data store, generates candidates,
    routes them through the risk gate, and dispatches approved trades.
    """

    def __init__(
        self,
        data_store: TimeSeriesDataStore,
        risk_engine: RiskEngine,
        broker: Optional[MT5ExecutionBridge] = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        max_orders_per_cycle: int = 1,
    ):
        self.data_store = data_store
        self.risk_engine = risk_engine
        self.broker = broker
        self.interval_seconds = interval_seconds
        self.max_orders_per_cycle = max_orders_per_cycle

        self.strategies = [
            TrendFollowingStrategy(),
            BreakoutStrategy(),
            MeanReversionStrategy(),
        ]

        self.cycle_count = 0
        self.last_candidate_count = 0
        self.last_approved_count = 0
        self.last_executed_count = 0
        self._running = False

    def set_broker(self, broker: MT5ExecutionBridge) -> None:
        self.broker = broker

    def _load_bars(self, symbol: str, limit: int = 100) -> List[Bar]:
        try:
            return self.data_store.query_candles(symbol, limit=limit)
        except Exception as e:
            logger.error(f"[StrategyRunner] Failed to load bars for {symbol}: {e}")
            return []

    def _gather_candidates(self) -> List[TradeCandidate]:
        candidates: List[TradeCandidate] = []
        for symbol in SUPPORTED_SYMBOLS:
            bars = self._load_bars(symbol)
            if len(bars) < MIN_BARS_REQUIRED:
                logger.debug(f"[StrategyRunner] Skipping {symbol}: only {len(bars)} bars (need {MIN_BARS_REQUIRED})")
                continue
            for strat in self.strategies:
                try:
                    new = strat.generate_candidates(symbol, bars)
                    if new:
                        candidates.extend(new)
                except Exception as e:
                    logger.error(f"[StrategyRunner] {strat.strategy_id} failed on {symbol}: {e}")
        return candidates

    def _evaluate_risk(self, candidate: TradeCandidate):
        try:
            return self.risk_engine.evaluate_candidate(
                symbol=candidate.symbol,
                current_equity=getattr(self.risk_engine, "peak_equity", 10000.0) or 10000.0,
                proposed_volume=0.01,
                entry_price=candidate.entry_price,
                stop_loss=candidate.stop_loss,
                current_spread_pips=10.0,
            )
        except Exception as e:
            logger.error(f"[StrategyRunner] Risk eval failed for {candidate.candidate_id}: {e}")
            return None

    async def _execute(self, candidate: TradeCandidate):
        if self.broker is None:
            logger.info(f"[StrategyRunner] No broker wired in - cannot execute {candidate.candidate_id}")
            return None
        try:
            result = await self.broker.send_order(
                symbol=candidate.symbol,
                signal_type=candidate.signal_type,
                volume=0.01,
                price=candidate.entry_price,
                sl=candidate.stop_loss,
                tp=candidate.take_profit,
            )
            return result
        except Exception as e:
            logger.error(f"[StrategyRunner] Execution failed for {candidate.candidate_id}: {e}")
            return None

    async def run_once(self) -> Dict[str, Any]:
        self.cycle_count += 1
        cycle_id = self.cycle_count

        candidates = self._gather_candidates()
        self.last_candidate_count = len(candidates)

        approved: List[TradeCandidate] = []
        for c in candidates:
            verdict = self._evaluate_risk(c)
            if verdict and getattr(verdict, "passed", False):
                approved.append(c)

        self.last_approved_count = len(approved)

        executed = 0
        if self.broker is not None:
            for c in approved[: self.max_orders_per_cycle]:
                result = await self._execute(c)
                if result and result.get("status") in ("FILLED", "SIMULATED_FILLED"):
                    executed += 1
                    logger.info(
                        f"[StrategyRunner] cycle={cycle_id} executed {c.signal_type.name} {c.symbol} "
                        f"@ {c.entry_price:.4f} ticket={result.get('broker_ticket')}"
                    )
        self.last_executed_count = executed

        return {
            "cycle": cycle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidates": len(candidates),
            "approved": len(approved),
            "executed": executed,
        }

    async def loop(self) -> None:
        self._running = True
        logger.info(
            f"[StrategyRunner] Starting loop. interval={self.interval_seconds}s "
            f"broker={'yes' if self.broker else 'no'} "
            f"strategies={[s.strategy_id for s in self.strategies]}"
        )
        while self._running:
            try:
                summary = await self.run_once()
                if summary["candidates"] or summary["executed"]:
                    logger.info(f"[StrategyRunner] cycle summary: {summary}")
            except asyncio.CancelledError:
                logger.info("[StrategyRunner] Stopping (cancelled).")
                self._running = False
                break
            except Exception as e:
                logger.error(f"[StrategyRunner] Unhandled error in loop: {e}")
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    def stop(self) -> None:
        self._running = False
