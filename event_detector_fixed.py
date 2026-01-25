from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
import re
from functools import lru_cache

# FIX BUG #1 & #7: Copy extract_event_date_from_title to avoid circular import
# Previously imported from analyzer, causing circular dependency

@lru_cache(maxsize=100)
def extract_event_date_from_title(title: str) -> Optional[datetime]:
    """
    Extract event date from market title.
    Patterns: "2026-01-19", "January 19", "Jan 19", "19.01.2026", etc.
    Returns timezone-aware datetime in UTC.
    
    FIX BUG #7: Copied from analyzer.py to avoid circular import.
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
            
            # If month already passed this year, use next year
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
            
            # If month already passed this year, use next year
            current_month = datetime.now().month
            if month_num < current_month:
                year += 1
            
            try:
                return datetime(year, month_num, day, tzinfo=timezone.utc)
            except:
                pass
    
    return None

def extract_event_timestamp(market_question: str, market_end_date: str = None) -> Optional[datetime]:
    """
    Extract event timestamp from market question or end date.
    
    For Phase 1: Use market end date as proxy for event time.
    Phase 2: Integrate news API for actual event timestamps.
    
    Returns timezone-aware datetime in UTC.
    """
    # Method 1: Use market end date if available
    if market_end_date:
        try:
            event_time = datetime.fromisoformat(market_end_date.replace("Z", "+00:00"))
            return event_time
        except:
            pass
    
    # Method 2: Extract date from question using copied function
    event_date = extract_event_date_from_title(market_question)
    if event_date:
        return event_date
    
    # Method 3: Real-time markets (event is "now")
    # E.g., "Bitcoin above $105k right now"
    realtime_keywords = ['right now', 'currently', 'at the moment', 'as of now']
    if any(kw in market_question.lower() for kw in realtime_keywords):
        return datetime.now(timezone.utc)
    
    return None

def calculate_event_latency(trade_timestamp: int, event_timestamp: datetime) -> Optional[Dict]:
    """
    Calculate latency between trade and event.
    FIX BUG #8: Ensure timezone-aware datetime handling.
    
    Returns:
        {
            'latency_seconds': float,
            'latency_minutes': float,
            'is_pre_event': bool,
            'severity': str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
        }
    """
    if not event_timestamp:
        return None
    
    # FIX BUG #8: Convert trade timestamp to timezone-aware datetime
    trade_time = datetime.fromtimestamp(trade_timestamp, tz=timezone.utc)
    
    # Calculate latency (positive = before event, negative = after event)
    latency_seconds = (event_timestamp - trade_time).total_seconds()
    latency_minutes = latency_seconds / 60
    
    # Determine if pre-event
    is_pre_event = latency_seconds > 0
    
    # Classify severity
    if not is_pre_event:
        severity = 'NONE'  # After event
    elif latency_seconds >= 1800:  # 30+ minutes
        severity = 'CRITICAL'
    elif latency_seconds >= 600:   # 10+ minutes
        severity = 'HIGH'
    elif latency_seconds >= 300:   # 5+ minutes
        severity = 'MEDIUM'
    else:
        severity = 'LOW'
    
    return {
        'latency_seconds': latency_seconds,
        'latency_minutes': latency_minutes,
        'is_pre_event': is_pre_event,
        'severity': severity,
        'trade_time': trade_time.isoformat(),
        'event_time': event_timestamp.isoformat()
    }

def detect_pre_event_trade(trade: Dict, market: Dict) -> Optional[Dict]:
    """
    Main function to detect if trade is before event.
    
    Returns latency analysis or None if not pre-event.
    """
    # Extract event timestamp
    event_timestamp = extract_event_timestamp(
        market.get('question', ''),
        market.get('endDate')
    )
    
    if not event_timestamp:
        return None
    
    # Calculate latency
    trade_timestamp = trade.get('timestamp')
    if not trade_timestamp:
        return None
    
    latency = calculate_event_latency(trade_timestamp, event_timestamp)
    
    # Only return if pre-event with significant latency
    if latency and latency['is_pre_event'] and latency['severity'] != 'NONE':
        return latency
    
    return None

def get_latency_insight(latency_data: Dict) -> str:
    """
    Generate human-readable insight about latency advantage.
    """
    if not latency_data or not latency_data.get('is_pre_event'):
        return ""
    
    minutes = abs(latency_data['latency_minutes'])
    severity = latency_data['severity']
    
    if severity == 'CRITICAL':
        return f"⚠️ EXTREME PRE-EVENT: Trade placed {minutes:.0f} minutes BEFORE event"
    elif severity == 'HIGH':
        return f"🚨 HIGH PRE-EVENT: Trade placed {minutes:.0f} minutes before event"
    elif severity == 'MEDIUM':
        return f"⚡ MEDIUM PRE-EVENT: Trade placed {minutes:.0f} minutes before event"
    else:
        return f"⏰ Trade placed {minutes:.0f} minutes before event"

def calculate_latency_score(latency_seconds: float) -> int:
    """
    Calculate score contribution from latency (0-40 points).
    
    Scoring:
    - 30+ min: 40 points (CRITICAL)
    - 20-30 min: 35 points
    - 10-20 min: 30 points
    - 5-10 min: 20 points
    - 2-5 min: 10 points
    - <2 min: 0 points
    """
    if latency_seconds < 0:  # After event
        return 0
    
    minutes = latency_seconds / 60
    
    if minutes >= 30:
        return 40
    elif minutes >= 20:
        return 35
    elif minutes >= 10:
        return 30
    elif minutes >= 5:
        return 20
    elif minutes >= 2:
        return 10
    else:
        return 0

def is_realtime_market(market_question: str) -> bool:
    """
    Detect if market is about real-time events (not pre-event opportunity).
    
    Examples:
    - "Bitcoin price right now"
    - "Current weather in NYC"
    - "Live game score"
    """
    realtime_keywords = [
        'right now', 'currently', 'at the moment', 'live',
        'real-time', 'real time', 'as of now', 'instant'
    ]
    
    question_lower = market_question.lower()
    return any(kw in question_lower for kw in realtime_keywords)

def should_skip_realtime_market(market_question: str) -> bool:
    """
    Filter out real-time markets where pre-event concept doesn't apply.
    """
    return is_realtime_market(market_question)

# NEWS API INTEGRATION (Phase 2 - placeholder for now)
def get_news_timestamp(market_question: str, event_keywords: list = None) -> Optional[datetime]:
    """
    Phase 2: Get actual event timestamp from news API.
    
    Integration ideas:
    - Twitter API: Search tweets with keywords, get earliest timestamp
    - NewsAPI: Search articles, get published timestamp
    - RSS feeds: Parse feeds for event mentions
    - Sports APIs: Get injury/trade timestamps
    
    For now: Returns None (use market end date instead)
    """
    # TODO: Implement in Phase 2
    return None

# MARKET-SPECIFIC EVENT DETECTORS (Phase 2 expansions)

def detect_sports_event(market_question: str) -> Optional[datetime]:
    """
    Phase 2: Detect sports events via APIs.
    
    APIs:
    - ESPN API
    - TheOddsAPI
    - Sports injury feeds
    """
    # TODO: Implement sports-specific detection
    return None

def detect_political_event(market_question: str) -> Optional[datetime]:
    """
    Phase 2: Detect political events via news.
    
    Sources:
    - Twitter political accounts
    - Bloomberg
    - Reuters
    """
    # TODO: Implement political event detection
    return None

def detect_crypto_event(market_question: str) -> Optional[datetime]:
    """
    Phase 2: Detect crypto events.
    
    Sources:
    - CoinDesk
    - CryptoCompare
    - On-chain analytics
    """
    # TODO: Implement crypto event detection
    return None
