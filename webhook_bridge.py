import os
import re
import json
import logging
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from metatrader_client import MT5Client
from metatrader_client.order.send_order import send_order
from metatrader_client.types import TradeRequestActions, OrderType

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingViewBridge")

app = FastAPI(title="TradingView MetaTrader 5 Webhook Bridge")

# Verified MT5 Credentials
MT5_CONFIG = {
    "login": 81627783,
    "password": "Iamgreat@2030",
    "server": "Exness-MT5Trial10"
}

# Default trade volume if not specified in signal
DEFAULT_VOLUME = 0.05

client = MT5Client(MT5_CONFIG)

@app.on_event("startup")
def startup_event():
    try:
        logger.info("Connecting to MetaTrader 5...")
        client.connect()
        logger.info("Successfully connected to MetaTrader 5 terminal!")
    except Exception as e:
        logger.error(f"Failed to connect to MT5 during startup: {e}")

@app.on_event("shutdown")
def shutdown_event():
    try:
        logger.info("Disconnecting from MetaTrader 5...")
        client.disconnect()
        logger.info("Disconnected.")
    except Exception as e:
        logger.error(f"Error during disconnect: {e}")

def clean_symbol(symbol_str: str) -> str:
    if ":" in symbol_str:
        symbol_str = symbol_str.split(":")[-1]
    return symbol_str.upper().strip()

def parse_plain_text_signal(text: str):
    logger.info(f"Attempting to parse plain text signal: {text}")
    
    action = None
    if "BUY" in text.upper():
        action = "BUY"
    elif "SELL" in text.upper():
        action = "SELL"
        
    if not action:
        return None
        
    symbol = None
    parts = [p.strip() for p in text.split("|")]
    if len(parts) >= 3:
        symbol = clean_symbol(parts[2])
    else:
        match = re.search(r'(?:BUY|SELL)\s*\|\s*([A-Z0-9_:]+)', text, re.IGNORECASE)
        if match:
            symbol = clean_symbol(match.group(1))
            
    if action and symbol:
        return {
            "action": action,
            "symbol": symbol,
            "volume": DEFAULT_VOLUME,
            "sl": None,
            "tp": None
        }
    return None

@app.post("/webhook")
async def receive_webhook(request: Request):
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8").strip()
    logger.info(f"Raw webhook payload received: {body_str}")
    
    parsed_data = None
    
    try:
        data = json.loads(body_str)
        action_val = data.get("action")
        symbol_val = data.get("symbol")
        
        if action_val and symbol_val:
            parsed_data = {
                "action": str(action_val).upper().strip(),
                "symbol": clean_symbol(str(symbol_val)),
                "volume": float(data.get("volume", DEFAULT_VOLUME)),
                "sl": float(data.get("sl")) if data.get("sl") is not None else None,
                "tp": float(data.get("tp")) if data.get("tp") is not None else None
            }
    except Exception as e:
        logger.info(f"Payload is not JSON or failed JSON parsing: {e}")
        
    if not parsed_data:
        parsed_data = parse_plain_text_signal(body_str)
        
    if not parsed_data:
        logger.error("Could not parse action and symbol from webhook payload.")
        raise HTTPException(status_code=400, detail="Invalid signal format. Could not parse action and symbol.")
        
    action = parsed_data["action"]
    symbol = parsed_data["symbol"]
    volume = parsed_data["volume"]
    
    if action not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Action must be BUY or SELL")
        
    try:
        if not client._connection.is_connected:
            logger.info("MT5 disconnected. Attempting to reconnect...")
            client.connect()
            
        # Get current market price to pass to send_order
        price_info = client.market.get_symbol_price(symbol)
        price = price_info["ask"] if action == "BUY" else price_info["bid"]
        
        logger.info(f"Executing {action} order for {volume} lots of {symbol} at current price {price} with SL={parsed_data['sl']}, TP={parsed_data['tp']}")
        
        result = send_order(
            client._connection,
            action=TradeRequestActions.DEAL,
            order_type=OrderType.BUY if action == "BUY" else OrderType.SELL,
            symbol=symbol,
            volume=volume,
            price=price,
            stop_loss=parsed_data["sl"] if parsed_data["sl"] is not None else 0.0,
            take_profit=parsed_data["tp"] if parsed_data["tp"] is not None else 0.0,
        )
        
        logger.info(f"Order result: {result}")
        if not result.get("success"):
            raise Exception(result.get("message"))
            
        return {"status": "success", "result": result, "parsed_signal": parsed_data}
        
    except Exception as e:
        logger.error(f"Trade execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    connected = False
    try:
        connected = client._connection.is_connected
    except Exception:
        pass
    return {"status": "ok", "mt5_connected": connected}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
