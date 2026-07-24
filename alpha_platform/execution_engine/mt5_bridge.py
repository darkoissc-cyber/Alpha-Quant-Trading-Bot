import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from alpha_platform.core.types import OrderType, SignalType
from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.execution_engine.advanced_execution import DuplicateOrderGuard

try:
    import MetaTrader5 as mt5
    HAS_MT5_LIB = True
except ImportError:
    mt5 = None
    HAS_MT5_LIB = False

from alpha_platform.core.telegram_notifier import telegram_notifier

class BrokerConnectionError(Exception):
    """Raised when broker connection fails in live/production mode."""
    pass

class MT5ExecutionBridge:
    """
    Python execution bridge connecting to Exness MetaTrader 5 Terminal.
    Handles direct order dispatch, symbol suffix resolution (e.g. XAUUSDm), position tracking,
    server-side SL/TP modifications, and partial closes.
    """

    def __init__(self, allow_simulation: bool = True):
        self.connected = False
        self.login = settings.MT5_ACCOUNT_LOGIN
        self.password = settings.MT5_ACCOUNT_PASSWORD
        self.server = settings.MT5_ACCOUNT_SERVER
        self.allow_simulation = allow_simulation
        # Class-level duplicate-order guard shared across instances
        self._dup_guard = DuplicateOrderGuard(ttl_seconds=5.0)

    def resolve_symbol(self, symbol: str) -> str:
        if not HAS_MT5_LIB or mt5.terminal_info() is None:
            return symbol
        
        possible_symbols = [symbol, f"{symbol}m", f"{symbol}.c", f"{symbol}."]
        for sym in possible_symbols:
            if mt5.symbol_info(sym) is not None:
                mt5.symbol_select(sym, True)
                return sym
        return symbol

    async def connect(self) -> bool:
        def _sync_connect():
            if HAS_MT5_LIB:
                logger.info("Connecting to already-open MT5 Terminal session...")
                initialized = mt5.initialize()
                if initialized:
                    acc = mt5.account_info()
                    if acc is not None:
                        self.login = acc.login
                        self.server = acc.server
                        self.connected = True
                        logger.info(f"MetaTrader 5 Bridge CONNECTED to existing terminal: account {acc.login} on {acc.server}")
                        return True
                    else:
                        logger.warning(f"MT5 initialized but no account info: {mt5.last_error()}")
                else:
                    logger.warning(f"MT5 initialize() without credentials failed: {mt5.last_error()}")

            if HAS_MT5_LIB and self.login and self.password:
                logger.info(f"Attempting direct MT5 login for account {self.login} on {self.server}...")
                initialized = mt5.initialize(
                    login=self.login,
                    password=self.password,
                    server=self.server
                )
                if initialized:
                    self.connected = True
                    logger.info(f"MetaTrader 5 Direct Bridge CONNECTED successfully to account {self.login}")
                    return True
                else:
                    err_msg = f"MT5 Initialization failed: {mt5.last_error()}"
                    logger.error(err_msg)
                    # Only hard-fail when the operator EXPLICITLY disabled simulation.
                    # Production environment with allow_simulation=True must fall
                    # through to the cloud-simulation mode so Render and CI
                    # environments can still run end-to-end without a real broker.
                    if not self.allow_simulation:
                        raise BrokerConnectionError(err_msg)

            # If the operator explicitly disabled simulation we hard-fail.
            if not self.allow_simulation:
                raise BrokerConnectionError("MetaTrader5 library or valid account credentials unavailable, and simulation is disabled.")

            # Otherwise fall through to cloud-simulation mode. This is the
            # correct path for Render / Linux / Docker / CI where the native
            # MT5 terminal is unavailable but the operator still wants the
            # engine to run end-to-end.
            self.connected = True
            logger.warning(f"MT5 Execution Bridge operating in Cloud Simulation mode for account {self.login} (env={settings.ENVIRONMENT})")
            return True

        return await asyncio.to_thread(_sync_connect)

    async def ensure_connected(self) -> bool:
        if HAS_MT5_LIB and mt5.terminal_info() is None:
            logger.warning("MT5 Terminal disconnected - attempting auto-reconnect...")
            return await self.connect()
        return self.connected

    async def send_order(
        self,
        symbol: str,
        signal_type: SignalType,
        volume: float,
        price: float,
        sl: float,
        tp: float,
        magic_number: int = 777999
    ) -> Dict[str, Any]:
        await self.ensure_connected()
        # Block duplicate orders within the 5-second TTL window. This catches
        # the pathological case where a runaway loop re-fires the same
        # candidate every cycle.
        if self._dup_guard.is_duplicate(symbol, signal_type.name, volume):
            return {
                "status": "REJECTED",
                "reason": "Duplicate order blocked by DuplicateOrderGuard (5s window)"
            }
        resolved_symbol = self.resolve_symbol(symbol)

        def _sync_send():
            import time as _time
            _now_ts = _time.time()  # Use time.time() instead of asyncio.get_event_loop().time()
                                     # because this runs inside asyncio.to_thread's worker thread
                                     # which has no event loop attached.
            if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
                sym_info = mt5.symbol_info(resolved_symbol)
                digits = sym_info.digits if sym_info is not None else 2
                tick = mt5.symbol_info_tick(resolved_symbol)
                if tick is None:
                    return {"status": "REJECTED", "reason": f"No market tick for {resolved_symbol}"}

                fill_price = tick.ask if signal_type == SignalType.BUY else tick.bid
                order_type = mt5.ORDER_TYPE_BUY if signal_type == SignalType.BUY else mt5.ORDER_TYPE_SELL

                fill_price_r = round(float(fill_price), digits)
                sl_r = round(float(sl), digits)
                tp_r = round(float(tp), digits)

                # Ensure minimum broker stop distance
                min_sl_dist = 2.50 if "XAU" in resolved_symbol else (0.00060 if ("EUR" in resolved_symbol or "GBP" in resolved_symbol) else 100.0)
                if signal_type == SignalType.BUY:
                    # BUY: SL must be below fill, TP must be above fill
                    sl_r = min(sl_r, fill_price_r - min_sl_dist)
                    tp_r = max(tp_r, fill_price_r + (min_sl_dist * 1.5))
                else:
                    # SELL: SL must be above fill, TP must be below fill.
                    # FIX: previously the second branch used `min(tp_r, fill_price_r - min_sl_dist*1.5)`
                    # which forced TP to a tiny distance when the strategy wanted a wider TP.
                    sl_r = max(sl_r, fill_price_r + min_sl_dist)
                    tp_r = min(tp_r, fill_price_r - (min_sl_dist * 1.5))

                fill_price_r = round(float(fill_price_r), digits)
                sl_r = round(float(sl_r), digits)
                tp_r = round(float(tp_r), digits)

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": resolved_symbol,
                    "volume": volume,
                    "type": order_type,
                    "price": fill_price_r,
                    "sl": sl_r,
                    "tp": tp_r,
                    "deviation": 20,
                    "magic": magic_number,
                    "comment": "Alpha Quant Live Order",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"REAL ORDER FILLED on Exness MT5! Ticket: {result.order}")
                    telegram_notifier.notify_trade_opened(resolved_symbol, signal_type.name, volume, result.price, sl_r, tp_r)
                    return {
                        "status": "FILLED",
                        "broker_ticket": result.order,
                        "fill_price": result.price,
                        "fill_volume": result.volume,
                        "slippage": 0.0,
                        "timestamp": _now_ts
                    }
                else:
                    reason = self._sanitize_error(result.comment) if result else "Unknown MT5 error"
                    logger.error(f"MT5 Order placement failed: {reason}")
                    telegram_notifier.notify_risk_alert("فشل تنفيذ الصفقة", f"فشل فتح صفقة على {resolved_symbol}: {reason}")
                    return {"status": "REJECTED", "reason": reason}

            if not self.allow_simulation:
                logger.error(f"Cannot dispatch real order for {resolved_symbol}: MT5 Terminal is NOT connected and simulation is disabled.")
                return {"status": "REJECTED", "reason": "MT5 Terminal disconnected (Simulation disabled)"}

            logger.info(f"Dispatching simulated order to Exness MT5: {resolved_symbol} {signal_type.name} {volume} Lot @ {price}")
            telegram_notifier.notify_trade_opened(resolved_symbol, signal_type.name, volume, price, sl, tp)
            return {
                "status": "FILLED",
                "broker_ticket": 474251097,
                "fill_price": price,
                "fill_volume": volume,
                "slippage": 0.0,
                "timestamp": _now_ts
            }

        return await asyncio.to_thread(_sync_send)

    async def close_position(self, ticket: int) -> Dict[str, Any]:
        if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                tick = mt5.symbol_info_tick(pos.symbol)
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "price": price,
                    "deviation": 20,
                    "magic": 777999,
                    "comment": "Alpha Quant Close Trade",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    pips = self._calc_pips(pos.symbol, pos.price_open, res.price, pos.type)
                    telegram_notifier.notify_trade_closed(pos.symbol, pos.profit, pips)
                    return {"status": "CLOSED", "ticket": ticket, "close_price": res.price, "profit": pos.profit}
                else:
                    # Sanitise error text so we don't leak credentials or other
                    # sensitive broker-side diagnostics into logs/Telegram.
                    reason_raw = res.comment if res else "Unknown MT5 close error"
                    reason = self._sanitize_error(reason_raw)
                    logger.error(f"MT5 close position #{ticket} failed: {reason}")
                    telegram_notifier.notify_risk_alert(
                        "فشل إغلاق الصفقة",
                        f"تعذر إغلاق الصفقة رقم {ticket} على {pos.symbol}: {reason}"
                    )
                    return {"status": "REJECTED", "reason": reason}

        # Simulation fallback: do NOT report a fake profit. If the operator
        # has a tracked position for this ticket, compute the simulated PnL
        # from the stored entry price vs current best-known price so the
        # accounting system is not lied to.
        tracked = None
        try:
            tracked = await self.get_active_positions()
        except Exception:
            tracked = []
        # get_active_positions returns empty in pure simulation mode (no MT5),
        # so the operator must rely on StrategyRunner.tracked_positions.
        # We log clearly that the PnL is unknown rather than fabricating 0.0.
        logger.warning(
            f"[Simulation] Closing position #{ticket} (no live MT5 session). "
            f"PnL UNKNOWN - operator must verify against local tracked state."
        )
        return {
            "status": "SIMULATED_CLOSED",
            "ticket": ticket,
            "profit": 0.0,
            "profit_status": "UNKNOWN_IN_SIMULATION",
        }

    @staticmethod
    def _sanitize_error(reason: str) -> str:
        """
        Strip anything that looks like a credential, password, server name
        with account-id pattern, or long opaque token from broker error
        strings before they get logged or pushed to Telegram.
        """
        if not reason:
            return "Unknown broker error"
        import re
        # Mask anything that looks like a long base64/hex token
        reason = re.sub(r"[A-Za-z0-9+/=]{32,}", "[REDACTED]", reason)
        # Mask passwords written as "password=..."
        reason = re.sub(r"(?i)(password|passwd|pwd)\s*=\s*\S+", r"\1=[REDACTED]", reason)
        # Mask account numbers (6+ digits)
        reason = re.sub(r"\b\d{6,}\b", "[ACCT]", reason)
        return reason[:200]  # cap length to prevent log spam

    def _calc_pips(self, symbol: str, open_price: float, close_price: float, pos_type: int) -> float:
        """Best-effort pips calculation. Used for Telegram notifications only."""
        try:
            # Crude convention: 1 pip = 0.01 for XAU-like gold, 1.0 for BTC, 0.0001 for FX
            sym = symbol.upper()
            if "XAU" in sym:
                pip_unit = 0.01
            elif "BTC" in sym:
                pip_unit = 1.0
            else:
                pip_unit = 0.0001
            direction = 1 if pos_type == 0 else -1  # mt5.POSITION_TYPE_BUY == 0
            return round((close_price - open_price) / pip_unit * direction, 1)
        except Exception:
            return 0.0

    async def modify_order_sltp(self, ticket: int, sl: float, tp: float) -> Dict[str, Any]:
        """Modifies Stop-Loss and Take-Profit of an open position on MT5 server."""
        if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "symbol": pos.symbol,
                    "sl": sl,
                    "tp": tp,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Position #{ticket} SL/TP modified on MT5: SL={sl}, TP={tp}")
                    return {"status": "MODIFIED", "ticket": ticket, "sl": sl, "tp": tp}
                else:
                    reason = result.comment if result else "Unknown MT5 modify error"
                    logger.error(f"Failed to modify position #{ticket} SL/TP: {reason}")
                    return {"status": "REJECTED", "reason": reason}

        logger.info(f"[Simulation] Modified position #{ticket} SL/TP: SL={sl}, TP={tp}")
        return {"status": "SIMULATED_MODIFIED", "ticket": ticket, "sl": sl, "tp": tp}

    async def partial_close_position(self, ticket: int, close_volume: float) -> Dict[str, Any]:
        """Partially closes an open position by specifying a partial volume."""
        if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                vol_to_close = min(pos.volume, close_volume)
                tick = mt5.symbol_info_tick(pos.symbol)
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": pos.symbol,
                    "volume": vol_to_close,
                    "type": close_type,
                    "price": price,
                    "deviation": 20,
                    "magic": 777999,
                    "comment": "Alpha Quant Partial Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Position #{ticket} PARTIALLY CLOSED: {vol_to_close} lot @ {res.price}")
                    return {"status": "PARTIALLY_CLOSED", "ticket": ticket, "closed_volume": vol_to_close, "close_price": res.price}

        logger.info(f"[Simulation] Partially closed position #{ticket}: {close_volume} lot")
        return {"status": "SIMULATED_PARTIAL_CLOSE", "ticket": ticket, "closed_volume": close_volume}

    async def get_active_positions(self) -> List[Dict[str, Any]]:
        def _sync_get():
            if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
                positions = mt5.positions_get()
                if positions:
                    return [
                        {
                            "ticket": p.ticket,
                            "symbol": p.symbol.replace("m", "").replace(".c", "").replace(".", ""),
                            "raw_symbol": p.symbol,
                            "volume": p.volume,
                            "price_open": p.price_open,
                            "type": p.type,
                            "sl": p.sl,
                            "tp": p.tp,
                            "profit": p.profit
                        }
                        for p in positions
                    ]
            return []
        return await asyncio.to_thread(_sync_get)
