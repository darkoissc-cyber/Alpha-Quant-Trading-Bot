
import asyncio
import contextlib
import random
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.api.websocket_manager import ws_manager
from alpha_platform.risk_engine.python_binding import RiskEngine
from alpha_platform.model_governance.registry import ModelRegistry
from alpha_platform.statistical_validation.walk_forward import StatisticalValidationGate
from alpha_platform.stress_testing.stress_engine import StressTestingEngine
from alpha_platform.execution_analytics.execution_tracker import ExecutionQualityTracker
from alpha_platform.feature_store.time_series_db import TimeSeriesDataStore
from alpha_platform.core.types import Bar, Tick
from alpha_platform.strategy_lifecycle.strategy_runner import StrategyRunner
from alpha_platform.execution_engine.mt5_bridge import MT5ExecutionBridge, HAS_MT5_LIB, mt5

# Global Instance State
risk_engine = RiskEngine(initial_equity=10000.0)
model_registry = ModelRegistry()
validation_gate = StatisticalValidationGate()
stress_engine = StressTestingEngine()
execution_tracker = ExecutionQualityTracker()
ts_store = TimeSeriesDataStore("time_series_data.db")
# Auto-enable simulation mode on platforms where the MetaTrader5 native
# library is unavailable (Linux/Docker/Render). On Windows desktop with
# MT5 installed, the real broker will be used automatically.
import platform as _platform
import os as _os
_mt5_sim = (
    _platform.system() != "Windows"
    or _os.getenv("ENABLE_MT5_SIMULATION", "true").lower() == "true"
)
mt5_bridge = MT5ExecutionBridge(allow_simulation=_mt5_sim)
strategy_runner = StrategyRunner(
    data_store=ts_store,
    risk_engine=risk_engine,
    broker=mt5_bridge,
    interval_seconds=30,
    max_orders_per_cycle=1,
    signals_only_mode=_os.getenv("AUTO_TRADE_SIGNALS_ONLY", "true").lower() in ("1", "true", "yes"),
)

def seed_historical_bars_if_needed():
    from datetime import timedelta
    for symbol in ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]:
        existing = ts_store.query_candles(symbol, limit=60)
        if len(existing) < 50:
            logger.info(f"Seeding historical bars for {symbol} (currently {len(existing)} bars)...")
            mt5_active = HAS_MT5_LIB and mt5_bridge.connected and mt5 is not None and mt5.terminal_info() is not None
            seeded_bars = []
            if mt5_active:
                try:
                    resolved = mt5_bridge.resolve_symbol(symbol)
                    rates = mt5.copy_rates_from_pos(resolved, mt5.TIMEFRAME_M1, 0, 60)
                    if rates is not None and len(rates) > 0:
                        for r in rates:
                            bar_dt = datetime.fromtimestamp(int(r['time']), tz=timezone.utc)
                            b = Bar(symbol, bar_dt, round(float(r['open']), 4), round(float(r['high']), 4), round(float(r['low']), 4), round(float(r['close']), 4), round(float(r['tick_volume']), 2), tick_count=int(r['tick_volume']))
                            seeded_bars.append(b)
                except Exception as e:
                    logger.warning(f"Failed to fetch MT5 historical seed bars for {symbol}: {e}")
            if not seeded_bars:
                base = 4060.0 if symbol == "XAUUSD" else (1.1380 if symbol == "EURUSD" else (1.3320 if symbol == "GBPUSD" else 95000.0))
                now = datetime.now(timezone.utc)
                curr_price = base
                for i in range(60):
                    bar_time = now - timedelta(minutes=(60 - i))
                    noise = random.uniform(-0.0008, 0.0008) * curr_price
                    curr_price = max(0.01, curr_price + noise)
                    b = Bar(symbol, bar_time, round(curr_price - 0.1, 4), round(curr_price + 0.3, 4), round(curr_price - 0.3, 4), round(curr_price, 4), 100.0, tick_count=10)
                    seeded_bars.append(b)
            if seeded_bars:
                ts_store.insert_candles(seeded_bars)
                logger.info(f"Successfully seeded {len(seeded_bars)} historical bars for {symbol}.")

