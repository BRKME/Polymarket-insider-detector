import requests
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from config import GAMMA_API_URL, DATA_API_URL, REQUEST_DELAY

def get_active_markets(limit: int = 50) -> List[Dict]:
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
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"[{datetime.now()}] API Response: {len(data)} markets fetched")
        if data:
            print(f"[{datetime.now()}] Sample market: {data[0].get('question', 'N/A')[:60]}...")
        return data
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error fetching markets: {e}")
        return []

def get_recent_trades(limit: int = 1000, minutes_back: int = 35) -> List[Dict]:
    """
    Fetch recent trades and filter to last N minutes.
    Uses limit=1000 to maximize coverage, then filters by time.
    """
    url = f"{DATA_API_URL}/trades"
    params = {
        "limit": limit,  # Максимум сколько можем взять
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC"
    }
    
    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"[{datetime.now()}] API Response: {len(data)} trades fetched")
        
        if not data:
            return []
        
        # Calculate time cutoff (35 minutes ago to have buffer)
        cutoff_time = datetime.now() - timedelta(minutes=minutes_back)
        cutoff_timestamp = int(cutoff_time.timestamp())
        
        # Filter trades by time
        filtered_trades = []
        for trade in data:
            trade_ts = trade.get("timestamp")
            if trade_ts and trade_ts >= cutoff_timestamp:
                filtered_trades.append(trade)
        
        # Time range analysis
        if data:
            first_trade = data[0]
            last_trade = data[-1]
            
            first_ts = first_trade.get("timestamp")
            last_ts = last_trade.get("timestamp")
            
            print(f"[{datetime.now()}] ═══ TIME RANGE ═══")
            if first_ts:
                first_dt = datetime.fromtimestamp(first_ts)
                print(f"  Newest trade: {first_dt} ({first_ts})")
            
            if last_ts:
                last_dt = datetime.fromtimestamp(last_ts)
                print(f"  Oldest trade: {last_dt} ({last_ts})")
                
                if first_ts:
                    duration_hours = (first_ts - last_ts) / 3600
                    print(f"  Full span: {duration_hours:.1f} hours ({duration_hours/24:.1f} days)")
            
            print(f"  Cutoff time: {cutoff_time}")
            print(f"  Trades after cutoff: {len(filtered_trades)}/{len(data)}")
            print(f"[{datetime.now()}] ═══════════════════")
        
        return filtered_trades
        
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error fetching trades: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_wallet_activity(address: str) -> Dict:
    url = f"{DATA_API_URL}/activity"
    params = {
        "user": address,
        "sortBy": "TIMESTAMP",
        "sortDirection": "ASC",
        "limit": 100
    }
    
    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        activities = response.json()
        
        if not activities:
            print(f"  ⚠️  No activity found for wallet")
            return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
        
        first_timestamp = activities[0].get("timestamp")
        print(f"  ✓ Activity found: {len(activities)} records, first activity: {datetime.fromtimestamp(first_timestamp).strftime('%Y-%m-%d') if first_timestamp else 'Unknown'}")
        
        return {
            "activities": activities,
            "first_activity_timestamp": first_timestamp,
            "total_count": len(activities)
        }
    except Exception as e:
        print(f"  ❌ Error fetching wallet activity: {e}")
        return {"activities": [], "first_activity_timestamp": None, "total_count": 0}

def get_market_by_condition_id(condition_id: str, markets: List[Dict]) -> Optional[Dict]:
    for market in markets:
        if market.get("conditionId") == condition_id:
            return market
    return None
