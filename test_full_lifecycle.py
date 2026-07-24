"""
Full lifecycle test: OPEN -> MODIFY SL/TP -> CLOSE
Each step sends a Telegram alert.
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
    print("FULL LIFECYCLE TEST: OPEN -> MODIFY -> CLOSE")
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

    # =========================================================
    # STEP 1: OPEN
    # =========================================================
    print(f"\n{'='*60}")
    print(f"STEP 1: OPEN BUY 0.01 XAUUSDm @ {entry:.4f}")
    print(f"        SL={sl:.4f} | TP={tp:.4f}")
    print(f"{'='*60}")
    result = await bridge.send_order("XAUUSD", SignalType.BUY, 0.01, entry, sl, tp)
    print(f"[{'OK' if result['status'] == 'FILLED' else 'FAIL'}] Open result: {result}")

    if result["status"] != "FILLED":
        print("[FAIL] Cannot continue without filled order")
        mt5.shutdown()
        return

    ticket = result["broker_ticket"]
    print(f"\n[OK] Trade #{ticket} opened at {result['fill_price']:.4f}")

    # Wait a moment
    await asyncio.sleep(2.0)

    # =========================================================
    # STEP 2: MODIFY SL/TP (move closer to break-even)
    # =========================================================
    new_sl = entry - 1.0  # tighter SL
    new_tp = entry + 5.0  # tighter TP
    print(f"\n{'='*60}")
    print(f"STEP 2: MODIFY SL/TP for trade #{ticket}")
    print(f"        New SL={new_sl:.4f} (was {sl:.4f})")
    print(f"        New TP={new_tp:.4f} (was {tp:.4f})")
    print(f"{'='*60}")
    modify_result = await bridge.modify_order_sltp(ticket, new_sl, new_tp)
    print(f"[{'OK' if modify_result['status'] == 'MODIFIED' else 'FAIL'}] Modify result: {modify_result}")

    # Wait
    await asyncio.sleep(2.0)

    # =========================================================
    # STEP 3: CLOSE
    # =========================================================
    print(f"\n{'='*60}")
    print(f"STEP 3: CLOSE trade #{ticket}")
    print(f"{'='*60}")
    close_result = await bridge.close_position(ticket)
    print(f"[{'OK' if 'CLOSED' in close_result['status'] else 'FAIL'}] Close result: {close_result}")

    # Final account state
    import time
    time.sleep(0.5)
    acc = mt5.account_info()
    if acc:
        print(f"\n{'='*60}")
        print(f"FINAL ACCOUNT STATE:")
        print(f"   Balance: ${acc.balance:.2f}")
        print(f"   Equity:  ${acc.equity:.2f}")
        print(f"   Margin Free: ${acc.margin_free:.2f}")
        print(f"{'='*60}")

    print()
    print("=" * 60)
    print("CHECK YOUR TELEGRAM - you should have received 2 alerts:")
    print("  1. [GREEN] New Trade Alert (open)")
    print("  2. [MONEY] Trade Closed (with P/L)")
    print()
    print("Note: MODIFY does NOT send Telegram in current code")
    print("=" * 60)

    mt5.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