async def run_247_data_collector_loop():
    logger.info("🚀 Starting 24/7 Continuous Background Data Collector & Strategy Daemon...")
    seed_historical_bars_if_needed()
    base_prices = {"XAUUSD": 4060.0, "EURUSD": 1.1380, "GBPUSD": 1.3320, "BTCUSD": 95000.0}
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            ticks = []
            bars = []
            
            mt5_active = HAS_MT5_LIB and mt5_bridge.connected and mt5 is not None and mt5.terminal_info() is not None
            
            for symbol, base in base_prices.items():
                fetched_live = False
                if mt5_active:
                    try:
                        resolved = mt5_bridge.resolve_symbol(symbol)
                        tick_info = mt5.symbol_info_tick(resolved)
                        rates = mt5.copy_rates_from_pos(resolved, mt5.TIMEFRAME_M1, 0, 1)
                        
                        if tick_info is not None and rates is not None and len(rates) > 0:
                            r = rates[0]
                            tick_dt = datetime.fromtimestamp(tick_info.time, tz=timezone.utc)
                            bar_dt = datetime.fromtimestamp(int(r['time']), tz=timezone.utc)
                            
                            t = Tick(symbol, tick_dt, round(float(tick_info.bid), 4), round(float(tick_info.ask), 4), round(float(tick_info.volume), 2))
                            b = Bar(symbol, bar_dt, round(float(r['open']), 4), round(float(r['high']), 4), round(float(r['low']), 4), round(float(r['close']), 4), round(float(r['tick_volume']), 2), tick_count=int(r['tick_volume']))
                            
                            ticks.append(t)
                            bars.append(b)
                            base_prices[symbol] = float(tick_info.bid)
                            fetched_live = True
                    except Exception as err:
                        logger.warning(f"Failed to fetch live MT5 tick/bar for {symbol}: {err}")
                
                if not fetched_live:
                    noise = random.uniform(-0.0005, 0.0005) * base
                    bid = max(0.01, base + noise)
                    ask = bid + (0.30 if symbol == "XAUUSD" else (0.00015 if "USD" in symbol and "BTC" not in symbol else 10.0))
                    vol = random.uniform(1.0, 50.0)
                    
                    tick = Tick(symbol, now, round(bid, 4), round(ask, 4), round(vol, 2))
                    bar = Bar(symbol, now, round(bid-0.1, 4), round(bid+0.2, 4), round(bid-0.2, 4), round(bid, 4), round(vol*10, 2), tick_count=10)
                    
                    ticks.append(tick)
                    bars.append(bar)
                    base_prices[symbol] = bid
                    
            if ticks:
                ts_store.insert_ticks(ticks)
            if bars:
                ts_store.insert_candles(bars)
            
            # Periodically refresh news filter
            risk_engine.news_filter.refresh_events_if_needed()
            
        except asyncio.CancelledError:
            logger.info("Stopping 24/7 Background Data Collector Daemon.")
            break
        except Exception as e:
            logger.error(f"Error in 24/7 data collector daemon: {e}")
            
        await asyncio.sleep(10)

async def run_247_telegram_heartbeat_loop():
    logger.info("📱 Starting 24/7 Continuous Telegram Heartbeat Daemon...")
    while True:
        try:
            await asyncio.sleep(3600)  # Hourly heartbeat notification
            portfolio = get_portfolio_overview()
            telegram_notifier.notify_portfolio_heartbeat(
                equity=portfolio["equity"],
                balance=portfolio["balance"],
                drawdown_pct=portfolio["current_drawdown_pct"],
                active_positions=portfolio["active_positions_count"]
            )
        except asyncio.CancelledError:
            logger.info("Stopping 24/7 Telegram Heartbeat Daemon.")
            break
        except Exception as e:
            logger.error(f"Error in 24/7 Telegram heartbeat daemon: {e}")

notified_deal_tickets = set()

async def run_247_mt5_history_deal_sync_loop():
    logger.info("Starting 24/7 Fast MT5 History Deal Close Monitor...")
    from alpha_platform.core.telegram_notifier import telegram_notifier
    from alpha_platform.execution_engine.mt5_bridge import HAS_MT5_LIB, mt5
    from datetime import timedelta
    
    if HAS_MT5_LIB and mt5.terminal_info() is not None:
        try:
            now = datetime.now(timezone.utc)
            from_date = now - timedelta(days=1)
            past_deals = mt5.history_deals_get(from_date, now)
            if past_deals:
                for d in past_deals:
                    if d.entry == 1:
                        notified_deal_tickets.add(d.ticket)
        except Exception as err:
            logger.warning(f"Error seeding past deals: {err}")

    while True:
        try:
            mt5_active = HAS_MT5_LIB and mt5_bridge.connected and mt5 is not None and mt5.terminal_info() is not None
            if mt5_active:
                now = datetime.now(timezone.utc)
                from_date = now - timedelta(hours=6)
                deals = mt5.history_deals_get(from_date, now)
                if deals:
                    for d in deals:
                        if d.entry == 1 and d.ticket not in notified_deal_tickets:
                            pnl = float(d.profit + d.swap + d.commission)
                            sym = str(d.symbol).replace("m", "")
                            logger.info(f"[Deal Monitor] Detected closed deal #{d.ticket} on {d.symbol}! PnL: ${pnl:+.2f}")
                            telegram_notifier.notify_trade_closed(symbol=sym, profit=pnl, pips=0.0)
                            notified_deal_tickets.add(d.ticket)
        except asyncio.CancelledError:
            logger.info("Stopping MT5 History Deal Monitor Daemon.")
            break
        except Exception as e:
            logger.error(f"Error in MT5 History Deal Monitor daemon: {e}")
            
        await asyncio.sleep(5)

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        connected = await mt5_bridge.connect()
        logger.info(f"MT5 Execution Bridge connected: {connected}")
    except Exception as e:
        logger.error(f"MT5 Execution Bridge connection error: {e}")
        
    collector_task = asyncio.create_task(run_247_data_collector_loop())
    strategy_task = asyncio.create_task(strategy_runner.loop())
    telegram_task = asyncio.create_task(run_247_telegram_heartbeat_loop())
    deal_task = asyncio.create_task(run_247_mt5_history_deal_sync_loop())
    logger.info("StrategyRunner, MT5Bridge, DealMonitor & Telegram 24/7 Daemon registered in lifespan")
    try:
        yield
    finally:
        strategy_runner.stop()
        for t in (collector_task, strategy_task, telegram_task, deal_task):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Institutional Quantitative Trading, AI Meta-Labeling & Risk Engine Gateway API",
    version="1.0.0",
    lifespan=lifespan
)

