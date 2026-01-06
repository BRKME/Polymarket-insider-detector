from src.collector import get_active_markets, get_recent_trades, get_wallet_activity, get_market_by_condition_id
from src.analyzer import calculate_score
from src.config import ALERT_THRESHOLD, MIN_BET_SIZE
from datetime import datetime

def detect_insider_trades():
    alerts = []
    
    print(f"[{datetime.now()}] Fetching active markets...")
    markets = get_active_markets(limit=50)
    print(f"[{datetime.now()}] Found {len(markets)} markets")
    
    print(f"[{datetime.now()}] Fetching recent trades...")
    trades = get_recent_trades(limit=100)
    print(f"[{datetime.now()}] Found {len(trades)} trades")
    
    for trade in trades:
        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            amount = size * price
            
            if amount < MIN_BET_SIZE:
                continue
            
            wallet_address = trade.get("user", {}).get("proxyWallet") or trade.get("user", {}).get("address")
            if not wallet_address:
                continue
            
            condition_id = trade.get("market", {}).get("conditionId")
            if not condition_id:
                continue
            
            market = get_market_by_condition_id(condition_id, markets)
            if not market:
                continue
            
            print(f"[{datetime.now()}] Analyzing wallet {wallet_address[:8]}... (${amount:,.0f})")
            wallet_data = get_wallet_activity(wallet_address)
            
            analysis = calculate_score(trade, wallet_data, market)
            
            if analysis["score"] >= ALERT_THRESHOLD:
                alerts.append({
                    "market": market.get("question"),
                    "market_slug": market.get("slug"),
                    "wallet": wallet_address,
                    "analysis": analysis,
                    "timestamp": datetime.now().isoformat(),
                    "trade_hash": trade.get("transactionHash", "")
                })
                print(f"[{datetime.now()}] 🚨 ALERT! Score: {analysis['score']}")
        
        except Exception as e:
            print(f"[{datetime.now()}] Error processing trade: {e}")
            continue
    
    return alerts
