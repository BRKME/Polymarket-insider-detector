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

class APIError(Exception):
    """Custom exception for API errors"""
    pass

class RateLimitError(Exception):
    """Custom exception for rate limit errors"""
    pass

def make_request_with_retry(url: str, params: dict, max_retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    """
    Make HTTP request with exponential backoff retry logic.
    Handles rate limiting (429) separately with longer delays.
    """
    for attempt in range(max_retries):
        try:
            time.sleep(REQUEST_DELAY)
            response = requests.get(url, params=params, timeout=30)
            
            # Handle rate limiting
            if response.status_code == 429:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    wait_time = RATE_LIMIT_RETRY_DELAY * (attempt + 1)
                    print(f"  ⚠️  Rate limit hit (429). Waiting {wait_time}s before retry {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}")
                    time.sleep(wait_time)
                    continue
                else:
                    raise RateLimitError(f"Rate limit exceeded after {RATE_LIMIT_MAX_RETRIES} retries")
            
            # Handle other HTTP errors
            if response.status_code >= 500:
                if attempt < max_retries - 1:
                    wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                    print(f"  ⚠️  Server error ({response.status_code}). Retry {attempt + 1}/{max_retries} after {wait_time}s")
                    time.sleep(wait_time)
                    continue
                else:
                    raise APIError(f"Server error {response.status_code} after {max_retries} retries")
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                print(f"  ⚠️  Request timeout. Retry {attempt + 1}/{max_retries} after {wait_time}s")
                time.sleep(wait_time)
                continue
            else:
                raise APIError(f"Request timeout after {max_retries} retries")
                
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                print(f"  ⚠️  Request error: {e}. Retry {attempt + 1}/{max_retries} after {wait_time}s")
                time.sleep(wait_time)
                continue
            else:
                raise APIError(f"Request failed after {max_retries} retries: {e}")
    
    return None

def get_active_markets(limit: int = 50) -> List[Dict]:
    """Fetch active markets with retry logic"""
    url = f"{GAMMA_API_URL}/markets"
    params = {
        "limit": limit,
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "_sort": "volume24hr:desc"
    }
    
    try:
        print(f"[{datetime.now()}] Fetching active markets...")
        response = make_request_with_retry(url, params)
        
        if response:
            data = response.json()
            print(f"[{datetime.now()}] ✓ Fetched {len(data)} markets")
            return data
        else:
            print(f"[{datetime.now()}] ⚠️  Failed to fetch markets")
            return []
            
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error fetching markets: {e}")
        return []

def get_recent_trades_paginated(minutes_back: int = MINUTES_BACK) -> List[Dict]:
    """
    Fetch recent trades with pagination and time filtering.
    Implements early exit when reaching old trades to avoid pagination drift.
    """
    all_trades = []
    cutoff_timestamp = int((datetime.now() - timedelta(minutes=minutes_back)).timestamp())
    
    print(f"[{datetime.now()}] Fetching recent trades (last {minutes_back} minutes)...")
    print(f"[{datetime.now()}] Cutoff timestamp: {datetime.fromtimestamp(cutoff_timestamp)}")
    
    for page in range(MAX_PAGES):
        try:
            url = f"{DATA_API_URL}/trades"
            params = {
                "limit": TRADES_LIMIT,
                "offset": page * TRADES_LIMIT,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC"
            }
            
            print(f"[{datetime.now()}] Fetching page {page + 1}/{MAX_PAGES} (offset={params['offset']})...")
            response = make_request_with_retry(url, params)
            
            if not response:
                print(f"[{datetime.now()}] ⚠️  Failed to fetch page {page + 1}, stopping pagination")
                break
            
            trades = response.json()
            
            if not trades:
                print(f"[{datetime.now()}] No more trades available, stopping pagination")
                break
            
            # Log time range of fetched trades
            if trades:
                first_ts = trades[0].get("timestamp")
                last_ts = trades[-1].get("timestamp")
                
                if first_ts and last_ts:
                    first_dt = datetime.fromtimestamp(first_ts)
                    last_dt = datetime.fromtimestamp(last_ts)
                    span = (first_ts - last_ts) / 60  # minutes
                    
                    print(f"  Retrieved {len(trades)} trades")
                    print(f"  Time range: {first_dt} to {last_dt}")
                    print(f"  Span: {span:.1f} minutes")
            
            # Filter by timestamp
            recent_trades = [t for t in trades if t.get("timestamp", 0) >= cutoff_timestamp]
            old_trades = len(trades) - len(recent_trades)
            
            print(f"  Trades after cutoff: {len(recent_trades)}/{len(trades)}")
            
            all_trades.extend(recent_trades)
            
            # Early exit if we've reached old trades
            if old_trades > 0:
                print(f"  Reached {old_trades} old trades, stopping pagination (prevents drift)")
                break
            
            # Stop if we got fewer trades than requested (end of data)
            if len(trades) < TRADES_LIMIT:
                print(f"  Got fewer than {TRADES_LIMIT} trades, no more data available")
                break
            
            # Delay between pages for rate limiting
            if page < MAX_PAGES - 1:
                time.sleep(PAGE_DELAY)
                
        except RateLimitError as e:
            print(f"[{datetime.now()}] ❌ Rate limit error: {e}")
            print(f"  Collected {len(all_trades)} trades before rate limit")
            break
            
        except APIError as e:
            print(f"[{datetime.now()}] ❌ API error on page {page + 1}: {e}")
            print(f"  Collected {len(all_trades)} trades before error")
            break
            
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Unexpected error on page {page + 1}: {e}")
            import traceback
            traceback.print_exc()
            break
    
    print(f"[{datetime.now()}] ═══════════════════════════════")
    print(f"[{datetime.now()}] COLLECTION SUMMARY:")
    print(f"[{datetime.now()}] Total pages fetched: {min(page + 1, MAX_PAGES)}")
    print(f"[{datetime.now()}] Total trades collected: {len(all_trades)}")
    print(f"[{datetime.now()}] Time window: {minutes_back} minutes")
    print(f"[{datetime.now()}] ═══════════════════════════════")
    
    return all_trades

def get_wallet_activity(address: str) -> Dict:
    """Fetch wallet activity with retry logic"""
    url = f"{DATA_API_URL}/activity"
    params = {
        "user": address,
        "sortBy": "TIMESTAMP",
        "sortDirection": "ASC",
        "limit": 100
    }
    
    try:
        response = make_request_with_retry(url, params)
        
        if not response:
            return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
        
        activities = response.json()
        
        if not activities:
            print(f"  ⚠️  No activity found for wallet")
            return {"activities": [], "first_activity_timestamp": None, "total_count": 0}
        
        first_timestamp = activities[0].get("timestamp")
        
        if first_timestamp:
            first_date = datetime.fromtimestamp(first_timestamp).strftime('%Y-%m-%d')
            print(f"  ✓ Activity: {len(activities)} records, first: {first_date}")
        
        return {
            "activities": activities,
            "first_activity_timestamp": first_timestamp,
            "total_count": len(activities)
        }
        
    except Exception as e:
        print(f"  ❌ Error fetching wallet activity: {e}")
        return {"activities": [], "first_activity_timestamp": None, "total_count": 0}

def get_market_by_condition_id(condition_id: str, markets: List[Dict]) -> Optional[Dict]:
    """Find market by condition ID"""
    for market in markets:
        if market.get("conditionId") == condition_id:
            return market
    return None