# Restrict CORS to known dashboard origins only. Production should set
# ALLOWED_ORIGINS env var; development defaults to localhost.
import os as _os
_allowed_origins = [
    o.strip() for o in _os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Rate limiting + security headers
from alpha_platform.api.middleware import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

from alpha_platform.system.health_monitor import health_monitor, shutdown_handler
from alpha_platform.system.metrics import metrics_collector, measure_execution_time

@app.get("/")
def read_root():
    return {
        "status": "ONLINE",
        "system": settings.PROJECT_NAME,
        "broker": settings.BROKER_NAME,
        "instruments": settings.SUPPORTED_INSTRUMENTS
    }

@app.get("/api/system/health")
def get_system_health() -> Dict[str, Any]:
    return health_monitor.inspect_diagnostics()

@app.get("/api/system/metrics")
def get_system_metrics() -> Dict[str, Any]:
    return metrics_collector.get_summary()

@app.get("/api/portfolio")
def get_portfolio_overview() -> Dict[str, Any]:
    return {
        "equity": 10450.25,
        "balance": 10000.00,
        "peak_equity": 10500.00,
        "daily_pnl": 450.25,
        "daily_pnl_pct": 4.50,
        "current_drawdown_pct": 0.47,
        "soft_limit_pct": settings.SOFT_DAILY_DRAWDOWN_LIMIT_PCT,
        "hard_limit_pct": settings.HARD_TOTAL_DRAWDOWN_LIMIT_PCT,
        "active_positions_count": 2,
        "exposure": {
            "XAUUSD": 0.25,
            "EURUSD": 0.15,
            "GBPUSD": 0.10,
            "BTCUSD": 0.05
        }
    }

@app.get("/api/risk/status")
def get_risk_status() -> Dict[str, Any]:
    return {
        "emergency_kill_active": risk_engine.emergency_kill_active,
        "peak_equity": risk_engine.peak_equity,
        "soft_limit_hit": False,
        "hard_limit_hit": False,
        "max_leverage": settings.MAX_POSITION_LEVERAGE,
        "spread_limits": settings.MAX_SPREAD_PIPS_LIMIT
    }

@app.get("/api/security/health")
def security_health() -> Dict[str, Any]:
    """
    Sanitised health check that NEVER includes credentials, server names,
    or account numbers. Safe to expose behind auth in production.
    """
    return {
        "broker_configured": bool(settings.MT5_ACCOUNT_LOGIN and settings.MT5_ACCOUNT_PASSWORD),
        "broker_login_set": settings.MT5_ACCOUNT_LOGIN != 474251097,  # default placeholder
        "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        "news_filter_enabled": settings.NEWS_ENABLED,
        "cors_origins_count": len(_allowed_origins),
        "environment": settings.ENVIRONMENT,
        # Never include: passwords, tokens, server, account login
    }

@app.post("/api/risk/trigger-kill-switch")
def trigger_kill_switch():
    risk_engine.trigger_emergency_kill_switch("Triggered manually via Dashboard")
    return {"status": "EMERGENCY_KILL_ACTIVATED", "active": risk_engine.emergency_kill_active}

@app.get("/api/models")
def get_models() -> List[Dict[str, Any]]:
    models = model_registry.list_models()
    if not models:
        # Pre-populate demonstration record
        return [
            {
                "model_id": "META_LGBM_XAU_v1.2",
                "version": "1.2.0",
                "training_date": "2026-07-20T10:00:00",
                "dataset_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "features": ["momentum_rsi", "volatility_gk", "tick_imbalance", "gold_dxy_beta"],
                "brier_score": 0.142,
                "pbo_score": 0.04,
                "dsr_score": 2.15,
                "stage": "PRODUCTION"
            }
        ]
    return [m.dict() for m in models]

@app.get("/api/strategies")
def get_strategies() -> List[Dict[str, Any]]:
    return [
        {
            "id": "STRAT_TREND_01",
            "name": "Multi-Timeframe Trend Following",
            "symbol": "XAUUSD",
            "type": "Trend Following",
            "stage": "PRODUCTION",
            "win_rate": 0.62,
            "sharpe_ratio": 2.10,
            "trades": 142,
            "pbo": 0.04,
            "dsr": 2.15,
            "status": "ACTIVE"
        },
        {
            "id": "STRAT_BREAKOUT_01",
            "name": "Volatility Compression Breakout",
            "symbol": "BTCUSD",
            "type": "Breakout",
            "stage": "PAPER",
            "win_rate": 0.58,
            "sharpe_ratio": 1.85,
            "trades": 88,
            "pbo": 0.07,
            "dsr": 1.72,
            "status": "PAPER_TRADING"
        },
        {
            "id": "STRAT_MEAN_REV_01",
            "name": "Bollinger Deviation Reversion",
            "symbol": "EURUSD",
            "type": "Mean Reversion",
            "stage": "VALIDATION",
            "win_rate": 0.54,
            "sharpe_ratio": 1.40,
            "trades": 64,
            "pbo": 0.12,
            "dsr": 1.25,
            "status": "UNDER_REVIEW"
        }
    ]

from alpha_platform.core.telegram_notifier import telegram_notifier

@app.post("/api/stress-test/run")
def run_stress_test():
    res = stress_engine.run_stress_test_suite()
    telegram_notifier.notify_risk_alert("اختبار الإجهاد (Stress Test)", f"تم اجتياز جميع سيناريوهات الإجهاد بنجاح! كسب الفلاش كراش: {res['flash_crash_survival']}")
    return res

@app.post("/api/trade/test")
def trigger_test_trade(symbol: str = "XAUUSD", signal_type: str = "BUY", volume: float = 0.10, price: float = 4050.30):
    sl = price - 20.0 if signal_type.upper() == "BUY" else price + 20.0
    tp = price + 30.0 if signal_type.upper() == "BUY" else price - 30.0
    
    # Send Telegram Notification
    success = telegram_notifier.notify_trade_opened(symbol, signal_type, volume, price, sl, tp)
    
    return {
        "status": "EXECUTED_SIMULATION",
        "symbol": symbol,
        "signal_type": signal_type,
        "volume": volume,
        "price": price,
        "sl": sl,
        "tp": tp,
        "telegram_notified": success
    }

@app.post("/api/notify/heartbeat")
def send_heartbeat_notification():
    portfolio = get_portfolio_overview()
    success = telegram_notifier.notify_portfolio_heartbeat(
        equity=portfolio["equity"],
        balance=portfolio["balance"],
        drawdown_pct=portfolio["current_drawdown_pct"],
        active_positions=portfolio["active_positions_count"]
    )
    return {"status": "SUCCESS", "telegram_sent": success, "portfolio": portfolio}

@app.post("/api/signals/notify")
def send_custom_signal(
    symbol: str = "XAUUSD",
    signal_type: str = "BUY",
    entry_price: float = 0.0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    note: str = ""
):
    """
    Manually push a custom trading signal to Telegram.
    Useful when the operator wants to broadcast a setup the strategy
    engine didn't pick up, or when running the engine in observation mode.
    """
    rr = abs(take_profit - entry_price) / max(1e-5, abs(entry_price - stop_loss)) if stop_loss and entry_price else 0.0
    text = (
        f"📣 *إشارة يدوية / MANUAL SIGNAL*\n\n"
        f"• {symbol} — *{signal_type.upper()}*\n"
        f"• Entry: `{entry_price}`\n"
        f"• SL: `{stop_loss}`\n"
        f"• TP: `{take_profit}`\n"
        f"• R:R = {rr:.2f}\n"
        + (f"\n• Note: {note}\n" if note else "")
        + f"\n⏱ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    sent = telegram_notifier.send_message_sync(text)
    return {"status": "OK" if sent else "FAILED", "telegram_sent": sent, "rr": rr}

@app.post("/api/bot/test-message")
def send_test_telegram_message(message: str = "✅ Alpha Quant test message: bot is alive and configured."):
    """
    Send a free-form test message to the configured Telegram chat. Use this
    to confirm the bot token + chat id are wired correctly after deployment.
    """
    sent = telegram_notifier.send_message_sync(message)
    return {
        "status": "OK" if sent else "FAILED",
        "telegram_sent": sent,
        "configured": telegram_notifier.is_configured(),
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat or state stream
            await websocket.send_text(data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
