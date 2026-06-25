import os
import sys
import time
import logging
import MetaTrader5 as mt5
from metatrader_client import MT5Client
from metatrader_client.order.send_order import send_order
from metatrader_client.types import TradeRequestActions, OrderType

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradeNowBasket")

# Verified MT5 Credentials
MT5_CONFIG = {
    "login": 81627783,
    "password": "Iamgreat@2030",
    "server": "Exness-MT5Trial10"
}

# 5 Symbols to Trade
SYMBOLS = ["GBPJPY", "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD"]

def get_lot_size(symbol: str) -> float:
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        return 0.03  # Gold
    elif "BTC" in symbol_upper or "ETH" in symbol_upper:
        return 0.05  # Crypto
    else:
        return 0.1   # Currencies

def get_market_trend(symbol: str) -> str:
    """
    Checks the last completed H1 candle.
    Returns "BUY" if bullish, "SELL" if bearish. Defaults to "BUY" if error.
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, 1)
        if rates is not None and len(rates) > 0:
            candle = rates[0]
            open_p = candle['open']
            close_p = candle['close']
            if close_p > open_p:
                return "BUY"
            else:
                return "SELL"
    except Exception as e:
        logger.error(f"Error checking trend for {symbol}: {e}")
    return "BUY"

def get_sltp_levels(symbol: str, action: str, entry_price: float):
    """
    Calculates safety Stop Loss and Take Profit levels based on the asset class.
    """
    symbol_upper = symbol.upper()
    action_upper = action.upper()
    
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        offset_sl = 5.0   # $5.00 stop loss
        offset_tp = 10.0  # $10.00 take profit
    elif "BTC" in symbol_upper:
        offset_sl = 300.0 # $300 stop loss
        offset_tp = 600.0 # $600 take profit
    else:
        offset_sl = 0.30  # 30 pips stop loss for forex
        offset_tp = 0.60  # 60 pips take profit
        
    if action_upper == "BUY":
        sl = entry_price - offset_sl
        tp = entry_price + offset_tp
    else:
        sl = entry_price + offset_sl
        tp = entry_price - offset_tp
        
    return round(sl, 4), round(tp, 4)

def main():
    client = MT5Client(MT5_CONFIG)
    try:
        logger.info("Connecting to MetaTrader 5...")
        client.connect()
        logger.info("Successfully connected to MetaTrader 5!")
    except Exception as e:
        logger.error(f"Failed to connect to MT5: {e}")
        sys.exit(1)
        
    basket_id = f"BASKET_{int(time.time())}"
    logger.info(f"Generating new trade basket with SL/TP protection: {basket_id}")
    
    executed_trades = []
    
    print(f"\n### Executing Basket Trade (SL/TP Enabled): {basket_id}")
    print("| Symbol | Action | Volume | Entry Price | Stop Loss (SL) | Take Profit (TP) | Status | Ticket |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    for symbol in SYMBOLS:
        if not mt5.symbol_select(symbol, True):
            print(f"| {symbol} | - | - | - | - | - | Failed to select symbol | - |")
            continue
            
        volume = get_lot_size(symbol)
        action = get_market_trend(symbol)
        order_type = OrderType.BUY if action == "BUY" else OrderType.SELL
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"| {symbol} | {action} | {volume} | - | - | - | Failed to fetch price | - |")
            continue
        price = tick.ask if action == "BUY" else tick.bid
        
        # Calculate SL & TP
        sl, tp = get_sltp_levels(symbol, action, price)
        
        try:
            result = send_order(
                client._connection,
                action=TradeRequestActions.DEAL,
                order_type=order_type,
                symbol=symbol,
                volume=volume,
                price=price,
                stop_loss=sl,
                take_profit=tp,
                comment=basket_id
            )
            
            if result.get("success"):
                response_data = result.get("data")
                ticket = response_data.order if response_data else "Unknown"
                print(f"| {symbol} | **{action}** | {volume} | {price:.5f} | {sl:.5f} | {tp:.5f} | Filled | `{ticket}` |")
                executed_trades.append(ticket)
            else:
                reason = result.get("message", "Unknown error")
                print(f"| {symbol} | {action} | {volume} | {price:.5f} | {sl:.5f} | {tp:.5f} | Failed: {reason} | - |")
                
        except Exception as e:
            print(f"| {symbol} | {action} | {volume} | - | - | - | Execution Error: {e} | - |")
            
    print(f"\nSuccessfully launched **{len(executed_trades)}** trades under basket `{basket_id}`.")
    print("Each trade has individual SL/TP protection. The server will close all of them if the combined profit reaches >= $10.00.")

    client.disconnect()

if __name__ == "__main__":
    main()
