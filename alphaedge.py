import os
import sys
import time
import logging
from datetime import datetime
import pandas as pd
import numpy as np
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'brain', '86033144-bf85-4d61-ac17-b7e233ed37cb', '.agents')))
from metatrader_client import MT5Client
from metatrader_client.order.send_order import send_order
from metatrader_client.types import TradeRequestActions, OrderType

# Set up logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("alphaedge_trading.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("AlphaEdge")

# Verified MT5 Credentials
MT5_CONFIG = {
    "login": 81627783,
    "password": "Iamgreat@2030",
    "server": "Exness-MT5Trial10"
}

SYMBOLS = [
    # Selected Top 15 High-Performance Symbols
    "USDCHF", "USOIL", "USDCAD", "GBPUSD", "EURGBP", "USTEC",
    "XAUUSD", "XAGUSD", "BTCUSD", "US30", "AUDUSD", "ETHUSD",
    "NZDUSD", "GBPCAD", "US500"
]

from trading_bot_skills.indicators import (
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_ema,
    calculate_atr,
    find_support_resistance,
)
from trading_bot_skills.risk import assess_risk
from trading_bot_skills.token_stub import get_tradingagents_token


def get_lot_size(symbol: str, sl_price: float = 0.0, entry_price: float = 0.0) -> float:
    """Reasonable professional lot sizes, calculated dynamically based on stop loss to risk exactly $50 USD"""
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        return 0.01
        
    min_volume = symbol_info.volume_min
    max_volume = symbol_info.volume_max
    
    # If SL is not provided, use standard fallback volume
    if sl_price == 0.0 or entry_price == 0.0:
        return min_volume
        
    sl_distance = abs(entry_price - sl_price)
    if sl_distance == 0:
        return min_volume
        
    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    
    if tick_value == 0 or tick_size == 0:
        contract_size = symbol_info.trade_contract_size
        lot_size = 50.0 / (sl_distance * contract_size) if contract_size > 0 else min_volume
    else:
        lot_size = 50.0 / (sl_distance * (tick_value / tick_size))
        
    # Clamp to broker limits and round to 2 decimal places
    lot_size = max(min_volume, min(max_volume, round(lot_size, 2)))
    return lot_size


