"""
Trader Performance Tracker — individual trader scoring.

Based on 71x Polymarket engineer insights + our 305 resolved data:
- Top leaderboard ≠ good to copy (Theo4 #1 = 42% WR in our data)
- Category specialization matters (sport ALPHA = 83%)
- Consistency > absolute PnL
- Filter out proven losers (GamblingIsAllYouNeed 17%, RepTrump 0%)

Tracks per-trader stats from resolution_stats.json.
"""

import json
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import defaultdict


STATS_PATH = Path("resolution_stats.json")
ALERTS_PATH = Path("alerts.json")

# Minimum trades before filtering
MIN_TRADES_FOR_FILTER = 5

# Below this WR on MIN_TRADES, trader is blacklisted
BAD_TRADER_WR = 0.35

# Below this WR in a category, skip that category for this trader
BAD_CATEGORY_WR = 0.30
MIN_CATEGORY_TRADES = 3


def build_trader_stats() -> Dict[str, Dict]:
    """
    Build per-trader performance from resolved alerts.
    Returns: {username: {wins, losses, total, wr, by_category: {cat: {w, l}}}}
    """
    try:
        with open(ALERTS_PATH) as f:
            alerts = json.load(f)
    except:
        return {}
    
    traders = defaultdict(lambda: {
        "wins": 0, "losses": 0,
        "by_category": defaultdict(lambda: {"w": 0, "l": 0}),
        "total_pnl": 0,
    })
    
    for a in alerts:
        if a.get("type") != "TOP_TRADER":
            continue
        res = a.get("resolution")
        if not res:
            continue
        
        win = res.get("insider_win")
        if win is None:
            continue
        
        pnl = res.get("pnl", 0) or 0
        
        # Get trader name
        trader_info = a.get("trader", {})
        username = trader_info.get("username", "")
        if not username:
            wallet = a.get("wallet", "")
            username = wallet[:10] if wallet else "unknown"
        
        # Categorize market
        market = (a.get("market", "") or "").lower()
        if any(kw in market for kw in ["nba", "nfl", "mlb", "nhl", "epl", "mls",
                                         "ufc", "vs.", "o/u", "spread", "win on"]):
            cat = "sports"
        elif any(kw in market for kw in ["counter-strike", "lol:", "dota", "valorant",
                                           "league of legends"]):
            cat = "esports"
        elif any(kw in market for kw in ["bitcoin", "ethereum", "crypto", "btc",
                                           "up or down"]):
            cat = "crypto"
        elif any(kw in market for kw in ["president", "election", "trump", "congress",
                                           "ceasefire", "iran", "military"]):
            cat = "politics"
        else:
            cat = "other"
        
        if win:
            traders[username]["wins"] += 1
            traders[username]["by_category"][cat]["w"] += 1
        else:
            traders[username]["losses"] += 1
            traders[username]["by_category"][cat]["l"] += 1
        
        traders[username]["total_pnl"] += pnl
    
    # Compute WR
    result = {}
    for name, d in traders.items():
        total = d["wins"] + d["losses"]
        wr = d["wins"] / total if total > 0 else 0.5
        
        cat_stats = {}
        for cat, cd in d["by_category"].items():
            ct = cd["w"] + cd["l"]
            cat_stats[cat] = {
                "w": cd["w"], "l": cd["l"], "total": ct,
                "wr": cd["w"] / ct if ct > 0 else 0.5
            }
        
        result[name] = {
            "wins": d["wins"],
            "losses": d["losses"],
            "total": total,
            "wr": wr,
            "pnl": d["total_pnl"],
            "by_category": cat_stats,
        }
    
    return result


def should_skip_trader(username: str, market_title: str, 
                        trader_stats: Dict[str, Dict]) -> Optional[str]:
    """
    Check if we should skip this trader's signal.
    
    Returns:
        None if OK to alert
        String reason if should skip
    """
    stats = trader_stats.get(username)
    if not stats:
        return None  # New trader, no data yet
    
    total = stats["total"]
    wr = stats["wr"]
    
    # Filter 1: Trader has bad overall WR on enough trades
    if total >= MIN_TRADES_FOR_FILTER and wr < BAD_TRADER_WR:
        return f"BAD_TRADER: {username} WR={wr*100:.0f}% on {total} trades"
    
    # Filter 2: Trader is bad in this specific category
    market_lower = market_title.lower()
    if any(kw in market_lower for kw in ["nba", "nfl", "mlb", "nhl", "epl", "mls",
                                           "ufc", "vs.", "o/u", "spread", "win on"]):
        cat = "sports"
    elif any(kw in market_lower for kw in ["counter-strike", "lol:", "dota", "valorant"]):
        cat = "esports"
    elif any(kw in market_lower for kw in ["bitcoin", "ethereum", "crypto"]):
        cat = "crypto"
    elif any(kw in market_lower for kw in ["president", "election", "ceasefire", "iran"]):
        cat = "politics"
    else:
        cat = "other"
    
    cat_data = stats.get("by_category", {}).get(cat)
    if cat_data and cat_data["total"] >= MIN_CATEGORY_TRADES:
        if cat_data["wr"] < BAD_CATEGORY_WR:
            return f"BAD_CATEGORY: {username} WR={cat_data['wr']*100:.0f}% in {cat} ({cat_data['total']} trades)"
    
    return None


def format_trader_quality(username: str, trader_stats: Dict[str, Dict]) -> str:
    """Short quality indicator for alerts."""
    stats = trader_stats.get(username)
    if not stats or stats["total"] < MIN_TRADES_FOR_FILTER:
        return ""
    
    wr = stats["wr"]
    if wr >= 0.60:
        return f"🟢 {wr*100:.0f}% trader WR"
    elif wr >= 0.45:
        return f"🟡 {wr*100:.0f}% trader WR"
    else:
        return f"🔴 {wr*100:.0f}% trader WR"
