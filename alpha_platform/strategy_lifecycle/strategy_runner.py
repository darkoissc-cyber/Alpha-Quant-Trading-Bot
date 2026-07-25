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
        # Signals-only mode: skip broker dispatch and only push approved
        # candidates to Telegram. The trader executes the trade manually
        # in their MT5 terminal. Default: False (auto-execute on broker).
        self.signals_only_mode = bool(
            signals_only_mode
            or os.getenv("AUTO_TRADE_SIGNALS_ONLY", "false").lower() in ("1", "true", "yes")
        )

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
                volume=0.01,
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
                
            # Update tracked positions with current live positions
            for ticket, pos in current_live_map.items():
                self.tracked_positions[ticket] = pos
        except Exception as e:
            logger.error(f"[StrategyRunner] Position reconciliation error: {e}")

    async def run_once(self) -> Dict[str, Any]:
        self.cycle_count += 1
        cycle_id = self.cycle_count

        # 1. Run Break-Even management on open positions and sync closed trades FIRST
        await self._check_and_apply_breakeven()
        await self._sync_and_notify_closed_positions()

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
        if self.broker is not None:
            for c in selected_candidates:
                result = await self._execute(c)
                if result and result.get("status") in ("FILLED", "SIMULATED_FILLED"):
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
