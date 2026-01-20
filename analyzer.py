from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, Optional
import re
from functools import lru_cache
from config import (
    MIN_BET_SIZE, NEW_WALLET_DAYS_HIGH, NEW_WALLET_DAYS_LOW,
    LOW_ACTIVITY_THRESHOLD, LOW_ODDS_THRESHOLD, TIME_TO_RESOLVE_HOURS, SCORES,
    BLOCK_15MIN_MARKETS, BLOCK_SHORT_PRICE_PREDICTIONS, MAX_ODDS_THRESHOLD
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
    """
    Score trades with extreme odds (both low and high)
    Low odds (< 10%): Betting against strong favorites (insider info?)
    High odds (> 95%): Betting with extreme confidence (insider info?)
    """
    if trade_price < LOW_ODDS_THRESHOLD:  # < 10%
        return SCORES["against_trend"]
    elif trade_price > 0.95:  # > 95% extreme confidence
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
        hours_until_resolve = (end_date - datetime.now(timezone.utc)).total_seconds() / 3600
        
        if 0 < hours_until_resolve < TIME_TO_RESOLVE_HOURS:
            return SCORES["timing"]
    except:
        pass
    
    return 0

def calculate_activity_score(total_activities: int) -> int:
    if total_activities < LOW_ACTIVITY_THRESHOLD:
        return SCORES["low_activity"]
    return 0

@lru_cache(maxsize=100)
def extract_event_date_from_title(title: str) -> Optional[datetime]:
    """
    Extract event date from market title.
    Patterns: "2026-01-19", "January 19", "Jan 19", "19.01.2026", etc.
    Returns timezone-aware datetime in UTC.
    """
    if not title:
        return None
    
    title_lower = title.lower()
    
    # Pattern 1: ISO date (2026-01-19, 2026/01/19)
    iso_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', title)
    if iso_match:
        try:
            year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except:
            pass
    
    # Pattern 2: Reverse date (19-01-2026, 19/01/2026, 19.01.2026)
    reverse_match = re.search(r'(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{4})', title)
    if reverse_match:
        try:
            day, month, year = int(reverse_match.group(1)), int(reverse_match.group(2)), int(reverse_match.group(3))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except:
            pass
    
    # Pattern 3: Month name (January 19, Jan 19, 19 January)
    months = {
        'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
        'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6,
        'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12
    }
    
    for month_name, month_num in months.items():
        # "January 19" or "Jan 19"
        pattern1 = rf'{month_name}\s+(\d{{1,2}})'
        match1 = re.search(pattern1, title_lower)
        if match1:
            day = int(match1.group(1))
            year = datetime.now().year
            
            # FIX BUG #3: If month already passed this year, use next year
            current_month = datetime.now().month
            if month_num < current_month:
                year += 1
            
            try:
                return datetime(year, month_num, day, tzinfo=timezone.utc)
            except:
                pass
        
        # "19 January" or "19 Jan"
        pattern2 = rf'(\d{{1,2}})\s+{month_name}'
        match2 = re.search(pattern2, title_lower)
        if match2:
            day = int(match2.group(1))
            year = datetime.now().year
            
            # FIX BUG #3: If month already passed this year, use next year
            current_month = datetime.now().month
            if month_num < current_month:
                year += 1
            
            try:
                return datetime(year, month_num, day, tzinfo=timezone.utc)
            except:
                pass
    
    return None

def is_15min_market(market_question: str) -> bool:
    """
    Detect 15-minute interval HFT markets.
    Examples: "Bitcoin Up or Down - January 19, 5:15AM-5:30AM ET"
    """
    if not market_question:
        return False
    
    title_lower = market_question.lower()
    
    # Pattern: "5:15AM-5:30AM", "5:15-5:30", "17:15-17:30"
    time_range_patterns = [
        r'\d{1,2}:\d{2}\s*(?:am|pm)?\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)?',
        r'\d{1,2}:\d{2}-\d{1,2}:\d{2}',
    ]
    
    for pattern in time_range_patterns:
        match = re.search(pattern, title_lower)
        if match:
            # Check if it's a short interval (15-30 min)
            time_str = match.group(0)
            # Simple heuristic: if contains "15" or "30" in the time range
            if '15' in time_str or '30' in time_str or '45' in time_str:
                return True
    
    # Keyword detection
    hft_keywords = [
        'up or down',
        '15 min',
        '30 min',
        'minute interval',
    ]
    
    for keyword in hft_keywords:
        if keyword in title_lower:
            return True
    
    return False

def should_skip_alert(market_question: str, wallet_age_days: int, odds: float, total_activities: int, end_date_str: str = None) -> Tuple[bool, str]:
    """
    Filter out false positives: short-term markets, absurd markets, impossible odds.
    Uses config.py flags: BLOCK_15MIN_MARKETS, BLOCK_SHORT_PRICE_PREDICTIONS
    
    NOTE: We do NOT filter by wallet age - insiders intentionally use new wallets!
    
    Returns:
        (should_skip, reason)
    """
    
    # FILTER 1: 15-MINUTE HFT MARKETS (if enabled in config)
    if BLOCK_15MIN_MARKETS and market_question:
        if is_15min_market(market_question):
            return (True, "HFT_15MIN_MARKET")
    
    # FILTER 2: SHORT-TERM MARKETS
    # Events happening today or tomorrow (high frequency trading, not insider info)
    event_date = None
    
    # Try to extract date from title
    if market_question:
        event_date = extract_event_date_from_title(market_question)
    
    # If no date in title, try endDate
    if not event_date and end_date_str:
        try:
            event_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except:
            pass
    
    # Check if event is today or tomorrow
    if event_date:
        # Use UTC timezone-aware datetime
        now_utc = datetime.now(timezone.utc)
        today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        # Convert event_date to date for comparison
        event_date_only = event_date.date() if event_date.tzinfo else event_date.date()
        tomorrow_date_only = tomorrow.date()
        
        if event_date_only <= tomorrow_date_only:
            # If BLOCK_SHORT_PRICE_PREDICTIONS enabled, block crypto price markets <24h
            if BLOCK_SHORT_PRICE_PREDICTIONS and market_question:
                title_lower = market_question.lower()
                crypto_keywords = ['bitcoin', 'ethereum', 'solana', 'btc', 'eth', 'sol', 'price']
                price_keywords = ['above', 'below', 'less than', 'more than', 'price']
                
                has_crypto = any(kw in title_lower for kw in crypto_keywords)
                has_price = any(kw in title_lower for kw in price_keywords)
                
                if has_crypto and has_price:
                    return (True, f"SHORT_CRYPTO_PRICE (event on {event_date_only.strftime('%Y-%m-%d')})")
            
            # General short-term market filter
            return (True, f"SHORT_TERM_MARKET (event on {event_date_only.strftime('%Y-%m-%d')})")
    
    # FILTER 3: ABSURD MARKETS (blacklist)
    if market_question:
        title_lower = market_question.lower()
        
        # Celebrity/unlikely president markets
        absurd_patterns = [
            r'kardashian.*president',
            r'kanye.*president', 
            r'elon musk.*president',
            r'taylor swift.*president',
            r'youngkin.*202[89].*president',  # Glenn Youngkin unlikely presidential candidate
            
            # Impossible sports outcomes
            r'everton.*(win|champion).*premier league',
            r'wizards.*(win|finals|champion).*(nba|202[6-9])',  # Wizards worst NBA team
            r'pistons.*(win|finals|champion).*(nba|202[6-9])',   # Pistons worst NBA team
            r'hornets.*(win|finals|champion).*(nba|202[6-9])',   # Hornets worst NBA team
            r'blazers.*(win|finals|champion).*(nba|202[6-9])',   # Blazers rebuilding
            r'spurs.*(win|finals|champion).*(nba|202[6-9])',     # Spurs rebuilding
            r'relegated.*win.*league',
            
            # Political impossibilities
            r'liz cheney.*202[89].*nomination',
            r'ventura.*202[6-9].*president',  # Andre Ventura unlikely US president
        ]
        
        for pattern in absurd_patterns:
            if re.search(pattern, title_lower):
                return (True, f"ABSURD_MARKET (matched: {pattern[:30]}...)")
        
        # FILTER 4: IMPOSSIBLE ODDS (>99% on unlikely outcomes)
        # This catches arbitrage bots betting on underdogs at extreme odds
        if odds > 0.99:
            # NBA underdogs at 99%+ for championship = arbitrage
            nba_underdogs = ['wizards', 'pistons', 'hornets', 'blazers', 'spurs', 'raptors', 'nets']
            for team in nba_underdogs:
                # Check if market is about team winning finals/championship
                if team in title_lower:
                    if any(kw in title_lower for kw in ['finals', 'championship', 'win.*202[6-9]']):
                        return (True, f"IMPOSSIBLE_ODDS ({team} at {odds*100:.1f}% for championship)")
            
            # Political long-shots at 99%+
            political_longshots = ['youngkin', 'ventura', 'desantis']
            for candidate in political_longshots:
                if candidate in title_lower and 'president' in title_lower:
                    if any(year in title_lower for year in ['2028', '2029', '2030']):
                        return (True, f"IMPOSSIBLE_ODDS ({candidate} at {odds*100:.1f}% for president)")
    
    # No filters matched - allow alert
    return (False, "")

def calculate_score(trade: Dict, wallet_data: Dict, market: Dict) -> Dict:
    score = 0
    flags = []
    
    print(f"     ── Score Breakdown ──")
    
    wallet_age_score = calculate_wallet_age_score(wallet_data.get("first_activity_timestamp"))
    if wallet_age_score > 0:
        age_days = calculate_wallet_age_days(wallet_data.get("first_activity_timestamp"))
        score += wallet_age_score
        flags.append(f"New wallet ({age_days}d old)")
        print(f"     Wallet age: {age_days}d → +{wallet_age_score} pts")
    else:
        age_days = calculate_wallet_age_days(wallet_data.get("first_activity_timestamp"))
        print(f"     Wallet age: {age_days}d → 0 pts (too old)")
    
    trade_price = float(trade.get("price", 0))
    against_trend_score = calculate_against_trend_score(trade_price)
    if against_trend_score > 0:
        score += against_trend_score
        if trade_price < LOW_ODDS_THRESHOLD:
            flags.append(f"Against trend ({trade_price*100:.1f}% odds)")
            print(f"     Against trend: {trade_price*100:.1f}% → +{against_trend_score} pts (betting underdog)")
        else:  # > 95%
            flags.append(f"Extreme confidence ({trade_price*100:.1f}% odds)")
            print(f"     Extreme confidence: {trade_price*100:.1f}% → +{against_trend_score} pts")
    else:
        print(f"     Odds: {trade_price*100:.1f}% → 0 pts (middle range)")
    
    size = float(trade.get("size", 0))
    amount = size * trade_price
    bet_size_score = calculate_bet_size_score(amount)
    if bet_size_score > 0:
        score += bet_size_score
        flags.append(f"Large bet (${amount:,.0f})")
        print(f"     Bet size: ${amount:,.0f} → +{bet_size_score} pts")
    else:
        print(f"     Bet size: ${amount:,.0f} → 0 pts")
    
    end_date = market.get("endDate")
    timing_score = calculate_timing_score(end_date)
    if timing_score > 0:
        score += timing_score
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            flags.append(f"Close to deadline ({hours:.0f}h)")
            print(f"     Timing: {hours:.0f}h until resolve → +{timing_score} pts")
        except:
            pass
    else:
        try:
            if end_date:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                print(f"     Timing: {hours:.0f}h until resolve → 0 pts (too far)")
            else:
                print(f"     Timing: no end date → 0 pts")
        except:
            print(f"     Timing: invalid date → 0 pts")
    
    total_activities = wallet_data.get("total_count", 0)
    activity_score = calculate_activity_score(total_activities)
    if activity_score > 0:
        score += activity_score
        flags.append(f"Low activity ({total_activities} txns)")
        print(f"     Activity: {total_activities} txns → +{activity_score} pts")
    else:
        print(f"     Activity: {total_activities} txns → 0 pts (too many)")
    
    print(f"     ────────────────────")
    print(f"     TOTAL: {score} pts")
    
    return {
        "score": score,
        "flags": flags,
        "amount": amount,
        "odds": trade_price,
        "wallet_age_days": calculate_wallet_age_days(wallet_data.get("first_activity_timestamp")),
        "total_activities": total_activities
    }
