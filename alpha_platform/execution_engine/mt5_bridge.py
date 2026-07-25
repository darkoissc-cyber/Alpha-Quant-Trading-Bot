import os
import json
import asyncio
from datetime import datetime, timezone
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

from alpha_platform.core.telegram_notifier import telegram_notifier  # Used for trade open/close alerts only

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
        if not HAS_MT5_LIB:
            logger.warning("MetaTrader5 library not found. Running in simulation mode.")
            return False

        def _sync_connect():
            if not mt5.initialize(login=self.login, password=self.password, server=self.server):
                logger.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False
            return True

        self.connected = await asyncio.to_thread(_sync_connect)
        if self.connected:
            logger.info(f"MT5 Execution Bridge connected: account {self.login} on {self.server}")
        return self.connected

    async def ensure_connected(self):
        if not self.connected:
            await self.connect()

    async def is_market_open(self, symbol: str) -> bool:
        """Checks if the market for a given symbol is currently open for trading."""
        def _sync_check():
            if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
                resolved = self.resolve_symbol(symbol)
                sym_info = mt5.symbol_info(resolved)
                if sym_info is None:
                    return False
                
                # Check if symbol is currently tradable
                if sym_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                    return False
                
                # Check current tick time vs local time to detect weekend/closed market
                tick = mt5.symbol_info_tick(resolved)
                if tick is None:
                    return False
                
                tick_time = datetime.fromtimestamp(tick.time, tz=timezone.utc).replace(tzinfo=None)
                now_time = datetime.now()
                # If the last tick is older than 5 minutes, market is likely closed or stale
                if (now_time - tick_time).total_seconds() > 300:
                    return False
                
                return True
            return True # Assume open in simulation mode
        return await asyncio.to_thread(_sync_check)

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
            _now_ts = _time.time()
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
                    sl_r = min(sl_r, fill_price_r - min_sl_dist)
                    tp_r = max(tp_r, fill_price_r + (min_sl_dist * 1.5))
                else:
                    sl_r = max(sl_r, fill_price_r + min_sl_dist)
                    tp_r = min(tp_r, fill_price_r - (min_sl_dist * 1.5))

                fill_price_r = round(float(fill_price_r), digits)
                sl_r = round(float(sl_r), digits)
                tp_r = round(float(tp_r), digits)

                vol_step = sym_info.volume_step if sym_info is not None else 0.01
                vol_min = sym_info.volume_min if sym_info is not None else 0.01
                final_volume = round(max(vol_min, (round(volume / vol_step) * vol_step)), 2)
                logger.info(f"[MT5Bridge] Normalizing volume for {resolved_symbol}: requested={volume}, final={final_volume} (step={vol_step}, min={vol_min})")

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": resolved_symbol,
                    "volume": final_volume,
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
                    reason = result.comment if result else "Unknown MT5 error"
                    logger.error(f"MT5 Order placement failed: {reason}")
                    return {"status": "REJECTED", "reason": reason}

            if not self.allow_simulation:
                logger.error(f"Cannot dispatch real order for {resolved_symbol}: MT5 Terminal is NOT connected and simulation is disabled.")
                return {"status": "REJECTED", "reason": "MT5 Terminal disconnected (Simulation disabled)"}

            logger.info(f"MT5 Terminal disconnected on cloud server - skipping real order for {resolved_symbol} (Simulation mode)")
            return {
                "status": "REJECTED",
                "reason": "MT5 Terminal disconnected on cloud server. Real order dispatch requires local MT5 execution bridge."
            }

        return await asyncio.to_thread(_sync_send)

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
                elif result and "No changes" in result.comment:
                    logger.debug(f"Position #{ticket} SL/TP already at target values.")
                    return {"status": "MODIFIED", "ticket": ticket, "sl": sl, "tp": tp, "note": "No changes required"}
                else:
                    reason = result.comment if result else "Unknown MT5 modify error"
                    logger.error(f"Failed to modify position #{ticket} SL/TP: {reason}")
                    return {"status": "REJECTED", "reason": reason}

        logger.info(f"[Simulation] Modified position #{ticket} SL/TP: SL={sl}, TP={tp}")
        return {"status": "SIMULATED_MODIFIED", "ticket": ticket, "sl": sl, "tp": tp}

    async def get_active_positions(self) -> List[Dict[str, Any]]:
        """Fetches all open positions currently active on the broker account."""
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
                            "profit": p.profit,
                            "time_open": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
                            "price_current": p.price_current if hasattr(p, 'price_current') else p.price_open
                        }
                        for p in positions
                    ]
            return []
        return await asyncio.to_thread(_sync_get)

    async def close_position(self, ticket: int) -> Dict[str, Any]:
        """Closes an open position at market price."""
        if HAS_MT5_LIB and self.connected and mt5.terminal_info() is not None:
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                tick = mt5.symbol_info_tick(pos.symbol)
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": 777999,
                    "comment": "Alpha Quant Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Position #{ticket} CLOSED on MT5.")
                    return {"status": "CLOSED", "ticket": ticket}
                else:
                    reason = result.comment if result else "Unknown MT5 close error"
                    logger.error(f"Failed to close position #{ticket}: {reason}")
                    return {"status": "REJECTED", "reason": reason}
        return {"status": "SIMULATED_CLOSED", "ticket": ticket}

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
                    "symbol": pos.symbol,
                    "volume": vol_to_close,
                    "type": close_type,
                    "position": ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": 777999,
                    "comment": "Alpha Quant Partial Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Position #{ticket} PARTIALLY CLOSED on MT5. Vol closed: {vol_to_close}")
                    return {"status": "PARTIALLY_CLOSED", "ticket": ticket, "closed_volume": vol_to_close}
                else:
                    reason = res.comment if res else "Unknown MT5 partial close error"
                    logger.error(f"Failed to partially close position #{ticket}: {reason}")
                    return {"status": "REJECTED", "reason": reason}
        return {"status": "SIMULATED_PARTIAL_CLOSE", "ticket": ticket, "closed_volume": close_volume}
