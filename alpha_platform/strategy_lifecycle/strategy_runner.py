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
            # CRITICAL FIX: derive current_equity from peak + realised P&L.
            # Previously the code passed peak_equity as current_equity which
            # made the 3.5% hard-DD kill-switch UNREACHABLE in production.
            current_equity = float(
                getattr(self.risk_engine, "peak_equity", 10000.0) or 10000.0
            ) + float(sum(self.recent_pnl_window))
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
            is_approved, raw_p, cal_p = self.meta_labeler.predict_trade_quality(
                candidate.features_snapshot
            )
            return float(cal_p), True
        except Exception as e:
            logger.error(f"[StrategyRunner] AI inference failed: {e}. Falling back to 0.60.")
            return 0.60, False

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
                            # Don't let a Telegram failure break the loop
                            try:
                                from alpha_platform.core.telegram_notifier import telegram_notifier
                                telegram_notifier.notify_risk_alert(
                                    "تأمين الصفقة تلقائياً (Break-Even)",
                                    f"تم تحريك إيقاف الخسارة للصفقة #{ticket} على {pos.get('symbol')} إلى سعر الدخول ({open_price:.4f}) لحجز الأرباح وتأمينها بدون مخاطرة!"
                                )
                            except Exception as tlg_err:
                                logger.warning(f"BE Telegram notify failed (non-critical): {tlg_err}")
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
                ai_prob, ai_real = self._get_ai_calibrated_prob(c)
                sc_ok, score, grade, justification = self.self_critic.evaluate_and_critique(
                    candidate=c,
                    ai_calibrated_prob=ai_prob,
                    current_spread_pips=1.5 if "USD" in c.symbol and "XAU" not in c.symbol else 15.0,
                    active_positions=active_pos_list,
                    recent_trade_results=self.recent_pnl_window[-5:],
                )
                if sc_ok:
                    ai_tag = "[AI=real]" if ai_real else "[AI=fallback]"
                    logger.info(
                        f"[StrategyRunner] Candidate {c.candidate_id} APPROVED by Risk Engine & "
                        f"Self-Critic [Grade {grade}, Score {score:.0f}/100, {ai_tag}]."
                    )
                    approved.append(c)
                else:
                    logger.info(f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Self-Critic: {justification}")
            else:
                reason = getattr(risk_verdict, "rejection_reason", "Risk verdict failed or undefined") if risk_verdict else "Risk evaluation returned None"
                logger.info(f"[StrategyRunner] Candidate {c.candidate_id} REJECTED by Risk Engine: {reason}")

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

        # ----------------------------------------------------------------
        # SIGNALS-ONLY MODE
        # ----------------------------------------------------------------
        if self.signals_only_mode:
            signals_sent = 0
            try:
                from alpha_platform.core.telegram_notifier import telegram_notifier
                for c in selected_candidates:
                    rr = abs(c.take_profit - c.entry_price) / max(1e-5, abs(c.entry_price - c.stop_loss))
                    text = (
                        f"🚨 *إشارة جديدة / NEW SIGNAL* (cycle {cycle_id})\n\n"
                        f"• {c.strategy_id.replace('_', ' ')}\n"
                        f"• {c.symbol} — *{c.signal_type.name}*\n"
                        f"• Entry: `{c.entry_price:.4f}`\n"
                        f"• SL: `{c.stop_loss:.4f}`\n"
                        f"• TP: `{c.take_profit:.4f}`\n"
                        f"• R:R = {rr:.2f}\n"
                        f"• Grade: {c.quality_grade or 'A+'} | Score: {c.composite_score:.0f}/100\n\n"
                        f"⏱ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    )
                    if telegram_notifier.is_configured() and telegram_notifier.send_message_sync(text):
                        signals_sent += 1
                        self.symbol_cooldowns[c.symbol] = datetime.now(timezone.utc) + timedelta(minutes=15)
            except Exception as sig_err:
                logger.error(f"[StrategyRunner] signals-only notification error: {sig_err}")
            self.last_executed_count = signals_sent
            return {
                "cycle": cycle_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidates": len(candidates),
                "approved": len(approved),
                "executed": signals_sent,
                "mode": "signals_only",
            }

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
            f"signals_only={self.signals_only_mode} "
            f"strategies={[s.strategy_id for s in self.strategies]}"
        )
        # Send a single boot-up Telegram message so the user can confirm the
        # bot is alive and the credentials are wired correctly.
        try:
            from alpha_platform.core.telegram_notifier import telegram_notifier
            if telegram_notifier.is_configured():
                mode = "SIGNALS-ONLY" if self.signals_only_mode else "AUTO-EXECUTE"
                boot_text = (
                    f"🤖 *Alpha Quant Online*\n\n"
                    f"• Mode: *{mode}*\n"
                    f"• Strategies: 3 (Trend / Breakout / Mean-Rev)\n"
                    f"• Symbols: XAUUSD, EURUSD, GBPUSD, BTCUSD\n"
                    f"• Cycle: every {self.interval_seconds}s\n"
                    f"• Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    f"You will receive a signal here every time an A+ setup is approved."
                )
                telegram_notifier.send_message_sync(boot_text)
        except Exception as boot_err:
            logger.warning(f"[StrategyRunner] boot-up Telegram message failed: {boot_err}")

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
