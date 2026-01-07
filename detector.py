from datetime import datetime
from collector import get_active_markets, get_recent_trades_paginated, get_wallet_activity, get_market_by_condition_id
from analyzer import calculate_score
from config import ALERT_THRESHOLD, MIN_BET_SIZE

def detect_insider_trades():
    """
    Main detection function with comprehensive error handling and logging.
    Returns list of alerts for trades meeting suspicious criteria.
    """
    alerts = []
    execution_start = datetime.now()
    
    try:
        # Fetch markets
        markets = get_active_markets(limit=50)
        if not markets:
            print(f"[{datetime.now()}] ⚠️  WARNING: No markets fetched, aborting")
            return []
        
        print(f"[{datetime.now()}] Found {len(markets)} active markets")
        
        # Fetch trades with pagination
        trades = get_recent_trades_paginated(markets)
        
        if not trades:
            print(f"[{datetime.now()}] ⚠️  WARNING: No trades fetched")
            return []
        
        print(f"[{datetime.now()}] Analyzing {len(trades)} trades...")
        
        # Analysis counters
        processed_count = 0
        filtered_small = 0
        filtered_no_wallet = 0
        filtered_no_condition = 0
        filtered_no_market = 0
        error_count = 0
        
        for idx, trade in enumerate(trades):
            try:
                # Extract basic trade info
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                amount = size * price
                
                # Log progress every 100 trades
                if (idx + 1) % 100 == 0:
                    elapsed = (datetime.now() - execution_start).total_seconds()
                    print(f"[{datetime.now()}] Progress: {idx + 1}/{len(trades)} trades ({elapsed:.1f}s elapsed)")
                
                # Filter by minimum bet size
                if amount < MIN_BET_SIZE:
                    filtered_small += 1
                    continue
                
                # Extract wallet address
                wallet_address = trade.get("proxyWallet")
                if not wallet_address:
                    filtered_no_wallet += 1
                    continue
                
                # Extract condition ID
                condition_id = trade.get("conditionId")
                if not condition_id:
                    filtered_no_condition += 1
                    continue
                
                # Find market
                market = get_market_by_condition_id(condition_id, markets)
                if not market:
                    # Use trade data as fallback
                    market = {
                        "question": trade.get("title", "Unknown market"),
                        "slug": trade.get("slug", ""),
                        "conditionId": condition_id,
                        "endDate": None
                    }
                    filtered_no_market += 1
                
                # Log high-value trades
                print(f"\n[{datetime.now()}] 💰 Large trade: ${amount:,.0f}")
                print(f"  Wallet: {wallet_address[:8]}...{wallet_address[-4:]}")
                print(f"  Market: {market.get('question', 'Unknown')[:60]}...")
                
                # Fetch wallet activity
                print(f"  → Fetching wallet activity...")
                wallet_data = get_wallet_activity(wallet_address)
                
                if wallet_data.get('total_count', 0) == 0:
                    print(f"  ⚠️  No wallet activity found, skipping")
                    continue
                
                # Calculate suspicion score
                analysis = calculate_score(trade, wallet_data, market)
                
                print(f"  📊 Score: {analysis['score']}/110")
                print(f"     Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
                print(f"     Wallet age: {analysis['wallet_age_days']} days")
                print(f"     Activities: {analysis['total_activities']}")
                print(f"     Odds: {analysis['odds']*100:.1f}%")
                
                # Check if alert threshold met
                if analysis["score"] >= ALERT_THRESHOLD:
                    alert = {
                        "market": market.get("question"),
                        "market_slug": market.get("slug"),
                        "wallet": wallet_address,
                        "analysis": analysis,
                        "timestamp": datetime.now().isoformat(),
                        "trade_hash": trade.get("transactionHash", ""),
                        "trade_timestamp": trade.get("timestamp")
                    }
                    alerts.append(alert)
                    print(f"  🚨 ALERT! Score {analysis['score']} >= {ALERT_THRESHOLD}")
                else:
                    print(f"  ✓ Below threshold ({analysis['score']} < {ALERT_THRESHOLD})")
                
                processed_count += 1
                
            except Exception as e:
                error_count += 1
                print(f"  ❌ Error processing trade #{idx + 1}: {e}")
                if error_count > 10:
                    print(f"[{datetime.now()}] ⚠️  Too many errors ({error_count}), stopping analysis")
                    break
                continue
        
        # Final summary
        execution_time = (datetime.now() - execution_start).total_seconds()
        
        print(f"\n[{datetime.now()}] ════════════════════════════════")
        print(f"[{datetime.now()}] DETECTION SUMMARY:")
        print(f"[{datetime.now()}] ════════════════════════════════")
        print(f"[{datetime.now()}] Total trades analyzed: {len(trades)}")
        print(f"[{datetime.now()}] Processed (≥${MIN_BET_SIZE:,}): {processed_count}")
        print(f"[{datetime.now()}] ")
        print(f"[{datetime.now()}] Filtered out:")
        print(f"[{datetime.now()}]   - Small bets (<${MIN_BET_SIZE:,}): {filtered_small}")
        print(f"[{datetime.now()}]   - No wallet address: {filtered_no_wallet}")
        print(f"[{datetime.now()}]   - No condition ID: {filtered_no_condition}")
        print(f"[{datetime.now()}]   - Market not found: {filtered_no_market}")
        print(f"[{datetime.now()}] ")
        print(f"[{datetime.now()}] Errors encountered: {error_count}")
        print(f"[{datetime.now()}] Alerts generated: {len(alerts)}")
        print(f"[{datetime.now()}] Execution time: {execution_time:.1f}s")
        print(f"[{datetime.now()}] ════════════════════════════════")
        
        return alerts
        
    except Exception as e:
        print(f"[{datetime.now()}] ❌ FATAL ERROR in detect_insider_trades: {e}")
        import traceback
        traceback.print_exc()
        return []
