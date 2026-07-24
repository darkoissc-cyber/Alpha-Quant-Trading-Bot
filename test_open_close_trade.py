"""
Test script: Open and immediately close a 0.01 XAUUSD BUY trade on MT5.
Uses the connected Exness-MT5Trial15 Demo account.
"""
import MetaTrader5 as mt5
import time

B = "[OK]"
X = "[FAIL]"
W = "[WARN]"

# Initialize MT5 (uses credentials from the running MT5 terminal)
print("=" * 60)
print("ALPHA QUANT - TEST OPEN & CLOSE TRADE")
print("=" * 60)

if not mt5.initialize():
    print(f"{X} MT5 initialize() failed: {mt5.last_error()}")
    raise SystemExit(1)

print(f"{B} MT5 initialized successfully")
print(f"   Terminal: {mt5.terminal_info().name}")
print(f"   Connected: {mt5.terminal_info().connected}")

# Get account info
account_info = mt5.account_info()
if account_info is None:
    print(f"{X} Failed to get account info: {mt5.last_error()}")
    mt5.shutdown()
    raise SystemExit(1)

print("")
print("ACCOUNT INFO:")
print(f"   Login: {account_info.login}")
print(f"   Server: {account_info.server}")
print(f"   Balance: ${account_info.balance:.2f}")
print(f"   Equity: ${account_info.equity:.2f}")
print(f"   Margin Free: ${account_info.margin_free:.2f}")

# Resolve symbol (XAUUSDm for Exness)
symbol = "XAUUSDm"
symbol_info = mt5.symbol_info(symbol)
if symbol_info is None:
    print(f"{X} Symbol {symbol} not found. Trying alternatives...")
    for alt in ["XAUUSD", "XAUUSD.", "XAUUSDm"]:
        if mt5.symbol_info(alt) is not None:
            symbol = alt
            symbol_info = mt5.symbol_info(symbol)
            print(f"   {B} Found: {symbol}")
            break
    else:
        print(f"{X} Could not find XAUUSD variant")
        mt5.shutdown()
        raise SystemExit(1)

# Make sure symbol is visible
if not symbol_info.visible:
    if not mt5.symbol_select(symbol, True):
        print(f"{X} Failed to select {symbol}")
        mt5.shutdown()
        raise SystemExit(1)

tick = mt5.symbol_info_tick(symbol)
print("")
print(f"PRICE ({symbol}):")
print(f"   Bid: {tick.bid:.4f}")
print(f"   Ask: {tick.ask:.4f}")
print(f"   Spread: {(tick.ask - tick.bid):.4f}")

# Get current price and compute SL/TP
entry_price = tick.ask
sl_price = entry_price - 5.0  # SL 5 USD below entry
tp_price = entry_price + 10.0  # TP 10 USD above entry
volume = 0.01

print("")
print("TRADE PLAN (BUY 0.01 lot):")
print(f"   Entry (Ask): {entry_price:.4f}")
print(f"   Stop Loss:   {sl_price:.4f}")
print(f"   Take Profit: {tp_price:.4f}")

# Build order request
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": volume,
    "type": mt5.ORDER_TYPE_BUY,
    "price": entry_price,
    "sl": sl_price,
    "tp": tp_price,
    "deviation": 20,
    "magic": 777999,
    "comment": "Alpha Quant test_open_close",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

# Send order
print("")
print("SENDING BUY ORDER...")
result = mt5.order_send(request)

if result is None:
    print(f"{X} order_send() returned None: {mt5.last_error()}")
    mt5.shutdown()
    raise SystemExit(1)

print("")
print("ORDER RESULT:")
print(f"   Retcode: {result.retcode}")
print(f"   Order ticket: {result.order}")
print(f"   Volume: {result.volume}")
print(f"   Price: {result.price}")
print(f"   Comment: {result.comment}")

if result.retcode != mt5.TRADE_RETCODE_DONE:
    print(f"{X} Order FAILED: {result.comment}")
    mt5.shutdown()
    raise SystemExit(1)

print(f"{B} Order FILLED! Ticket #{result.order}")
ticket = result.order

# Wait a moment so the position is registered
time.sleep(1.0)

# Verify position exists
positions = mt5.positions_get(ticket=ticket)
if not positions:
    print(f"{W} Position not found by ticket, scanning all positions...")
    positions = mt5.positions_get(symbol=symbol)

if not positions:
    print(f"{X} No open position found after order fill")
    mt5.shutdown()
    raise SystemExit(1)

pos = positions[0]
print("")
print("ACTIVE POSITION CONFIRMED:")
print(f"   Ticket: {pos.ticket}")
print(f"   Symbol: {pos.symbol}")
print(f"   Volume: {pos.volume}")
print(f"   Open price: {pos.price_open}")
print(f"   Current profit: ${pos.profit:.2f}")

# Build close request
close_tick = mt5.symbol_info_tick(pos.symbol)
close_price = close_tick.bid if pos.type == mt5.ORDER_TYPE_BUY else close_tick.ask

close_request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "position": pos.ticket,
    "symbol": pos.symbol,
    "volume": pos.volume,
    "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
    "price": close_price,
    "deviation": 20,
    "magic": 777999,
    "comment": "Alpha Quant test_close",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

print("")
print(f"CLOSING POSITION #{ticket}...")
close_result = mt5.order_send(close_request)

if close_result is None:
    print(f"{X} Close order_send() returned None: {mt5.last_error()}")
    mt5.shutdown()
    raise SystemExit(1)

print("")
print("CLOSE RESULT:")
print(f"   Retcode: {close_result.retcode}")
print(f"   Price: {close_result.price}")
print(f"   Comment: {close_result.comment}")

if close_result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"{B} Position CLOSED successfully!")
else:
    print(f"{X} Close FAILED: {close_result.comment}")

# Final account state
time.sleep(0.5)
final = mt5.account_info()
if final:
    print("")
    print("FINAL ACCOUNT STATE:")
    print(f"   Balance: ${final.balance:.2f}")
    print(f"   Equity:  ${final.equity:.2f}")
    delta = final.balance - account_info.balance
    print(f"   Profit Delta: ${delta:+.2f}")

mt5.shutdown()
print("")
print("=" * 60)
print("DONE - Trade opened and closed.")
print("=" * 60)
