from datetime import datetime
from collector import get_active_markets, get_recent_trades, get_wallet_activity, get_market_by_condition_id
from analyzer import calculate_score
from config import ALERT_THRESHOLD, MIN_BET_SIZE

def detect_insider_trades():
    alerts = []
    
    print(f"[{datetime.now()}] Fetching active markets...")
    markets = get_active_markets(limit=50)
    print(f"[{datetime.now()}] Found {len(markets)} markets")
    
    print(f"[{datetime.now()}] Fetching recent trades...")
    trades = get_recent_trades(limit=100)
    print(f"[{datetime.now()}] Found {len(trades)} trades")
    
    processed_count = 0
    filtered_count = 0
    
    for trade in trades:
        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            amount = size * price
            
            print(f"\n[{datetime.now()}] Trade #{processed_count + 1}: size={size:.2f}, price={price:.4f}, amount=${amount:,.2f}")
            
            if amount < MIN_BET_SIZE:
                print(f"  ❌ Filtered: amount ${amount:,.2f} < ${MIN_BET_SIZE:,.0f}")
                filtered_count += 1
                continue
            
            wallet_address = trade.get("user", {}).get("proxyWallet") or trade.get("user", {}).get("address")
            if not wallet_address:
                print(f"  ❌ Filtered: no wallet address found")
                filtered_count += 1
                continue
            
            print(f"  ✓ Wallet: {wallet_address[:8]}...{wallet_address[-4:]}")
            
            condition_id = trade.get("market", {}).get("conditionId")
            if not condition_id:
                print(f"  ❌ Filtered: no condition_id found")
                filtered_count += 1
                continue
            
            market = get_market_by_condition_id(condition_id, markets)
            if not market:
                print(f"  ❌ Filtered: market not found for condition_id={condition_id[:8]}...")
                filtered_count += 1
                continue
            
            print(f"  ✓ Market: {market.get('question', 'Unknown')[:60]}...")
            print(f"  → Fetching wallet activity...")
            
            wallet_data = get_wallet_activity(wallet_address)
            print(f"  ✓ Wallet activity: {wallet_data.get('total_count', 0)} transactions")
            
            analysis = calculate_score(trade, wallet_data, market)
            
            print(f"  📊 SCORE: {analysis['score']}/110")
            print(f"     Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
            print(f"     Wallet age: {analysis['wallet_age_days']} days")
            print(f"     Total activities: {analysis['total_activities']}")
            print(f"     Odds: {analysis['odds']*100:.1f}%")
            
            if analysis["score"] >= ALERT_THRESHOLD:
                alerts.append({
                    "market": market.get("question"),
                    "market_slug": market.get("slug"),
                    "wallet": wallet_address,
                    "analysis": analysis,
                    "timestamp": datetime.now().isoformat(),
                    "trade_hash": trade.get("transactionHash", "")
                })
                print(f"  🚨 ALERT! Score {analysis['score']} >= {ALERT_THRESHOLD}")
            else:
                print(f"  ✓ Below threshold ({analysis['score']} < {ALERT_THRESHOLD})")
            
            processed_count += 1
        
        except Exception as e:
            print(f"  ❌ Error processing trade: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n[{datetime.now()}] ════════════════════════════════")
    print(f"[{datetime.now()}] SUMMARY:")
    print(f"[{datetime.now()}] Total trades fetched: {len(trades)}")
    print(f"[{datetime.now()}] Processed: {processed_count}")
    print(f"[{datetime.now()}] Filtered out: {filtered_count}")
    print(f"[{datetime.now()}] Alerts generated: {len(alerts)}")
    print(f"[{datetime.now()}] ════════════════════════════════")
    
    return alerts
