import requests
import time
import json
from datetime import datetime
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
            print(f"[{datetime.now()}] Market keys: {list(data[0].keys())[:10]}")
        return data
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error fetching markets: {e}")
        return []

def get_recent_trades(limit: int = 100) -> List[Dict]:
    url = f"{DATA_API_URL}/trades"
    params = {
        "limit": limit,
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC"
    }
    
    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"[{datetime.now()}] API Response: {len(data)} trades fetched")
        
        if data:
            first_trade = data[0]
            last_trade = data[-1]
            
            # Extract timestamps
            first_ts = first_trade.get("timestamp") or first_trade.get("createdAt") or first_trade.get("time")
            last_ts = last_trade.get("timestamp") or last_trade.get("createdAt") or last_trade.get("time")
            
            print(f"[{datetime.now()}] ═══ TIME RANGE ═══")
            if first_ts:
                if isinstance(first_ts, (int, float)):
                    first_dt = datetime.fromtimestamp(first_ts)
                else:
                    first_dt = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
                print(f"  Newest trade: {first_dt} ({first_ts})")
            else:
                print(f"  Newest trade: timestamp not found")
            
            if last_ts:
                if isinstance(last_ts, (int, float)):
                    last_dt = datetime.fromtimestamp(last_ts)
                else:
                    last_dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
                print(f"  Oldest trade: {last_dt} ({last_ts})")
                
                if first_ts:
                    if isinstance(first_ts, (int, float)) and isinstance(last_ts, (int, float)):
                        duration_hours = (first_ts - last_ts) / 3600
                    else:
                        duration_hours = (first_dt - last_dt).total_seconds() / 3600
                    print(f"  Time span: {duration_hours:.1f} hours ({duration_hours/24:.1f} days)")
            else:
                print(f"  Oldest trade: timestamp not found")
            
            print(f"[{datetime.now()}] ═══════════════════")
            
            print(f"[{datetime.now()}] Sample trade structure:")
            print(f"  - Keys: {list(first_trade.keys())}")
            print(f"  - Size: {first_trade.get('size', 'N/A')}")
            print(f"  - Price: {first_trade.get('price', 'N/A')}")
            print(f"  - Full trade (first 500 chars): {json.dumps(first_trade)[:500]}")
        return data
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
