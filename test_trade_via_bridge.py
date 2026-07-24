"""
Test via the platform's MT5ExecutionBridge (which calls Telegram).
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

PROJECT_ROOT = r"C:\Users\BASEEL PC\OneDrive\Desktop\تصميم الفا"
sys.path.insert(0, PROJECT_ROOT)

# Explicitly load .env with absolute path BEFORE any alpha_platform imports
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from alpha_platform.execution_engine.mt5_bridge import MT5ExecutionBridge
from alpha_platform.core.types import SignalType
from alpha_platform.core.telegram_notifier import telegram_notifier


async def main():
    print("=" * 60)
    print("OPEN + CLOSE TRADE VIA PLATFORM BRIDGE (with Telegram)")
    print("=" * 60)

    if not telegram_notifier.is_configured():
        print("[FAIL] Telegram notifier is not configured")
        return
    print(f"[OK] Telegram configured: chat_id={telegram_notifier.chat_id[:6]}...")

    bridge = MT5ExecutionBridge(allow_simulation=True)

    print("[...] Connecting to MT5...")
    connected = await bridge.connect()
    print(f"[{'OK' if connected else 'FAIL'}] Connect: {connected}")

    # Read current price
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick("XAUUSDm")
    entry = tick.ask
    sl = entry - 5.0
    tp = entry + 10.0

    print(f"\n[...] Sending BUY 0.01 XAUUSDm @ {entry:.4f}")
    print(f"      SL={sl:.4f}, TP={tp:.4f}")
    result = await bridge.send_order("XAUUSD", SignalType.BUY, 0.01, entry, sl, tp)
    print(f"[{'OK' if result['status'] == 'FILLED' else 'FAIL'}] Order result: {result}")

    if result["status"] == "FILLED":
        ticket = result["broker_ticket"]
        print(f"\n[...] Waiting 1.5s before closing ticket #{ticket}...")
        await asyncio.sleep(1.5)

        print(f"[...] Closing ticket #{ticket}...")
        close_result = await bridge.close_position(ticket)
        print(f"[{'OK' if 'CLOSED' in close_result['status'] else 'FAIL'}] Close result: {close_result}")

    print()
    print("=" * 60)
    print("CHECK YOUR TELEGRAM - you should have received 2 alerts")
    print("=" * 60)

    mt5.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
