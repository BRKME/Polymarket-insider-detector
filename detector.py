from datetime import datetime, timezone
from collector import get_active_markets, get_recent_trades_paginated, get_wallet_activity, get_market_by_condition_id
from analyzer import calculate_score, should_skip_alert
from event_detector_fixed import detect_pre_event_trade, calculate_latency_score, get_latency_insight
from database_fixed import (
    init_database, get_wallet_stats, update_wallet_stats, 
    save_trade, is_alert_sent, mark_alert_sent
)
from config import ALERT_THRESHOLD, MIN_BET_SIZE

def detect_insider_trades():
    """
    Main detection function with event latency and wallet tracking.
    Phase 1 enhancements:
    - Pre-event trade detection
    - Historical wallet performance tracking
    - Enhanced insider scoring
    
    All critical bugs fixed:
    - BUG #1-8: Fixed
    - ISSUE #9: Database indexes added
    - ISSUE #11: Batch operations (wallet stats cache)
    - ISSUE #15: Thread-safe database
    - ISSUE #16: Data validation
    - ISSUE #20: Database backup
    """
    # Initialize database on first run (with backup)
    init_database()
    
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
        
        # FIX ISSUE #11: Pre-fetch wallet stats for all unique wallets (batch operation)
        print(f"[{datetime.now()}] Pre-fetching wallet stats for batch processing...")
        unique_wallets = set()
        for trade in trades:
            wallet = trade.get("proxyWallet")
            if wallet:
                unique_wallets.add(wallet)
        
        wallet_stats_cache = {}
        for wallet in unique_wallets:
            stats = get_wallet_stats(wallet)
            if stats:
                wallet_stats_cache[wallet] = stats
        
        print(f"[{datetime.now()}] Cached stats for {len(wallet_stats_cache)} wallets")
        
        # Analysis counters
        processed_count = 0
        filtered_small = 0
        filtered_no_wallet = 0
        filtered_no_condition = 0
        filtered_no_market = 0
        filtered_by_rules = 0
        filtered_duplicate = 0
        filtered_invalid_data = 0
        pre_event_detected = 0
        error_count = 0
        debug_printed = False
        
        for idx, trade in enumerate(trades):
            try:
                # Extract basic trade info
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                amount = size * price
                
                # FIX ISSUE #16: Validate data before processing
                if amount <= 0:
                    filtered_invalid_data += 1
                    continue
                
                if not (0 <= price <= 1):
                    filtered_invalid_data += 1
                    continue
                
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
                    market = {
                        "question": trade.get("title", "Unknown market"),
                        "slug": trade.get("slug", ""),
                        "conditionId": condition_id,
                        "endDate": trade.get("endDate")
                    }
                    filtered_no_market += 1
                
                # Check for duplicate alert
                trade_hash = trade.get("transactionHash", "")
                if is_alert_sent(wallet_address, trade_hash):
                    filtered_duplicate += 1
                    continue
                
                # Log high-value trades
                print(f"\n[{datetime.now()}] 💰 Large trade: ${amount:,.0f}")
                print(f"  Wallet: {wallet_address[:8]}...{wallet_address[-4:]}")
                print(f"  Market: {market.get('question', 'Unknown')[:60]}...")
                
                # DEBUG: Print trade structure once
                if not debug_printed:
                    print(f"\n  ═══ DEBUG: TRADE OBJECT STRUCTURE ═══")
                    print(f"  Available keys: {list(trade.keys())}")
                    print(f"  Sample trade data (first 10 fields):")
                    for key, value in list(trade.items())[:10]:
                        print(f"    {key}: {value}")
                    print(f"  ═══════════════════════════════════════\n")
                    debug_printed = True
                
                # Event Latency Detection
                latency_data = detect_pre_event_trade(trade, market)
                if latency_data:
                    pre_event_detected += 1
                    print(f"  {get_latency_insight(latency_data)}")
                    print(f"     Trade time: {latency_data['trade_time']}")
                    print(f"     Event time: {latency_data['event_time']}")
                
                # Get Wallet Historical Stats (from cache)
                wallet_stats = wallet_stats_cache.get(wallet_address)
                if wallet_stats:
                    print(f"  📊 Wallet History:")
                    print(f"     Total trades: {wallet_stats['total_trades']}")
                    print(f"     Pre-event trades: {wallet_stats['pre_event_trades']}")
                    print(f"     Insider Score: {wallet_stats['insider_score']:.1f}")
                    print(f"     Classification: {wallet_stats['classification']}")
                
                # Fetch wallet activity
                print(f"  → Fetching wallet activity...")
                wallet_data = get_wallet_activity(wallet_address)
                
                if wallet_data.get('total_count', 0) == 0:
                    print(f"  ⚠️  No wallet activity found, skipping")
                    continue
                
                # Calculate base suspicion score
                analysis = calculate_score(trade, wallet_data, market)
                
                # Add Latency Score
                latency_score = 0
                if latency_data:
                    latency_score = calculate_latency_score(latency_data['latency_seconds'])
                    analysis['score'] += latency_score
                    analysis['flags'].append(f"Pre-event latency: {latency_data['latency_minutes']:.0f}m")
                
                # Add Wallet History Score
                history_score = 0
                if wallet_stats and wallet_stats['total_trades'] >= 3:
                    # Bonus for proven insiders
                    if wallet_stats['insider_score'] >= 70:
                        history_score = 20
                        analysis['flags'].append(f"Known insider (score: {wallet_stats['insider_score']:.0f})")
                    elif wallet_stats['insider_score'] >= 50:
                        history_score = 10
                        analysis['flags'].append(f"Suspicious history (score: {wallet_stats['insider_score']:.0f})")
                
                analysis['score'] += history_score
                
                print(f"  📊 Score: {analysis['score']}/150 (base: {analysis['score'] - latency_score - history_score}, latency: +{latency_score}, history: +{history_score})")
                print(f"     Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
                print(f"     Wallet age: {analysis['wallet_age_days']} days")
                print(f"     Activities: {analysis['total_activities']}")
                print(f"     Odds: {analysis['odds']*100:.1f}%")
                
                # Check if alert threshold met
                if analysis["score"] >= ALERT_THRESHOLD:
                    # Apply filters before alerting
                    should_skip, skip_reason = should_skip_alert(
                        market_question=market.get("question", ""),
                        wallet_age_days=analysis['wallet_age_days'],
                        odds=analysis['odds'],
                        total_activities=analysis['total_activities'],
                        end_date_str=market.get("endDate")
                    )
                    
                    if should_skip:
                        filtered_by_rules += 1
                        print(f"  🚫 FILTERED: {skip_reason}")
                        print(f"     (Score was {analysis['score']} >= {ALERT_THRESHOLD}, but filtered out)")
                    else:
                        # Create enhanced alert
                        alert = {
                            "market": market.get("question"),
                            "market_slug": market.get("slug"),
                            "wallet": wallet_address,
                            "analysis": analysis,
                            "timestamp": datetime.now().isoformat(),
                            "trade_hash": trade_hash,
                            "trade_timestamp": trade.get("timestamp"),
                            # Latency data
                            "latency": latency_data,
                            # Wallet stats
                            "wallet_stats": wallet_stats,
                            # Trade data for notifier
                            "trade_data": {
                                "outcome": trade.get("outcome"),
                                "side": trade.get("side"),
                                "price": price,
                                "size": size,
                                "amount": amount
                            }
                        }
                        alerts.append(alert)
                        print(f"  🚨 ALERT! Score {analysis['score']} >= {ALERT_THRESHOLD}")
                        
                        # Mark alert as sent
                        mark_alert_sent(
                            wallet_address, 
                            market.get("question"), 
                            trade_hash,
                            wallet_stats['insider_score'] if wallet_stats else 0,
                            latency_data['latency_seconds'] if latency_data else None
                        )
                else:
                    print(f"  ✓ Below threshold ({analysis['score']} < {ALERT_THRESHOLD})")
                
                # Save Trade to History
                # FIX BUG #8: Use timezone-aware timestamps
                trade_record = {
                    'wallet': wallet_address,
                    'market': market.get('question'),
                    'trade_timestamp': datetime.fromtimestamp(trade.get('timestamp'), tz=timezone.utc),
                    'event_timestamp': datetime.fromisoformat(latency_data['event_time']) if latency_data else None,
                    'latency_seconds': latency_data['latency_seconds'] if latency_data else None,
                    'position': trade.get('outcome', 'Unknown'),
                    'size': amount,
                    'odds': price,
                    'is_pre_event': latency_data is not None,
                    'trade_hash': trade_hash
                }
                save_trade(trade_record)
                
                # Update Wallet Stats
                update_wallet_stats(wallet_address, {
                    'size': amount,
                    'is_pre_event': latency_data is not None,
                    'latency_seconds': latency_data['latency_seconds'] if latency_data else None
                })
                
                processed_count += 1
                
            except Exception as e:
                error_count += 1
                print(f"  ❌ Error processing trade #{idx + 1}: {e}")
                import traceback
                traceback.print_exc()
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
        print(f"[{datetime.now()}]   - Invalid data: {filtered_invalid_data}")
        print(f"[{datetime.now()}]   - No wallet address: {filtered_no_wallet}")
        print(f"[{datetime.now()}]   - No condition ID: {filtered_no_condition}")
        print(f"[{datetime.now()}]   - Market not found: {filtered_no_market}")
        print(f"[{datetime.now()}]   - Duplicate alerts: {filtered_duplicate}")
        print(f"[{datetime.now()}]   - Arbitrage/Short-term/Absurd: {filtered_by_rules}")
        print(f"[{datetime.now()}] ")
        print(f"[{datetime.now()}] 🔍 Pre-event trades detected: {pre_event_detected}")
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
