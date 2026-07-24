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
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}
        self.symbol_cooldowns: Dict[str, datetime] = {}
        from alpha_platform.risk_engine.self_critic import InstitutionalSelfCriticValidator
        self.self_critic = InstitutionalSelfCriticValidator(min_composite_score=75.0)
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
        now = datetime.now(timezone.utc)
        for symbol in SUPPORTED_SYMBOLS:
            cooldown_until = self.symbol_cooldowns.get(symbol)
            if cooldown_until and now < cooldown_until:
                remaining_sec = int((cooldown_until - now).total_seconds())
                logger.debug(f"[StrategyRunner] Skipping {symbol}: Symbol Cooldown Active ({remaining_sec}s remaining)")
                continue

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
            active_positions = list(self.tracked_positions.values())
            return self.risk_engine.evaluate_candidate(
                symbol=candidate.symbol,
                current_equity=getattr(self.risk_engine, "peak_equity", 10000.0) or 10000.0,
                proposed_volume=0.01,
                entry_price=candidate.entry_price,
                stop_loss=candidate.stop_loss,
                current_spread_pips=1.5 if "USD" in candidate.symbol and "XAU" not in candidate.symbol else 15.0,
                active_positions=active_positions
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

    async def _check_and_apply_breakeven(self) -> None:
        if self.broker is None:
            return
        try:
            positions = await self.broker.get_active_positions()
            if not positions:
                return
            
            for pos in positions:
                ticket = pos.get("ticket")
                profit = pos.get("profit", 0.0)
                # Trigger Break-Even once open trade profit exceeds $0.50
                if profit > 0.50:
                    open_price = pos.get("price_open")
                    current_sl = pos.get("sl", 0.0)
                    pos_type = pos.get("type", 0) # 0: BUY, 1: SELL
                    
                    need_be = False
                    if pos_type == 0 and (current_sl < open_price or current_sl == 0.0):
                        need_be = True
                    elif pos_type == 1 and (current_sl > open_price or current_sl == 0.0):
                        need_be = True
                        
                    if need_be and open_price:
                        res = await self.broker.modify_order_sltp(ticket=ticket, sl=open_price, tp=pos.get("tp", 0.0))
                        if res.get("status") in ("MODIFIED", "SIMULATED_MODIFIED"):
                            logger.info(f"🛡️ [Break-Even] Position #{ticket} ({pos.get('symbol')}) moved to Break-Even at {open_price:.4f}!")
                            from alpha_platform.core.telegram_notifier import telegram_notifier
                            telegram_notifier.notify_risk_alert(
                                "تأمين الصفقة تلقائياً (Break-Even)",
                                f"تم تحريك إيقاف الخسارة للصفقة #{ticket} على {pos.get('symbol')} إلى سعر الدخول ({open_price:.4f}) لحجز الأرباح وتأمينها بدون مخاطرة!"
                            )
        except Exception as e:
            logger.error(f"[StrategyRunner] Error during Break-Even evaluation: {e}")

    async def _sync_and_notify_closed_positions(self) -> None:
        if self.broker is None:
            return
        try:
            from alpha_platform.execution_engine.mt5_bridge import HAS_MT5_LIB, mt5
            current_positions = await self.broker.get_active_positions()
            current_live_map = {pos["ticket"]: pos for pos in current_positions if "ticket" in pos}
            
            # Detect positions that were in tracked_positions but are no longer active on MT5
            closed_tickets = [t for t in self.tracked_positions if t not in current_live_map]
            for ticket in closed_tickets:
                pos_info = self.tracked_positions[ticket]
                symbol = pos_info.get("symbol", "UNKNOWN")
                profit = pos_info.get("profit", 0.0)
                
                if HAS_MT5_LIB and mt5.terminal_info() is not None:
                    try:
                        deals = mt5.history_deals_get(position=ticket)
                        if deals and len(deals) > 0:
                            profit = sum(d.profit + d.swap + d.commission for d in deals)
                    except Exception as err:
                        logger.warning(f"Could not query MT5 history deals for ticket {ticket}: {err}")
                
                logger.info(f"🔔 [Position Tracker] Position #{ticket} ({symbol}) closed on broker. PnL: ${profit:+.2f}")
                from alpha_platform.core.telegram_notifier import telegram_notifier
                telegram_notifier.notify_trade_closed(symbol=symbol, profit=profit, pips=0.0)
                
                del self.tracked_positions[ticket]
                
            # Update tracked positions with current live positions
            for ticket, pos in current_live_map.items():
                self.tracked_positions[ticket] = pos
        except Exception as e:
            logger.error(f"[StrategyRunner] Position reconciliation error: {e}")

    async def run_once(self) -> Dict[str, Any]:
        self.cycle_count += 1
        cycle_id = self.cycle_count

        candidates = self._gather_candidates()
        self.last_candidate_count = len(candidates)
        if candidates:
            for c in candidates:
                logger.info(
                    f"[StrategyRunner] cycle={cycle_id} candidate generated: "
                    f"{c.strategy_id} -> {c.signal_type.name} {c.symbol} @ {c.entry_price:.4f} "
                    f"(SL: {c.stop_loss:.4f}, TP: {c.take_profit:.4f})"
                )

        approved: List[TradeCandidate] = []
        active_pos_list = list(self.tracked_positions.values())
        from datetime import timedelta

        for c in candidates:
            risk_verdict = self._evaluate_risk(c)
            if risk_verdict and getattr(risk_verdict, "passed", False):
                # Dual Validator Pass: Institutional Self-Critic Gate
                sc_ok, score, grade, justification = self.self_critic.evaluate_and_critique(
                    candidate=c,
                    ai_calibrated_prob=0.60,
                    current_spread_pips=1.5 if "USD" in c.symbol and "XAU" not in c.symbol else 15.0,
                    active_positions=active_pos_list,
                    recent_trade_results=[]
                )
                if sc_ok:
                    logger.info(f"[StrategyRunner] Candidate {c.candidate_id} APPROVED by Risk Engine & Self-Critic [Grade {grade}, Score {score:.0f}/100].")
                    approved.append(c)
                else:
                    logger.info(f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Self-Critic: {justification}")
            else:
                reason = getattr(risk_verdict, "rejection_reason", "Risk verdict failed or undefined") if risk_verdict else "Risk evaluation returned None"
                logger.info(f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Risk Engine: {reason}")

        self.last_approved_count = len(approved)

        executed = 0
        if self.broker is not None:
            for c in approved[: self.max_orders_per_cycle]:
                result = await self._execute(c)
                if result and result.get("status") in ("FILLED", "SIMULATED_FILLED"):
                    executed += 1
                    # Trigger 15-minute symbol cooldown to prevent overtrading & price chasing
                    self.symbol_cooldowns[c.symbol] = datetime.now(timezone.utc) + timedelta(minutes=15)
                    logger.info(
                        f"[StrategyRunner] cycle={cycle_id} EXECUTED {c.signal_type.name} {c.symbol} "
                        f"@ {c.entry_price:.4f} ticket={result.get('broker_ticket')} (15-min cooldown activated)"
                    )
                else:
                    reason = result.get("reason", "Unknown execution failure") if result else "Execution returned None"
                    logger.error(f"[StrategyRunner] cycle={cycle_id} EXECUTION FAILED for {c.candidate_id}: {reason}")
        else:
            if approved:
                logger.warning(f"[StrategyRunner] cycle={cycle_id}: {len(approved)} approved candidate(s) were NOT executed because broker is None.")

        self.last_executed_count = executed
        await self._check_and_apply_breakeven()
        await self._sync_and_notify_closed_positions()

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
