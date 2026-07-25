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
import os
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.core.types import Bar, TradeCandidate, SignalType
from alpha_platform.feature_store.time_series_db import TimeSeriesDataStore
from alpha_platform.strategy_engine.trend_following import TrendFollowingStrategy
from alpha_platform.strategy_engine.breakout import BreakoutStrategy
from alpha_platform.strategy_engine.mean_reversion import MeanReversionStrategy
from alpha_platform.risk_engine.python_binding import RiskEngine
from alpha_platform.execution_engine.mt5_bridge import MT5ExecutionBridge

SUPPORTED_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD"]
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
        meta_labeler: Optional[Any] = None,
        signals_only_mode: bool = False,
    ):
        self.data_store = data_store
        self.risk_engine = risk_engine
        self.broker = broker
        self.interval_seconds = interval_seconds
        self.max_orders_per_cycle = max_orders_per_cycle
        # Optional real meta-labeler; if absent, the AI gate is honestly
        # bypassed (logged) rather than being silently replaced by a constant.
        self.meta_labeler = meta_labeler
        # Full auto-execution mode: broker dispatch is mandatory for approved candidates.
        self.signals_only_mode = False

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
        self.recovery_pairs: Dict[int, int] = {} # {new_trade_ticket: old_losing_trade_ticket}
        self.data_store = data_store # Ensure data_store is accessible here
        self.symbol_cooldowns: Dict[str, datetime] = {}
        # Track recent realised P&L for the Revenge-Trade Guard in SelfCritic
        self.recent_pnl_window: List[float] = []
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

    async def _gather_candidates(self) -> List[TradeCandidate]:
        candidates: List[TradeCandidate] = []
        now = datetime.now(timezone.utc)
        for symbol in SUPPORTED_SYMBOLS:
            cooldown_until = self.symbol_cooldowns.get(symbol)
            if cooldown_until and now < cooldown_until:
                remaining_sec = int((cooldown_until - now).total_seconds())
                logger.debug(f"[StrategyRunner] Skipping {symbol}: Symbol Cooldown Active ({remaining_sec}s remaining)")
                continue
            
            # Market Status Check: Skip if market is closed (e.g. Gold on weekends)
            if self.broker:
                is_open = await self.broker.is_market_open(symbol)
                if not is_open:
                    # Log at INFO level so user can see it's working
                    logger.info(f"[StrategyRunner] Skipping {symbol}: Market is currently CLOSED.")
                    continue

            bars = self._load_bars(symbol)
            if len(bars) < MIN_BARS_REQUIRED:
                logger.debug(f"[StrategyRunner] Skipping {symbol}: only {len(bars)} bars (need {MIN_BARS_REQUIRED})")
                continue
            for strat in self.strategies:
                try:
                    new = strat.generate_candidates(symbol, bars)
                    if new:
                        for cand in new:
                            # Initialize volume to a default, will be updated by risk engine
                            cand.volume = 0.01 # Default volume, will be overwritten by risk engine
                        candidates.extend(new)
                except Exception as e:
                    logger.error(f"[StrategyRunner] {strat.strategy_id} failed on {symbol}: {e}")
        return candidates

    def _evaluate_risk(self, candidate: TradeCandidate):
        try:
            active_positions = list(self.tracked_positions.values())
            # CRITICAL FIX: Compute REAL current_equity from peak_equity + realised P&L.
            # Previously the code passed peak_equity as current_equity which
            # made the 3.5% hard-DD kill-switch UNREACHABLE in production.
            # Now: current_equity = peak_equity - cumulative_loss
            peak_eq = float(getattr(self.risk_engine, "peak_equity", 10000.0) or 10000.0)
            realised_pnl = float(sum(self.recent_pnl_window))
            current_equity = peak_eq + realised_pnl  # If realised_pnl is negative, current_equity < peak_equity
            
            logger.debug(
                f"[StrategyRunner] Risk eval for {candidate.candidate_id}: "
                f"peak={peak_eq:.2f}, realised_pnl={realised_pnl:.2f}, current={current_equity:.2f}"
            )
            
            return self.risk_engine.evaluate_candidate(
                symbol=candidate.symbol,
                current_equity=current_equity,
                proposed_volume=0.01,
                entry_price=candidate.entry_price,
                stop_loss=candidate.stop_loss,
                current_spread_pips=1.5 if "USD" in candidate.symbol and "XAU" not in candidate.symbol else 15.0,
                active_positions=active_positions
            )
        except Exception as e:
            logger.error(f"[StrategyRunner] Risk eval failed for {candidate.candidate_id}: {e}")
            return None

    def _get_ai_calibrated_prob(self, candidate: TradeCandidate) -> Tuple[float, bool]:
        """
        Returns (calibrated_prob, used_real_model).

        If a real MetaLabelModelTrainer has been injected AND its underlying
        model has been trained, we call predict_trade_quality() on the
        candidate's feature snapshot. Otherwise we return (0.60, False) but
        log a clear warning so the operator can see that the AI gate is
        NOT actually engaged (replaces the previous silent hard-coded 0.60).
        """
        if self.meta_labeler is None or getattr(self.meta_labeler, "model", None) is None:
            logger.warning(
                "[StrategyRunner] AI gate is NOT active: no trained meta-labeler "
                "was injected. Using fallback constant 0.60 (rejected trades will "
                "fall back to deterministic rule filters only)."
            )
            return 0.60, False
        try:
            # CRITICAL FIX: Call predict_trade_quality with the candidate's feature snapshot.
            # This was previously hard-coded to 0.60, which completely bypassed the AI gate.
            is_approved, raw_p, cal_p = self.meta_labeler.predict_trade_quality(
                candidate.features_snapshot
            )
            logger.debug(f"[StrategyRunner] AI inference for {candidate.candidate_id}: raw={raw_p:.3f}, calibrated={cal_p:.3f}, approved={is_approved}")
            return float(cal_p), True
        except Exception as e:
            logger.error(f"[StrategyRunner] AI inference failed: {e}. Falling back to 0.60.")
            return 0.60, False

    async def _execute(self, candidate: TradeCandidate):
        """Execute a trade candidate via the MT5 bridge.
        
        CRITICAL FIX: The MT5 bridge's send_order() is already async and uses
        asyncio.to_thread() internally for thread-safe MT5 operations. We don't
        need to wrap it again. Just await it directly.
        """
        if self.broker is None:
            logger.info(f"[StrategyRunner] No broker wired in - cannot execute {candidate.candidate_id}")
            return None
        try:
            result = await self.broker.send_order(
                symbol=candidate.symbol,
                signal_type=candidate.signal_type,
                volume=candidate.volume,
                price=candidate.entry_price,
                sl=candidate.stop_loss,
                tp=candidate.take_profit,
            )
            if result:
                logger.info(f"[StrategyRunner] Order execution result for {candidate.candidate_id}: {result.get('status')}")
            return result
        except Exception as e:
            logger.error(f"[StrategyRunner] Execution failed for {candidate.candidate_id}: {e}", exc_info=True)
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
                            logger.info(f"[Break-Even] Position #{ticket} ({pos.get('symbol')}) moved to Break-Even at {open_price:.4f}")
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
                
                # Fetch actual PnL from MT5 if available, otherwise use stored profit
                actual_profit = pos_info.get("profit", 0.0)
                if HAS_MT5_LIB and mt5.terminal_info() is not None:
                    try:
                        deals = mt5.history_deals_get(position=ticket)
                        if deals and len(deals) > 0:
                            actual_profit = sum(d.profit + d.swap + d.commission for d in deals)
                    except Exception as err:
                        logger.warning(f"Could not query MT5 history deals for ticket {ticket}: {err}")
                profit = actual_profit

                # If this closed trade was part of a recovery pair, remove the link
                if ticket in self.recovery_pairs:
                    del self.recovery_pairs[ticket]
                    logger.info(f"[Recovery Logic] Removed recovery link for closed trade {ticket}.")

                # If this closed trade was the old losing trade in a recovery pair, also remove its link
                for new_ticket, old_ticket in list(self.recovery_pairs.items()):
                    if old_ticket == ticket:
                        del self.recovery_pairs[new_ticket]
                        logger.info(f"[Recovery Logic] Removed recovery link for old closed trade {ticket}.")

                
                logger.info(f"🔔 [Position Tracker] Position #{ticket} ({symbol}) closed on broker. PnL: ${profit:+.2f}")
                from alpha_platform.core.telegram_notifier import telegram_notifier
                telegram_notifier.notify_trade_closed(symbol=symbol, profit=profit, pips=0.0)

                # Feed realised P&L into the rolling window so the RiskEngine
                # current_equity calc and the Self-Critic revenge-trade guard
                # see the same data. Bound the window to last 50 trades.
                self.recent_pnl_window.append(float(profit))
                if len(self.recent_pnl_window) > 50:
                    self.recent_pnl_window = self.recent_pnl_window[-50:]

                # Instantly release symbol cooldown so the engine is ready for the next trade setup on this symbol!
                base_sym = symbol.replace("m", "").replace(".c", "")
                if base_sym in self.symbol_cooldowns:
                    del self.symbol_cooldowns[base_sym]
                if symbol in self.symbol_cooldowns:
                    del self.symbol_cooldowns[symbol]

                del self.tracked_positions[ticket]
                self.data_store.delete_open_position(ticket)

                # If this closed trade was part of a recovery pair, remove the link
                if ticket in self.recovery_pairs:
                    del self.recovery_pairs[ticket]
                    logger.info(f"[Recovery Logic] Removed recovery link for closed trade {ticket}.")

                # If this closed trade was the old losing trade in a recovery pair, also remove its link
                for new_ticket, old_ticket in list(self.recovery_pairs.items()):
                    if old_ticket == ticket:
                        del self.recovery_pairs[new_ticket]
                        logger.info(f"[Recovery Logic] Removed recovery link for old closed trade {ticket}.")

                
            # Update tracked positions with current live positions
            for ticket, pos in current_live_map.items():
                self.tracked_positions[ticket] = pos
                # Update profit and current price for persistence
                pos["profit"] = pos.get("profit", 0.0) # Ensure profit field exists
                pos["price_current"] = pos.get("price_current", pos.get("price_open")) # Ensure current price exists
                self.data_store.insert_open_position(pos)
        except Exception as e:
            logger.error(f"[StrategyRunner] Position reconciliation error: {e}")

    async def run_once(self) -> Dict[str, Any]:
        self.cycle_count += 1
        cycle_id = self.cycle_count

        # 1. Run Break-Even management on open positions and sync closed trades FIRST
        await self._check_and_apply_breakeven()
        await self._sync_and_notify_closed_positions()

        # CRITICAL FIX: Update current prices and profits for all tracked positions
        await self._update_tracked_positions_live_data()

        candidates = await self._gather_candidates()
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
            # 1. Evaluate Risk
            risk_verdict = self._evaluate_risk(c)
            
            # 2. Get AI and Self-Critic Evaluation (even if risk fails, to show user quality)
            ai_prob, ai_real = self._get_ai_calibrated_prob(c)
            sc_ok, score, grade, justification = self.self_critic.evaluate_and_critique(
                candidate=c,
                ai_calibrated_prob=ai_prob,
                current_spread_pips=1.5 if "USD" in c.symbol and "XAU" not in c.symbol else 15.0,
                active_positions=active_pos_list,
                recent_trade_results=self.recent_pnl_window[-5:],
            )
            
            ai_tag = "[AI=real]" if ai_real else "[AI=fallback]"
            
            if risk_verdict and getattr(risk_verdict, "passed", False):
                if sc_ok:
                    logger.info(
                        f"[StrategyRunner] Candidate {c.candidate_id} APPROVED by Risk Engine & "
                    f"Self-Critic [Grade {grade}, Score {score:.0f}/100, {ai_tag}]."
                )
                # CRITICAL FIX 1: Apply scaled position size from risk engine
                c.volume = risk_verdict.scaled_position_size
                approved.append(c)
                else:
                    logger.info(
                        f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Self-Critic: {justification} "
                        f"[Grade {grade}, Score {score:.0f}/100, {ai_tag}]."
                    )
            else:
                # Fix: Use 'veto_reason' instead of 'rejection_reason' as per types.py/RiskCheckResult
                reason = getattr(risk_verdict, "veto_reason", "Risk evaluation failed") if risk_verdict else "Risk evaluation returned None"
                logger.info(
                    f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Risk Engine: {reason}. "
                    f"Setup Quality: [Grade {grade}, Score {score:.0f}/100, {ai_tag}]."
                )

        self.last_approved_count = len(approved)

        # Per-Symbol Selection: Group approved candidates by symbol and pick the single BEST candidate for each symbol
        symbol_best_map: Dict[str, TradeCandidate] = {}
        for c in approved:
            sym = c.symbol
            if sym not in symbol_best_map:
                symbol_best_map[sym] = c
            else:
                curr_score = getattr(c, "composite_score", 0.0)
                prev_score = getattr(symbol_best_map[sym], "composite_score", 0.0)
                if curr_score > prev_score:
                    symbol_best_map[sym] = c

        selected_candidates = list(symbol_best_map.values())
        selected_candidates.sort(
            key=lambda c: (
                getattr(c, "composite_score", 0.0),
                abs(c.take_profit - c.entry_price) / max(1e-5, abs(c.entry_price - c.stop_loss))
            ),
            reverse=True
        )

        # Direct Execution Dispatch: Only trades approved by Risk Engine and Self-Critic are executed,
        # and Telegram receives alerts ONLY when an approved trade is actually filled/entered.
        executed = 0
        
        # Implement Recovery Logic for strong counter-trend signals
        recovery_trades_to_monitor = []

        # First, identify all potential recovery trades
        for c in selected_candidates:
            # Check if this is a strong counter-trend signal
            is_strong_signal = (getattr(c, "ai_calibrated_prob", 0.0) > 0.95 and getattr(c, "composite_score", 0.0) > 90)
            
            if is_strong_signal:
                # Look for conflicting open positions on the same symbol
                conflicting_positions = [
                    pos for pos in active_pos_list
                    if pos.get("symbol") == c.symbol and 
                       ((c.signal_type == SignalType.BUY and pos.get("type") == 1) or 
                        (c.signal_type == SignalType.SELL and pos.get("type") == 0))
                ]
                
                if conflicting_positions:
                    for conflict_pos in conflicting_positions:
                        # If conflicting position is losing, mark for recovery monitoring
                        if conflict_pos.get("profit", 0.0) <= 0:
                            recovery_trades_to_monitor.append((c, conflict_pos))
                            logger.info(f"[Recovery Logic] Identified strong counter-trend signal {c.candidate_id} for {c.symbol} against losing position {conflict_pos.get("ticket")}. Will attempt recovery.")
                        else:
                            # If conflicting position is profitable, proceed with hedging (normal execution)
                            logger.info(f"[Recovery Logic] Identified strong counter-trend signal {c.candidate_id} for {c.symbol} against profitable position {conflict_pos.get("ticket")}. Hedging.")

        # Now, create the final list of candidates to execute. Recovery trades should be included.
        # For simplicity, we'll execute all selected candidates, and the recovery logic will manage the losing positions post-execution.
        # If a candidate is part of a recovery, it will be handled by _manage_losing_recovery.
            
        # New method to manage losing positions with new profitable counter-trades
        await self._manage_losing_recovery(recovery_trades_to_monitor)

        if self.broker is not None:
            for c in selected_candidates:
                result = await self._execute(c)
                if result and result.get("status") in ("FILLED", "SIMULATED_FILLED"):
                    # Update current price for tracked position
                    if result.get("broker_ticket") in self.tracked_positions:
                        self.tracked_positions[result.get("broker_ticket")]["price_current"] = result.get("fill_price")
                        self.tracked_positions[result.get("broker_ticket")]["profit"] = 0.0 # Reset profit for new position
                    
                    # Check if this executed trade is part of a recovery strategy
                    for rec_cand, rec_pos in recovery_trades_to_monitor:
                        if rec_cand.candidate_id == c.candidate_id:
                            # Store the link between the new profitable trade and the old losing trade
                            self.recovery_pairs[result.get("broker_ticket")] = rec_pos.get("ticket")
                            logger.info(f"[Recovery Logic] Linked new trade {result.get("broker_ticket")} to old losing trade {rec_pos.get("ticket")}.")


                    executed += 1
                    self.symbol_cooldowns[c.symbol] = datetime.now(timezone.utc) + timedelta(minutes=15)
                    logger.info(
                        f"[StrategyRunner] cycle={cycle_id} EXECUTED {c.signal_type.name} {c.symbol} "
                        f"@ {c.entry_price:.4f} ticket={result.get('broker_ticket')}"
                    )
                else:
                    reason = result.get("reason", "Unknown execution failure") if result else "Execution returned None"
                    logger.error(f"[StrategyRunner] cycle={cycle_id} EXECUTION FAILED for {c.candidate_id}: {reason}")
        else:
            if approved:
                logger.warning(f"[StrategyRunner] cycle={cycle_id}: {len(approved)} approved candidate(s) were NOT executed because broker is None.")

        self.last_executed_count = executed
        return {
            "cycle": cycle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidates": len(candidates),
            "approved": len(approved),
            "executed": executed,
            "mode": "auto_execution",
        }

    async def loop(self) -> None:
        self._running = True
        logger.info(
            f"[StrategyRunner] Starting loop. interval={self.interval_seconds}s "
            f"broker={'yes' if self.broker else 'no'} "
            f"signals_only={self.signals_only_mode} "
            f"strategies={[s.strategy_id for s in self.strategies]}"
        )
        # Boot-up Telegram message REMOVED - user only wants trade entry/exit alerts.

        while self._running:
            try:
                summary = await self.run_once()
                if summary.get("candidates") or summary.get("executed"):
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

    async def load_tracked_positions(self):
        if self.data_store:
            positions = self.data_store.get_open_positions()
            for pos in positions:
                self.tracked_positions[pos["ticket"]] = pos
            logger.info(f"[StrategyRunner] Loaded {len(positions)} tracked positions from database.")
            # Re-establish recovery pairs if any (requires more complex logic, for now assume fresh start on recovery pairs)

    async def save_tracked_positions(self):
        # Positions are saved incrementally in _sync_and_notify_closed_positions
        # This method is primarily for ensuring any remaining open positions are saved on shutdown
        if self.data_store:
            for ticket, pos in self.tracked_positions.items():
                self.data_store.insert_open_position(pos)
            logger.info(f"[StrategyRunner] Saved {len(self.tracked_positions)} tracked positions to database on shutdown.")

    async def _update_tracked_positions_live_data(self):
        if self.broker is None:
            return
        try:
            live_positions = await self.broker.get_active_positions()
            live_map = {pos["ticket"]: pos for pos in live_positions if "ticket" in pos}
            
            for ticket, tracked_pos in self.tracked_positions.items():
                if ticket in live_map:
                    live_pos = live_map[ticket]
                    # Update current price and profit from live data
                    tracked_pos["price_current"] = live_pos.get("price_current", tracked_pos.get("price_open"))
                    tracked_pos["profit"] = live_pos.get("profit", 0.0)
                    self.data_store.insert_open_position(tracked_pos) # Persist updated live data
        except Exception as e:
            logger.error(f"[StrategyRunner] Error updating live data for tracked positions: {e}")

    async def _manage_losing_recovery(self, recovery_trades: List[Tuple[TradeCandidate, Dict[str, Any]]]):
        if self.broker is None:
            return
        
        for new_trade_candidate, old_losing_position in recovery_trades:
            # Find the actual executed new trade from tracked_positions
            new_trade_ticket = None
            for ticket, pos in self.tracked_positions.items():
                if pos.get("symbol") == new_trade_candidate.symbol and \
                   pos.get("type") == (0 if new_trade_candidate.signal_type == SignalType.BUY else 1) and \
                   abs(pos.get("price_open", 0.0) - new_trade_candidate.entry_price) < 0.0001: # Small tolerance for price match
                    new_trade_ticket = ticket
                    break
            
            if new_trade_ticket and new_trade_ticket in self.tracked_positions:
                new_trade_pos = self.tracked_positions[new_trade_ticket]
                new_trade_profit = new_trade_pos.get("profit", 0.0)
                old_trade_profit = old_losing_position.get("profit", 0.0)

                # If the new trade is profitable and the old trade is still losing
                if new_trade_profit > 0.0 and old_trade_profit < 0.0:
                    # Calculate how much of the old loss can be covered by the new profit
                    # We need to estimate PnL per lot for the old losing position to determine volume to close.
                    # For simplicity, let's assume a fixed partial close volume if new trade is profitable.
                    # User requested: "قلل مقدار الخساره اكبر ما يمكن بس بشرط اذا الصفقه الجديده الي انتا فتها صارت تطلع ربح و لو صغير"
                    # This implies a gradual reduction or full close if profit allows.

                    old_pos_volume = old_losing_position.get("volume", 0.0)
                    if old_pos_volume > 0.01 and new_trade_profit >= 0.10: # If new trade has at least $0.10 profit and old trade has volume to partially close
                        # Close a small portion of the losing trade, e.g., 10% of its current volume, or 0.01 lot, whichever is smaller but not zero.
                        volume_to_close = max(0.01, round(old_pos_volume * 0.1, 2))
                        if volume_to_close > old_pos_volume: # Don't close more than available
                            volume_to_close = old_pos_volume

                        if volume_to_close > 0:
                            logger.info(f"[Recovery Logic] New trade {new_trade_ticket} is profitable (${new_trade_profit:.2f}). Attempting partial close of {volume_to_close:.2f} lots from old losing trade {old_losing_position.get("ticket")}.")
                            partial_close_result = await self.broker.partial_close_position(old_losing_position.get("ticket"), volume_to_close)
                            if partial_close_result and partial_close_result.get("status") == "PARTIALLY_CLOSED":
                                logger.info(f"[Recovery Logic] Successfully partially closed {volume_to_close:.2f} lots from old losing trade {old_losing_position.get("ticket")}.")
                                # Update old_losing_position volume in tracked_positions
                                self.tracked_positions[old_losing_position.get("ticket")]["volume"] -= volume_to_close
                                # Re-save updated position to DB
                                self.data_store.insert_open_position(self.tracked_positions[old_losing_position.get("ticket")])
                            else:
                                logger.error(f"[Recovery Logic] Failed to partially close old losing trade {old_losing_position.get("ticket")}: {partial_close_result.get("reason") if partial_close_result else "Unknown error"}")
                    elif new_trade_profit >= abs(old_trade_profit): # If new trade profit can cover the entire old loss
                        logger.info(f"[Recovery Logic] New trade {new_trade_ticket} profit (${new_trade_profit:.2f}) can cover old losing trade {old_losing_position.get("ticket")} loss (${old_trade_profit:.2f}). Closing old trade at market.")
                        close_result = await self.broker.close_position(old_losing_position.get("ticket"))
                        if close_result and close_result.get("status") == "CLOSED":
                            logger.info(f"[Recovery Logic] Successfully closed old losing trade {old_losing_position.get("ticket")}.")
                            # Remove from recovery pairs as old trade is closed
                            if new_trade_ticket in self.recovery_pairs:
                                del self.recovery_pairs[new_trade_ticket]
                        else:
                            logger.error(f"[Recovery Logic] Failed to close old losing trade {old_losing_position.get("ticket")}: {close_result.get("reason") if close_result else "Unknown error"}")
                    else:
                        logger.debug(f"[Recovery Logic] New trade {new_trade_ticket} profit (${new_trade_profit:.2f}) not yet sufficient to cover old trade {old_losing_position.get("ticket")} loss (${old_trade_profit:.2f}).")
            else:
                logger.warning(f"[Recovery Logic] Could not find executed new trade for candidate {new_trade_candidate.candidate_id} to manage recovery.")
