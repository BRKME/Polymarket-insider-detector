import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from config import (
    GAMMA_API_URL, DATA_API_URL, TRADES_LIMIT, MAX_PAGES, 
    MINUTES_BACK, PAGE_DELAY, REQUEST_DELAY,
    MAX_RETRIES, RETRY_DELAY, RETRY_BACKOFF,
    RATE_LIMIT_RETRY_DELAY, RATE_LIMIT_MAX_RETRIES
)

def make_request_with_retry(url: str, params: dict, max_retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    """Make HTTP request with exponential backoff retry logic"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
            
            # Handle rate limiting
            if response.status_code == 429:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    print(f"  ⚠️  Rate limited, waiting {RATE_LIMIT_RETRY_DELAY}s...")
                    time.sleep(RATE_LIMIT_RETRY_DELAY)
                    continue
                else:
                    print(f"  ❌ Rate limit max retries exceeded")
                    return None
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                delay = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                print(f"  ⚠️  Request failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"  ❌ Request failed after {max_retries} attempts: {e}")
                return None
    
    return None

def get_active_markets(limit: int = 50) -> List[Dict]:
    """Fetch active markets sorted by volume"""
    url = f"{GAMMA_API_URL}/markets"
    params = {
        "limit": limit,
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "_sort": "volume24hr:desc"
    }
    
    try:
        time.sleep(REQUEST_DELAY)
        response = make_request_with_retry(url, params)
        if response:
            data = response.json()
            print(f"[{datetime.now()}] ✓ Fetched {len(data)} markets")
            return data
        return []
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error fetching markets: {e}")
        return []

def is_trade_suspicious(trade: Dict, market: Dict) -> bool:
    """
    Smart filter to reduce noise - check if trade is worth analyzing
    Returns True if trade looks suspicious/interesting
    """
    try:
        size = float(trade.get("size", 0))
        price = float(trade.get("price", 0))
        amount = size * price
        
        # Basic size filter
        if amount < 10000:
            return False
        
        # FILTER 1: Extreme odds (high conviction)
        # Skip "obvious" bets between 40-60%
        if 0.40 <= price <= 0.60:
            return False
        
        # FILTER 2: Market volume context
        # Higher threshold for high-volume markets (more noise)
        market_volume = float(market.get("volume24hr", 0))
        
        if market_volume > 10_000_000:  # $10M+ volume
            if amount < 50_000:  # Need $50k+ to be interesting
                return False
        elif market_volume < 100_000:  # <$100k volume
            if amount < 5_000:  # Lower threshold for small markets
                return False
        
        # FILTER 3: Market category priority
        # Focus on high-value categories
        priority_categories = ['politics', 'economics', 'sports']
        category = market.get('groupItemTitle', '').lower()
        
        if category not in priority_categories:
            # Higher threshold for other categories
            if amount < 25_000:
                return False
        
        # Trade passes all filters
        return True
        
    except Exception as e:
        print(f"  ⚠️  Error in smart filter: {e}")
        return True  # If filter fails, process anyway (conservative)

def get_recent_trades_paginated(markets: List[Dict]) -> List[Dict]:
    """
    Fetch recent trades with pagination and early exit
    Returns trades within the time window
    """
    cutoff_time = datetime.now() - timedelta(minutes=MINUTES_BACK)
    cutoff_timestamp = int(cutoff_time.timestamp())
    
    print(f"[{datetime.now()}] Fetching recent trades (last {MINUTES_BACK} minutes)...")
    print(f"[{datetime.now()}] Cutoff timestamp: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_trades = []
    page = 0
    
    # Create market lookup for smart filtering
    market_lookup = {m['conditionId']: m for m in markets if 'conditionId' in m}
    
    while page < MAX_PAGES:
        print(f"[{datetime.now()}] Fetching page {page + 1}/{MAX_PAGES} (offset={page * TRADES_LIMIT})...")
        
        url = f"{DATA_API_URL}/trades"
        params = {
            "limit": TRADES_LIMIT,
            "offset": page * TRADES_LIMIT,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC"
        }
        
        response = make_request_with_retry(url, params)
        if not response:
            print(f"  ❌ Failed to fetch page {page + 1}, stopping pagination")
            break
        
        try:
            trades = response.json()
            
            if not trades:
                print(f"  ℹ️  No more trades available")
                break
            
            # Extract timestamps for logging
            if len(trades) >= 2:
                first_ts = trades[0].get('timestamp', 0)
                last_ts = trades[-1].get('timestamp', 0)
                
                if first_ts and last_ts:
                    first_time = datetime.fromtimestamp(first_ts)
                    last_time = datetime.fromtimestamp(last_ts)
                    span_minutes = (first_ts - last_ts) / 60
                    
                    print(f"  Retrieved {len(trades)} trades")
                    print(f"  Time range: {first_time.strftime('%Y-%m-%d %H:%M:%S')} to {last_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"  Span: {span_minutes:.1f} minutes")
            
            # Filter trades by timestamp AND smart filters
            recent_trades = []
            filtered_by_time = 0
            filtered_by_smart = 0
            
            for trade in trades:
                timestamp = trade.get('timestamp', 0)
                
                # Time filter
                if timestamp < cutoff_timestamp:
                    filtered_by_time += 1
                    continue
                
                # Smart filter to reduce noise
                condition_id = trade.get('conditionId')  # FIXED: Direct access!
                if condition_id and condition_id in market_lookup:
                    market = market_lookup[condition_id]
                    
                    if not is_trade_suspicious(trade, market):
                        filtered_by_smart += 1
                        continue
                
                recent_trades.append(trade)
            
            print(f"  Trades after cutoff: {len(recent_trades)}/{len(trades)}")
            if filtered_by_smart > 0:
                print(f"  Filtered by smart filters: {filtered_by_smart}")
            
            all_trades.extend(recent_trades)
            
            # Early exit if we hit old trades
            if filtered_by_time > len(trades) * 0.5:
                print(f"  Reached {filtered_by_time} old trades, stopping pagination (prevents drift)")
                break
            
            # Early exit if no trades returned
            if len(trades) < TRADES_LIMIT:
                print(f"  Got fewer than {TRADES_LIMIT} trades, no more data available")
                break
            
            page += 1
            
            # Delay between pages to avoid rate limiting
            if page < MAX_PAGES:
                time.sleep(PAGE_DELAY)
        
        except Exception as e:
            print(f"  ❌ Error processing page {page + 1}: {e}")
            break
    
    print(f"[{datetime.now()}] ═══════════════════════════════")
    print(f"[{datetime.now()}] COLLECTION SUMMARY:")
    print(f"[{datetime.now()}] Total pages fetched: {page}")
    print(f"[{datetime.now()}] Total trades collected: {len(all_trades)}")
    print(f"[{datetime.now()}] Time window: {MINUTES_BACK} minutes")
    print(f"[{datetime.now()}] ═══════════════════════════════")
    
    return all_trades

def get_wallet_activity(address: str) -> Dict:
    """Get wallet activity history for analysis"""
    url = f"{DATA_API_URL}/activity"
    params = {
        "user": address,
        "sortBy": "TIMESTAMP",
        "sortDirection": "ASC",
        "limit": 100
    }
    
    try:
        time.sleep(REQUEST_DELAY)
        response = make_request_with_retry(url, params)
        
        if response:
            activities = response.json()
            
            if not activities:
                return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
            
            first_timestamp = activities[0].get("timestamp")
            
            return {
                "activities": activities,
                "first_activity_timestamp": first_timestamp,
                "total_count": len(activities)
            }
        
        return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
        
    except Exception as e:
        print(f"  ❌ Error fetching wallet activity: {e}")
        return {"activities": [], "first_activity_timestamp": None, "total_count": 0}

def get_market_by_condition_id(condition_id: str, markets: List[Dict]) -> Optional[Dict]:
    """Find market by condition ID"""
    for market in markets:
        if market.get("conditionId") == condition_id:
            return market
    return None
