from datetime import datetime
from typing import Dict
from config import (
    MIN_BET_SIZE, NEW_WALLET_DAYS_HIGH, NEW_WALLET_DAYS_LOW,
    LOW_ACTIVITY_THRESHOLD, LOW_ODDS_THRESHOLD, TIME_TO_RESOLVE_HOURS, SCORES
)

def calculate_wallet_age_days(first_activity_timestamp: int) -> int:
    if not first_activity_timestamp:
        return 999
    first_activity = datetime.fromtimestamp(first_activity_timestamp)
    age = (datetime.now() - first_activity).days
    return age

def calculate_wallet_age_score(first_activity_timestamp: int) -> int:
    if not first_activity_timestamp:
        return 0
    
    age_days = calculate_wallet_age_days(first_activity_timestamp)
    
    if age_days < NEW_WALLET_DAYS_HIGH:
        return SCORES["wallet_age_high"]
    elif age_days < NEW_WALLET_DAYS_LOW:
        return SCORES["wallet_age_low"]
    return 0

def calculate_against_trend_score(trade_price: float) -> int:
    if trade_price < LOW_ODDS_THRESHOLD:
        return SCORES["against_trend"]
    return 0

def calculate_bet_size_score(amount: float) -> int:
    if amount >= MIN_BET_SIZE:
        return SCORES["large_bet"]
    return 0

def calculate_timing_score(end_date_str: str) -> int:
    if not end_date_str:
        return 0
    
    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        hours_until_resolve = (end_date - datetime.now()).total_seconds() / 3600
        
        if 0 < hours_until_resolve < TIME_TO_RESOLVE_HOURS:
            return SCORES["timing"]
    except:
        pass
    
    return 0

def calculate_activity_score(total_activities: int) -> int:
    if total_activities < LOW_ACTIVITY_THRESHOLD:
        return SCORES["low_activity"]
    return 0

def calculate_score(trade: Dict, wallet_data: Dict, market: Dict) -> Dict:
    score = 0
    flags = []
    
    wallet_age_score = calculate_wallet_age_score(wallet_data.get("first_activity_timestamp"))
    if wallet_age_score > 0:
        age_days = calculate_wallet_age_days(wallet_data.get("first_activity_timestamp"))
        score += wallet_age_score
        flags.append(f"New wallet ({age_days}d old)")
    
    trade_price = float(trade.get("price", 0))
    against_trend_score = calculate_against_trend_score(trade_price)
    if against_trend_score > 0:
        score += against_trend_score
        flags.append(f"Against trend ({trade_price*100:.1f}% odds)")
    
    size = float(trade.get("size", 0))
    amount = size * trade_price
    bet_size_score = calculate_bet_size_score(amount)
    if bet_size_score > 0:
        score += bet_size_score
        flags.append(f"Large bet (${amount:,.0f})")
    
    end_date = market.get("endDate")
    timing_score = calculate_timing_score(end_date)
    if timing_score > 0:
        score += timing_score
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            hours = (end_dt - datetime.now()).total_seconds() / 3600
            flags.append(f"Close to deadline ({hours:.0f}h)")
        except:
            pass
    
    total_activities = wallet_data.get("total_count", 0)
    activity_score = calculate_activity_score(total_activities)
    if activity_score > 0:
        score += activity_score
        flags.append(f"Low activity ({total_activities} txns)")
    
    return {
        "score": score,
        "flags": flags,
        "amount": amount,
        "odds": trade_price,
        "wallet_age_days": calculate_wallet_age_days(wallet_data.get("first_activity_timestamp")),
        "total_activities": total_activities
    }