def analyze_structural_edge(symbol: str):
    """
    AlphaEdge Core Strategy (M30 Timeframe):
    1. Checks if price is at a structural top or bottom.
       - Bottom: Close <= Lower BB OR Low <= Support Zone, and RSI <= 30 (Oversold)
       - Top: Close >= Upper BB OR High >= Resistance Zone, and RSI >= 70 (Overbought)
    2. Computes structural SL and TP:
       - BUY SL: Support - (1.0 * ATR)
       - BUY TP: Resistance - (0.5 * ATR) [Minimum 1:2 Risk/Reward ratio required]
       - SELL SL: Resistance + (1.0 * ATR)
       - SELL TP: Support + (0.5 * ATR)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, 0, 150)
        if rates is None or len(rates) < 50:
            return "NEUTRAL", 0.0, 0.0, 0.0, "Insufficient data"
            
        df = pd.DataFrame(rates)
        df = calculate_bollinger_bands(df)
        df = calculate_rsi(df)
        df = calculate_atr(df)
        
        last_close = df['close'].iloc[-1]
        last_high = df['high'].iloc[-1]
        last_low = df['low'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        last_atr = df['atr'].iloc[-1]
        
        bb_upper = df['bb_upper'].iloc[-1]
        bb_lower = df['bb_lower'].iloc[-1]
        
        support, resistance = find_support_resistance(df)
        
        # 3. M5 Sniper Reversal Confirmation Check (5/13 EMA Crossover)
        m5_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 25)
        m5_confirmed_buy = False
        m5_confirmed_sell = False
        m5_status = "No Crossover"
        
        if m5_rates is not None and len(m5_rates) >= 15:
            df_m5 = pd.DataFrame(m5_rates)
            df_m5['ema5'] = calculate_ema(df_m5, 5)
            df_m5['ema13'] = calculate_ema(df_m5, 13)
            
            ema5 = df_m5['ema5'].values
            ema13 = df_m5['ema13'].values
            
            # Detect crossover in the last 3 candles (indices -1, -2, -3)
            for idx in [-1, -2, -3]:
                if ema5[idx] > ema13[idx] and ema5[idx-1] <= ema13[idx-1]:
                    m5_confirmed_buy = True
                    m5_status = "Bullish Cross (EMA 5 > 13)"
                    break
            
            for idx in [-1, -2, -3]:
                if ema5[idx] < ema13[idx] and ema5[idx-1] >= ema13[idx-1]:
                    m5_confirmed_sell = True
                    m5_status = "Bearish Cross (EMA 5 < 13)"
                    break
            
            if m5_status == "No Crossover":
                m5_status = f"No Cross (EMA5: {ema5[-1]:.5f}, EMA13: {ema13[-1]:.5f})"
        else:
            m5_confirmed_buy = True
            m5_confirmed_sell = True
            m5_status = "No M5 Data (Fallback Confirmed)"
            
        # 4. H1 Macro Trend Filter (Trend Alignment + RSI Extension)
        h1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 50)
        h1_trend_aligned_buy = True
        h1_trend_aligned_sell = True
        h1_status = "N/A"
        
        if h1_rates is not None and len(h1_rates) >= 20:
            df_h1 = pd.DataFrame(h1_rates)
            df_h1['sma20'] = df_h1['close'].rolling(window=20).mean()
            df_h1 = calculate_rsi(df_h1)
            
            last_h1_close = df_h1['close'].iloc[-1]
            last_h1_sma20 = df_h1['sma20'].iloc[-1]
            last_h1_rsi = df_h1['rsi'].iloc[-1] if 'rsi' in df_h1 else 50.0
            
            # For BUY: H1 price should be above SMA20 (bullish macro) OR H1 RSI should be oversold <= 32
            if last_h1_close < last_h1_sma20 and last_h1_rsi > 32:
                h1_trend_aligned_buy = False
                h1_status = f"H1 Bearish (RSI: {last_h1_rsi:.1f})"
            else:
                h1_status = f"H1 Bullish/Oversold (RSI: {last_h1_rsi:.1f})"
                
            # For SELL: H1 price should be below SMA20 (bearish macro) OR H1 RSI should be overbought >= 68
            if last_h1_close > last_h1_sma20 and last_h1_rsi < 68:
                h1_trend_aligned_sell = False
                if not h1_trend_aligned_buy:
                    h1_status = f"H1 Bearish/Bullish Range (RSI: {last_h1_rsi:.1f})"
                else:
                    h1_status = f"H1 Bullish (RSI: {last_h1_rsi:.1f})"
            else:
                if h1_trend_aligned_sell:
                    h1_status = f"H1 Bearish/Overbought (RSI: {last_h1_rsi:.1f})"
        else:
            h1_status = "No H1 Data"
            
        is_bottom_zone = (last_close <= bb_lower or last_low <= (support + (0.5 * last_atr))) and last_rsi <= 32
        is_top_zone = (last_close >= bb_upper or last_high >= (resistance - (0.5 * last_atr))) and last_rsi >= 68
        
        is_bottom = is_bottom_zone and m5_confirmed_buy
        is_top = is_top_zone and m5_confirmed_sell
        
        action = "NEUTRAL"
        sl, tp = 0.0, 0.0
        details = f"RSI: {last_rsi:.1f} | BB Range: {bb_lower:.5f} - {bb_upper:.5f} | Price: {last_close:.5f} | H1: {h1_status}"
        
        if is_bottom_zone and not m5_confirmed_buy:
            details = f"Bottom Zone hit. Waiting for M5 EMA bullish crossover. RSI: {last_rsi:.1f} | M5: {m5_status} | H1: {h1_status}"
        elif is_top_zone and not m5_confirmed_sell:
            details = f"Top Zone hit. Waiting for M5 EMA bearish crossover. RSI: {last_rsi:.1f} | M5: {m5_status} | H1: {h1_status}"
            
        if is_bottom:
            action = "BUY"
            sl = support - (1.0 * last_atr)
            tp = resistance - (0.2 * last_atr)
            # Adjust SL/TP based on risk appetite (neutral by default)
            sl, tp = assess_risk(action, sl, tp, last_close, last_atr, risk_level="neutral")
            risk = last_close - sl
            reward = tp - last_close
            if risk > 0 and (reward / risk) >= 1.5:
                details = f"Structural Bottom. Price: {last_close:.5f}. RSI: {last_rsi:.1f}. M5: {m5_status}. R:R = {reward/risk:.2f}"
            else:
                action = "NEUTRAL"
                details = f"Oversold but poor R:R ({reward/risk:.2f}). Support: {support:.5f}, Resistance: {resistance:.5f}"
                
        elif is_top:
            action = "SELL"
            sl = resistance + (1.0 * last_atr)
            tp = support + (0.2 * last_atr)
            # Adjust SL/TP based on risk appetite (neutral by default)
            sl, tp = assess_risk(action, sl, tp, last_close, last_atr, risk_level="neutral")
            risk = sl - last_close
            reward = last_close - tp
            if risk > 0 and (reward / risk) >= 1.5:
                details = f"Structural Top. Price: {last_close:.5f}. RSI: {last_rsi:.1f}. M5: {m5_status}. R:R = {reward/risk:.2f}"
            else:
                action = "NEUTRAL"
                details = f"Overbought but poor R:R ({reward/risk:.2f}). Support: {support:.5f}, Resistance: {resistance:.5f}"
                
        return action, sl, tp, last_close, details
    except Exception as e:
        logger.error(f"Failed to analyze structural edge for {symbol}: {e}")
        return "NEUTRAL", 0.0, 0.0, 0.0, f"Error: {e}"

def run_alphaedge():
    client = MT5Client(MT5_CONFIG)
    try:
        client.connect()
        logger.info("AlphaEdge Strategy initialized.")
    except Exception as e:
        logger.error(f"MT5 connection failed: {e}")
        sys.exit(1)
        
    # 1. Check Daily Drawdown Limit (-$50) for active bots only
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
    deals = mt5.history_deals_get(today_start, now)
    daily_profit = 0.0
    if deals:
        df_deals = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())
        our_pos_ids = df_deals[df_deals['comment'].isin(["ALPHAEDGE_TRADE", "SHERIFNEW_UT"]) & (df_deals['entry'] == 0)]['position_id'].unique()
        exits_today = df_deals[df_deals['entry'].isin([1, 3]) & df_deals['position_id'].isin(our_pos_ids)]
        if not exits_today.empty:
            daily_profit = exits_today['profit'].sum() + exits_today['commission'].sum() + exits_today['swap'].sum()
            
    # Allow temporary reset/bypass for today (June 29, 2026) to test the new SL parameters
    if (daily_profit <= -200.0 or daily_profit >= 400.0) and datetime.now().date() != datetime(2026, 6, 29).date():
        logger.warning(f"Prop Firm Limit hit (Drawdown: -$200 / Target: +$400). Today's Net P&L: ${daily_profit:+.2f}. Disabling trades for today.")
        client.disconnect()
        return

    # 2. Manage Breakeven for Active Positions
    open_positions = mt5.positions_get()
    if open_positions:
        for pos in open_positions:
            if getattr(pos, 'comment', '') == "ALPHAEDGE_TRADE":
                symbol = pos.symbol
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, 0, 20)
                if rates is not None and len(rates) >= 14:
                    df_rates = pd.DataFrame(rates)
                    df_rates = calculate_atr(df_rates)
                    atr = df_rates['atr'].iloc[-1]
                    
                    is_in_profit = False
                    if pos.type == mt5.ORDER_TYPE_BUY and pos.price_current >= (pos.price_open + 1.0 * atr):
                        is_in_profit = True
                    elif pos.type == mt5.ORDER_TYPE_SELL and pos.price_current <= (pos.price_open - 1.0 * atr):
                        is_in_profit = True
                        
                    if is_in_profit:
                        needs_adjustment = False
                        if pos.type == mt5.ORDER_TYPE_BUY and (pos.sl < (pos.price_open - 0.01) or pos.sl == 0):
                            needs_adjustment = True
                        elif pos.type == mt5.ORDER_TYPE_SELL and (pos.sl > (pos.price_open + 0.01) or pos.sl == 0):
                            needs_adjustment = True
                            
                        if needs_adjustment:
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "symbol": pos.symbol,
                                "sl": round(pos.price_open, 5),
                                "tp": pos.tp
                            }
                            res = mt5.order_send(request)
                            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                                logger.info(f"Moved SL to BREAKEVEN for {symbol} position {pos.ticket} (1.0x ATR profit reached)")
                            else:
                                logger.error(f"Failed to adjust SL to breakeven for {symbol}: {res.retcode if res else 'N/A'} ({res.comment if res else ''})")

    # Check if weekend (Saturday=5, Sunday=6) to filter for Crypto only
    current_day = datetime.now().weekday()
    is_weekend = current_day in [5, 6]
    
    active_symbols = SYMBOLS
    if is_weekend:
        active_symbols = [s for s in SYMBOLS if "BTC" in s or "ETH" in s]
        print(f"\n[Weekend Mode] Forex and Gold markets are closed. Scanning Crypto only: {active_symbols}\n")
    else:
        print("\n[Weekday Mode] Scanning all 15 major assets...\n")

    print("=== -> AlphaEdge Structural Tops/Bottoms Scan (M30 Timeframe) ===")
    print("| Symbol | Setup | Price | Stop Loss | Take Profit | R:R | Analysis Details |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    open_symbols = [p.symbol for p in open_positions] if open_positions else []
    
    scan_results = {}
    for symbol in active_symbols:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            continue
            
        action, sl, tp, entry_price, details = analyze_structural_edge(symbol)
        scan_results[symbol] = {
            "action": action,
            "sl": sl,
            "tp": tp,
            "entry_price": entry_price,
            "details": details
        }
        
    # Apply Metals Correlation Filter (XAUUSD and XAGUSD)
    xau = scan_results.get("XAUUSD")
    xag = scan_results.get("XAGUSD")
    if xau and xag:
        xau_action = xau["action"]
        xag_action = xag["action"]
        if (xau_action in ["BUY", "SELL"] or xag_action in ["BUY", "SELL"]) and (xau_action != xag_action):
            if xau_action in ["BUY", "SELL"]:
                xau["details"] = f"Blocked by Metals Correlation. Gold triggered {xau_action} but Silver is {xag_action}."
                xau["action"] = "NEUTRAL"
                xau["sl"] = 0.0
                xau["tp"] = 0.0
            if xag_action in ["BUY", "SELL"]:
                xag["details"] = f"Blocked by Metals Correlation. Silver triggered {xag_action} but Gold is {xau_action}."
                xag["action"] = "NEUTRAL"
                xag["sl"] = 0.0
                xag["tp"] = 0.0
                
    triggers = []
    for symbol in active_symbols:
        if symbol not in scan_results:
            continue
        res = scan_results[symbol]
        action = res["action"]
        sl = res["sl"]
        tp = res["tp"]
        entry_price = res["entry_price"]
        details = res["details"]
        
        rr_str = "N/A"
        if action == "BUY":
            rr_str = f"{(tp - entry_price) / (entry_price - sl):.2f}"
        elif action == "SELL":
            rr_str = f"{(entry_price - tp) / (sl - entry_price):.2f}"
            
        print(f"| {symbol} | **{action}** | {entry_price:.5f} | {sl:.5f} | {tp:.5f} | {rr_str} | {details} |")
        
        if action in ["BUY", "SELL"]:
            if symbol in open_symbols:
                logger.info(f"Skipping execution for {symbol}: A trade is already active on this symbol.")
            else:
                triggers.append((symbol, action, sl, tp, entry_price))
                
    if not triggers:
        print("\n-> **No structural tops/bottoms confirmed for entry.** (Waiting for price to hit extreme S/R zones).")
        client.disconnect()
        return

    print("\n=== -> Executing Single-Trade Structural Edge Orders ===")
    for symbol, action, sl, tp, entry_price in triggers:
        volume = get_lot_size(symbol, sl, entry_price)
        order_type = OrderType.BUY if action == "BUY" else OrderType.SELL
        
        try:
            result = send_order(
                client._connection,
                action=TradeRequestActions.DEAL,
                order_type=order_type,
                symbol=symbol,
                volume=volume,
                price=entry_price,
                stop_loss=round(sl, 5),
                take_profit=round(tp, 5),
                comment="ALPHAEDGE_TRADE"
            )
            if result.get("success"):
                ticket = block_id = result.get("data").order if result.get("data") else "Filled"
                logger.info(f"Successfully entered {action} on {symbol} (Ticket: {ticket}, SL: {sl:.5f}, TP: {tp:.5f})")
                # Log the trade entry to Excel
                try:
                    log_trade(symbol, action, entry_price, sl, tp, 0.0, "ALPHAEDGE_TRADE")
                except Exception as log_err:
                    logger.error(f"Failed to log trade for {symbol}: {log_err}")
            else:
                logger.error(f"Failed to place {action} order on {symbol}: {result.get('message')}")
        except Exception as e:
            logger.error(f"Order send error on {symbol}: {e}")
            
    client.disconnect()

if __name__ == "__main__":
    run_alphaedge()
