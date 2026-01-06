import requests
import time
from datetime import datetime
from typing import List, Dict, Optional
from src.config import GAMMA_API_URL, DATA_API_URL, REQUEST_DELAY

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
        return response.json()
    except Exception as e:
        print(f"Error fetching markets: {e}")
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
        return response.json()
    except Exception as e:
        print(f"Error fetching trades: {e}")
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
            return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
        
        first_timestamp = activities[0].get("timestamp")
        
        return {
            "activities": activities,
            "first_activity_timestamp": first_timestamp,
            "total_count": len(activities)
        }
    except Exception as e:
        print(f"Error fetching wallet activity for {address}: {e}")
        return {"activities": [], "first_activity_timestamp": None, "total_count": 0}

def get_market_by_condition_id(condition_id: str, markets: List[Dict]) -> Optional[Dict]:
    for market in markets:
        if market.get("conditionId") == condition_id:
            return market
    return None
