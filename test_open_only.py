"""
Open a 0.01 XAUUSD BUY trade and LEAVE IT OPEN.
Verifies Telegram notification fires.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

PROJECT_ROOT = r"C:\Users\BASEEL PC\OneDrive\Desktop\تصميم الفا"
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from alpha_platform.execution_engine.mt5_bridge import MT5ExecutionBridge
from alpha_platform.core.types import SignalType
from alpha_platform.core.telegram_notifier import telegram_notifier


async def main():
    print("=" * 60)
    print("OPEN TRADE (LEAVE OPEN) + TELEGRAM ALERT")
    print("=" * 60)

    if not telegram_notifier.is_configured():
        print("[FAIL] Telegram not configured")
        return
    print(f"[OK] Telegram: chat_id={telegram_notifier.chat_id[:6]}...")

    bridge = MT5ExecutionBridge(allow_simulation=True)
    print("[...] Connecting to MT5...")
    connected = await bridge.connect()
    print(f"[{'OK' if connected else 'FAIL'}] Connected")

    if not connected:
        return

    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick("XAUUSDm")
    if tick is None:
        print("[FAIL] No tick for XAUUSDm")
        mt5.shutdown()
        return

    entry = tick.ask
    sl = entry - 5.0
    tp = entry + 10.0

    print(f"\n[PLAN] BUY 0.01 XAUUSDm @ {entry:.4f}")
    print(f"       SL={sl:.4f} | TP={tp:.4f}")

    result = await bridge.send_order("XAUUSD", SignalType.BUY, 0.01, entry, sl, tp)
    print(f"\n[{'OK' if result['status'] == 'FILLED' else 'FAIL'}] Result: {result}")

    if result["status"] == "FILLED":
        ticket = result["broker_ticket"]
        print(f"\n[OK] Trade #{ticket} OPEN and will stay open")
        print(f"     Open it in your MT5 to verify")

    print()
    print("=" * 60)
    print("CHECK TELEGRAM - alert: 'New Trade Alert' (green icon)")
    print("=" * 60)

    mt5.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
