import asyncio
import os
import sys
from datetime import datetime, timezone
from alpha_platform.config.logging_config import logger
from alpha_platform.api.app import strategy_runner, mt5_bridge, ts_store, seed_historical_bars_if_needed

async def bot_console_loop():
    print("="*60)
    print("🚀 ALPHA QUANT TRADING BOT - LIVE CONSOLE")
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. Initialize
    print("[1/3] Connecting to MT5 Bridge...")
    connected = await mt5_bridge.connect()
    if connected:
        print("✅ MT5 Connected Successfully!")
    else:
        print("⚠️ MT5 Connection Failed. Running in SIMULATION MODE.")
    
    print("[2/3] Seeding historical data...")
    seed_historical_bars_if_needed()
    
    print("[3/3] Starting Strategy Engine...")
    print("="*60)
    print("📡 BOT IS NOW ACTIVE & MONITORING MARKETS...")
    print("Press Ctrl+C to stop the bot.")
    print("="*60)
    
    # 2. Run the main loop
    try:
        # FORCE SIMULATION MODE for terminal testing
        print("[!] FORCING SIMULATION MODE: The bot will generate signals even if markets are closed.")
        mt5_bridge.allow_simulation = True
        # Monkey-patch is_market_open to always return True for testing
        async def mock_is_market_open(symbol): return True
        mt5_bridge.is_market_open = mock_is_market_open
        
        # Start the background data collector as well
        from alpha_platform.api.app import run_247_data_collector_loop
        asyncio.create_task(run_247_data_collector_loop())
        
        # Run the strategy runner loop
        await strategy_runner.loop()
    except KeyboardInterrupt:
        print("\n[!] Stopping bot...")
    except Exception as e:
        print(f"\n[❌] CRITICAL ERROR: {e}")
    finally:
        strategy_runner.stop()
        print("="*60)
        print("🛑 BOT SHUTDOWN COMPLETE.")
        print("="*60)

if __name__ == "__main__":
    try:
        asyncio.run(bot_console_loop())
    except KeyboardInterrupt:
        pass
