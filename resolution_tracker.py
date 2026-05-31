"""
Resolution Tracker — Closes the feedback loop.

Runs daily (via GitHub Actions). For each alert in alerts.json:
1. Checks if the market has resolved via Gamma API
2. Records the outcome (YES/NO)
3. Scores: did the insider's bet win?
4. Scores: was the model's mispricing call correct?
5. Saves stats to resolution_stats.json and prints summary to Telegram

This is essential for validating the system.
Without it, we cannot know if our signals are profitable.
"""

import json
import re
import time
import requests
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from config import (
    GAMMA_API_URL, REQUEST_DELAY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    CLOB_API_URL, FLAT_STAKE, EXPIRE_AFTER_DAYS,
)
import trade_economics

ALERTS_PATH = Path("alerts.json")
STATS_PATH = Path("resolution_stats.json")

# Rate limiting
API_DELAY = 0.3  # seconds between API calls (reduced from 0.5)


def load_alerts() -> List[Dict]:
    if ALERTS_PATH.exists():
        with open(ALERTS_PATH) as f:
            return json.load(f)
    return []


def save_alerts(alerts: List[Dict]):
    temp = ALERTS_PATH.with_suffix(".tmp")
    with open(temp, "w") as f:
        json.dump(alerts, f, indent=2)
    temp.replace(ALERTS_PATH)


def load_stats() -> Dict:
    if STATS_PATH.exists():
        with open(STATS_PATH) as f:
            return json.load(f)
    return {
        "last_run": None,
        "total_checked": 0,
        "total_resolved": 0,
        "total_unresolved": 0,
        "insider_wins": 0,
        "insider_losses": 0,
        "model_correct": 0,
        "model_wrong": 0,
        "model_na": 0,
        "by_signal_type": {},
        "by_category": {},
        "history": [],
    }


def save_stats(stats: Dict):
    temp = STATS_PATH.with_suffix(".tmp")
    with open(temp, "w") as f:
        json.dump(stats, f, indent=2)
    temp.replace(STATS_PATH)


def fetch_market_by_condition_id(condition_id: str) -> Optional[Dict]:
    """
    Fetch market by conditionId via Gamma (plural `condition_ids` param).

    The old code used the singular `condition_id` param which Gamma rejects
    with 403. The plural form works and — crucially — returns CLOSED markets
    with no date cutoff, so old resolved markets are still retrievable.
    """
    if not condition_id:
        return None

    url = f"{GAMMA_API_URL}/markets"
    for params in ({"condition_ids": condition_id, "limit": 1},
                   {"condition_id": condition_id, "limit": 1}):  # legacy fallback
        try:
            time.sleep(API_DELAY)
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    market = data[0] if isinstance(data, list) else data
                    returned_cid = (market.get("conditionId") or "").lower()
                    cid = condition_id.lower()
                    if not returned_cid or returned_cid == cid or returned_cid[:20] == cid[:20]:
                        return market
        except Exception:
            pass
    return None


def fetch_market_by_clob(condition_id: str) -> Optional[Dict]:
    """
    Resolution source of last resort: CLOB market endpoint.

    CLOB keeps resolved markets indefinitely and exposes a per-token `winner`
    flag, which is the single most reliable resolution signal for old markets.
    We normalise its shape to look like a Gamma market so determine_resolution
    can consume it unchanged.
    """
    if not condition_id:
        return None
    try:
        time.sleep(API_DELAY)
        resp = requests.get(f"{CLOB_API_URL}/markets/{condition_id}", timeout=15)
        if resp.status_code != 200:
            return None
        m = resp.json()
        tokens = m.get("tokens") or []
        if not tokens:
            return None
        outcomes = [t.get("outcome") for t in tokens]
        # Prefer explicit winner flag; fall back to token price.
        prices = []
        winner_seen = any(t.get("winner") is not None for t in tokens)
        for t in tokens:
            if winner_seen:
                prices.append("1" if t.get("winner") else "0")
            else:
                prices.append(str(t.get("price", 0)))
        return {
            "closed": bool(m.get("closed")),
            "outcomes": outcomes,
            "outcomePrices": prices,
            "conditionId": condition_id,
            "_source": "clob",
        }
    except Exception:
        return None


def fetch_market_by_slug(slug: str) -> Optional[Dict]:
    """Fetch market data from Gamma API by slug."""
    if not slug:
        return None

    url = f"{GAMMA_API_URL}/markets"
    params = {"slug": slug, "limit": 1}

    try:
        time.sleep(API_DELAY)
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return data[0]
    except Exception as e:
        print(f"  ⚠️  API error for slug '{slug[:40]}': {e}")

    # Fallback: try event slug via events endpoint
    try:
        time.sleep(API_DELAY)
        resp = requests.get(f"{GAMMA_API_URL}/events", params={"slug": slug, "limit": 1}, timeout=15)
        if resp.status_code == 200:
            events = resp.json()
            if events and len(events) > 0:
                markets = events[0].get("markets", [])
                if markets:
                    return markets[0]
    except:
        pass

    return None


def fetch_market_by_question(question: str) -> Optional[Dict]:
    """Fallback: search by question text (first 60 chars)."""
    if not question:
        return None

    url = f"{GAMMA_API_URL}/markets"
    # Use closed=true to find resolved markets
    params = {"closed": "true", "limit": 20}

    try:
        time.sleep(API_DELAY)
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            markets = resp.json()
            q_lower = question.lower().strip()
            for m in markets:
                if m.get("question", "").lower().strip() == q_lower:
                    return m
    except Exception as e:
        print(f"  ⚠️  API error searching by question: {e}")

    return None


def determine_resolution(market: Dict) -> Optional[str]:
    """
    Determine winning outcome from market data.
    Returns 'Yes', 'No', or team/player name. None if unresolved.
    """
    if not market:
        return None

    is_closed = market.get("closed", False)

    # Parse outcomes and prices
    outcomes = market.get("outcomes", [])
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except:
            return None

    prices = market.get("outcomePrices", [])
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except:
            return None

    # Method 1: price = 1.0 (fully resolved — works even without resolutionSource)
    for i, p in enumerate(prices):
        try:
            if float(p) >= 0.99 and i < len(outcomes):
                return outcomes[i]
        except:
            pass

    # Method 2: price = 0.0 for all but one (also fully resolved)
    if len(prices) == 2:
        try:
            p0, p1 = float(prices[0]), float(prices[1])
            if p0 <= 0.01 and p1 >= 0.99 and len(outcomes) >= 2:
                return outcomes[1]
            if p1 <= 0.01 and p0 >= 0.99 and len(outcomes) >= 2:
                return outcomes[0]
        except:
            pass

    # Method 3: resolvedOutcome field
    resolved = market.get("resolvedOutcome") or market.get("winner")
    if resolved:
        return resolved

    # Method 4: closed market with clear winner (>90%)
    if is_closed and prices:
        try:
            float_prices = [float(p) for p in prices]
            max_idx = float_prices.index(max(float_prices))
            if max(float_prices) > 0.90 and max_idx < len(outcomes):
                return outcomes[max_idx]
        except:
            pass

    # Not resolved or can't determine
    return None


def check_insider_win(alert: Dict, resolution: str) -> Optional[bool]:
    """
    Did the insider's/trader's bet win?
    Handles both insider alerts (trade_data) and TOP_TRADER alerts (trade).
    """
    # Extract position from either alert format
    trade_data = alert.get("trade_data", {})
    trade = alert.get("trade", {})
    
    # Get outcome: insider alerts use trade_data, TOP_TRADER uses trade
    outcome = trade_data.get("outcome") or trade.get("outcome", "Yes")
    normalized = trade_data.get("normalized_position")  # YES or NO from detector

    position = str(outcome).strip()
    resolved = str(resolution).strip()

    # 1. Binary resolution (Yes/No)
    if resolved.lower() in ("yes", "no"):
        if normalized:
            return normalized.lower() == resolved.lower()
        if position.lower() in ("yes", "no"):
            return position.lower() == resolved.lower()
        if position.lower() == "over":
            return resolved.lower() == "yes"
        if position.lower() == "under":
            return resolved.lower() == "no"
        return None

    # 2. Named resolution (team/player name)
    if position.lower() == resolved.lower():
        return True
    if position.lower() in resolved.lower() or resolved.lower() in position.lower():
        return True
    if position.lower() in ("yes", "no", "over", "under"):
        return None

    return False


def _extract_position(alert: Dict) -> Tuple[float, float, str]:
    """Return (size_tokens, yes_price, outcome) from either alert format."""
    td = alert.get("trade_data", {}) or {}
    tr = alert.get("trade", {}) or {}
    outcome = td.get("outcome") or tr.get("outcome", "Yes")
    yes_price = float(td.get("price", 0) or tr.get("price", 0) or 0)
    # size in tokens; fall back to amount/price if only $ amount is stored
    size = float(td.get("size", 0) or tr.get("size", 0) or 0)
    if size <= 0:
        amount = float(td.get("amount", 0) or alert.get("amount", 0) or 0)
        if amount > 0 and 0 < yes_price < 1:
            eff = (1 - yes_price) if str(outcome).lower() == "no" else yes_price
            size = amount / eff if eff > 0 else 0
    return size, yes_price, str(outcome)


def calculate_pnl(alert: Dict, insider_win: Optional[bool]) -> Optional[float]:
    """
    Notional P&L — what the WHALE made/lost. Kept for backwards compatibility,
    but corrected to use effective odds (NO bets were mispriced before).
    Use calculate_pnls() for the honest picture.
    """
    pnls = calculate_pnls(alert, insider_win)
    return pnls["notional"] if pnls else None


def calculate_pnls(alert: Dict, insider_win: Optional[bool]) -> Optional[Dict]:
    """
    Single source of truth for resolved P&L.

    Returns:
        notional   — P&L at the whale's stake (informational only)
        flat       — P&L at OUR fixed FLAT_STAKE (the number that reflects edge)
        roi        — return on our stake, % (win → +x%, loss → -100%)
        eff_odds   — price actually paid for the chosen side
    """
    if insider_win is None:
        return None

    size, yes_price, outcome = _extract_position(alert)
    if yes_price <= 0 or yes_price >= 1:
        return None

    econ = trade_economics.calculate(size=max(size, 0.0), price=yes_price, outcome=outcome)
    eff = econ.effective_odds
    if eff <= 0:
        return None

    if insider_win:
        notional = round(econ.cost * (1.0 / eff - 1.0), 2)
        flat = round(FLAT_STAKE * (1.0 / eff - 1.0), 2)
        roi = round((1.0 / eff - 1.0) * 100, 1)
    else:
        notional = round(-econ.cost, 2)
        flat = round(-FLAT_STAKE, 2)
        roi = -100.0

    return {"notional": notional, "flat": flat, "roi": roi, "eff_odds": round(eff, 4)}


def check_model_correct(alert: Dict, resolution: str) -> Optional[bool]:
    """
    Was the model's mispricing assessment correct?

    Model says 'YES overpriced' (edge > 0) → correct if resolved NO.
    Model says 'NO overpriced' (edge < 0) → correct if resolved YES.
    No edge → N/A.
    """
    mispricing = alert.get("mispricing", {})
    edge = mispricing.get("edge", 0)

    if not edge or abs(edge) < 0.01:
        return None  # No opinion

    resolved_lower = str(resolution).lower()

    if resolved_lower not in ["yes", "no"]:
        return None  # Can't evaluate for non-binary

    if edge > 0:
        # Model says YES overpriced → should resolve NO
        return resolved_lower == "no"
    else:
        # Model says NO overpriced → should resolve YES
        return resolved_lower == "yes"


def update_by_bucket(stats: Dict, bucket_key: str, bucket_name: str, insider_win: Optional[bool], model_correct: Optional[bool]):
    """Update stats for a specific bucket (signal_type, category, etc.)."""
    bucket = stats.setdefault(bucket_key, {})
    entry = bucket.setdefault(bucket_name, {
        "total": 0, "insider_wins": 0, "insider_losses": 0,
        "model_correct": 0, "model_wrong": 0, "model_na": 0,
    })
    entry["total"] += 1

    if insider_win is True:
        entry["insider_wins"] += 1
    elif insider_win is False:
        entry["insider_losses"] += 1

    if model_correct is True:
        entry["model_correct"] += 1
    elif model_correct is False:
        entry["model_wrong"] += 1
    else:
        entry["model_na"] += 1


def run_resolution_check():
    print(f"[{datetime.now()}] ═══════════════════════════════")
    print(f"[{datetime.now()}] RESOLUTION TRACKER")
    print(f"[{datetime.now()}] ═══════════════════════════════")

    alerts = load_alerts()
    stats = load_stats()

    if not alerts:
        print("No alerts to check.")
        return

    # Only check alerts that don't have resolution yet
    unchecked = [a for a in alerts if not a.get("resolution")]
    print(f"Total alerts: {len(alerts)}, unchecked: {len(unchecked)}")

    if not unchecked:
        print("All alerts already resolved or checked.")
        return

    newly_resolved = 0
    still_open = 0
    api_errors = 0
    expired_count = 0
    found_by_method = {"conditionId": 0, "slug": 0, "event_slug": 0, "question": 0, "clob": 0}

    # ══════════════════════════════════════════
    # PHASE 1: parse a market date per alert (age hint only — NOT a cutoff)
    # The old code blind-expired anything >7 days old BEFORE calling the API,
    # which silently discarded ~62% of all signals. We now resolve regardless
    # of age and only expire after every source genuinely fails (PHASE 2).
    # ══════════════════════════════════════════
    def _alert_age_days(alert: Dict) -> Optional[int]:
        td = alert.get("trade_data", {}) or {}
        tr = alert.get("trade", {}) or {}
        all_text = ' '.join(filter(None, [
            alert.get("market_slug", ""), td.get("slug", ""), td.get("eventSlug", ""),
            tr.get("slug", ""), tr.get("eventSlug", ""), alert.get("market", "")
        ]))
        m = re.search(r'(\d{4}-\d{2}-\d{2})', all_text)
        if not m:
            return None
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
            return (datetime.utcnow() - d).days
        except Exception:
            return None

    remaining = list(unchecked)

    # ══════════════════════════════════════════
    # PHASE 2: Check remaining via API
    # ══════════════════════════════════════════
    # De-duplicate by market to avoid redundant API calls
    lookup_cache: Dict[str, Optional[Dict]] = {}

    for i, alert in enumerate(remaining):
        # Extract all possible lookup keys
        slug = alert.get("market_slug", "")
        event_slug = alert.get("event_slug", "")
        market_question = alert.get("market", "")
        
        # conditionId: different location for insider vs TOP_TRADER
        condition_id = ""
        trade_data = alert.get("trade_data", {})
        trade = alert.get("trade", {})
        if trade_data.get("conditionId"):
            condition_id = trade_data["conditionId"]
        elif trade.get("conditionId"):
            condition_id = trade["conditionId"]
        
        # Collect ALL available slugs (some alerts have slug in multiple places)
        all_slugs = []
        for s in [slug, event_slug, 
                  trade_data.get("slug", ""), trade_data.get("eventSlug", ""),
                  trade.get("slug", ""), trade.get("eventSlug", "")]:
            if s and s not in all_slugs:
                all_slugs.append(s)
        
        # Also try slug with trailing numbers stripped (e.g., "nba-nyk-lal-2026-03-08-total-2" → "nba-nyk-lal-2026-03-08-total")
        for s in list(all_slugs):
            cleaned = re.sub(r'-\d{1,4}$', '', s)
            if cleaned and cleaned != s and cleaned not in all_slugs:
                all_slugs.append(cleaned)

        # Build cache key from best available identifier
        cache_key = condition_id or (all_slugs[0] if all_slugs else "") or market_question[:60]
        
        if not cache_key:
            api_errors += 1
            continue

        # Try cache first
        if cache_key in lookup_cache:
            market_data = lookup_cache[cache_key]
        else:
            market_data = None
            found_method = None
            
            # Cascade: conditionId → all slugs → question
            if condition_id:
                market_data = fetch_market_by_condition_id(condition_id)
                if market_data:
                    found_method = "conditionId"
            
            if not market_data:
                for s in all_slugs:
                    market_data = fetch_market_by_slug(s)
                    if market_data:
                        found_method = "slug"
                        break
            
            if not market_data and market_question:
                market_data = fetch_market_by_question(market_question)
                if market_data:
                    found_method = "question"

            # Last resort: CLOB winner flag (keeps old resolved markets forever)
            if not market_data and condition_id:
                market_data = fetch_market_by_clob(condition_id)
                if market_data:
                    found_method = "clob"

            lookup_cache[cache_key] = market_data
            if found_method:
                found_by_method[found_method] = found_by_method.get(found_method, 0) + 1

        if not market_data:
            api_errors += 1
            age = _alert_age_days(alert)
            # Only now — after conditionId, all slugs, question AND CLOB failed —
            # do we give up, and only for markets old enough to be truly gone.
            if age is not None and age > EXPIRE_AFTER_DAYS:
                alert["resolution"] = {
                    "outcome": "EXPIRED",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "insider_win": None,
                    "model_correct": None,
                    "pnl": None,
                    "note": f"Unresolvable after all sources; {age}d old",
                }
                stats["model_na"] = stats.get("model_na", 0) + 1
                expired_count += 1
            else:
                # Recent market not found yet — leave unchecked, retry next run.
                alert["resolution_last_check"] = datetime.now(timezone.utc).isoformat()
            if api_errors <= 5:
                atype = alert.get("combined_signal", {}).get("signal_type") or alert.get("type", "?")
                print(f"  ❌ NOT FOUND [{atype}]: cid={condition_id[:20]}, q={market_question[:40]}")
            continue

        resolution = determine_resolution(market_data)

        if resolution:
            # Market is resolved!
            insider_win = check_insider_win(alert, resolution)
            model_correct = check_model_correct(alert, resolution)
            pnls = calculate_pnls(alert, insider_win)
            pnl = pnls["notional"] if pnls else None
            pnl_flat = pnls["flat"] if pnls else None

            # Store resolution in the alert itself
            alert["resolution"] = {
                "outcome": resolution,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "insider_win": insider_win,
                "model_correct": model_correct,
                "pnl": pnl,
                "pnl_flat": pnl_flat,
                "roi": pnls["roi"] if pnls else None,
                "source": market_data.get("_source", "gamma"),
            }

            # Update global stats
            stats["total_resolved"] += 1
            if insider_win is True:
                stats["insider_wins"] += 1
            elif insider_win is False:
                stats["insider_losses"] += 1

            if model_correct is True:
                stats["model_correct"] += 1
            elif model_correct is False:
                stats["model_wrong"] += 1
            else:
                stats["model_na"] += 1

            # P&L tracking
            if pnl is not None:
                stats["total_pnl"] = round(stats.get("total_pnl", 0) + pnl, 2)
            if pnl_flat is not None:
                stats["total_pnl_flat"] = round(stats.get("total_pnl_flat", 0) + pnl_flat, 2)

            # Update per-signal-type and per-category
            signal_type = alert.get("combined_signal", {}).get("signal_type") or alert.get("type", "UNKNOWN")
            category = alert.get("irrationality", {}).get("category", "unknown")

            update_by_bucket(stats, "by_signal_type", signal_type, insider_win, model_correct)
            update_by_bucket(stats, "by_category", category, insider_win, model_correct)
            
            # Track AI verdict accuracy (Grok only now)
            ai_verdict = alert.get("ai_verdict", "NONE")
            if ai_verdict != "NONE":
                update_by_bucket(stats, "by_ai_verdict", ai_verdict, insider_win, model_correct)

            newly_resolved += 1
            position = alert.get("trade_data", {}).get("outcome") or alert.get("trade", {}).get("outcome", "?")
            amount = float(alert.get("trade_data", {}).get("amount", 0) or alert.get("amount", 0) or 0)
            signal_type = alert.get("combined_signal", {}).get("signal_type") or alert.get("type", "?")
            win_str = "✅" if insider_win else ("❌" if insider_win is False else "❓")
            pnl_str = f"${pnl:+,.0f}" if pnl is not None else "?"
            print(f"  [{newly_resolved}] {market_question[:55]}")
            print(f"       {signal_type} | {position} ${amount:,.0f} | Resolved: {resolution} | {win_str} {pnl_str}")
        else:
            still_open += 1
            # Debug: show first 5 still-open to check if they're actually resolved
            if still_open <= 5:
                closed = market_data.get("closed", False)
                res_source = market_data.get("resolutionSource", "")
                end_date = market_data.get("endDate", "")[:10]
                outcomes = market_data.get("outcomes", [])
                prices = market_data.get("outcomePrices", [])
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except: pass
                if isinstance(prices, str):
                    try: prices = json.loads(prices)
                    except: pass
                print(f"  ⏳ STILL OPEN: {market_question[:50]}")
                print(f"       closed={closed}, resSource={res_source[:30] if res_source else 'None'}, end={end_date}")
                print(f"       outcomes={outcomes[:3]}, prices={str(prices)[:60]}")
            # Mark as checked so we don't spam the API
            alert.setdefault("resolution_last_check", datetime.now(timezone.utc).isoformat())

        stats["total_checked"] += 1

    # Save
    stats["last_run"] = datetime.now(timezone.utc).isoformat()

    # Append to history for trend tracking
    stats.setdefault("history", []).append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "newly_resolved": newly_resolved,
        "still_open": still_open,
        "total_resolved": stats["total_resolved"],
        "insider_wins": stats["insider_wins"],
        "insider_losses": stats["insider_losses"],
        "model_correct": stats["model_correct"],
        "model_wrong": stats["model_wrong"],
    })

    # Keep last 90 days of history
    stats["history"] = stats["history"][-90:]

    save_alerts(alerts)
    save_stats(stats)

    # Print summary
    print()
    print(f"[{datetime.now()}] ═══════════════════════════════")
    print(f"[{datetime.now()}] RESOLUTION SUMMARY")
    print(f"[{datetime.now()}] ═══════════════════════════════")
    print(f"  Newly resolved: {newly_resolved}")
    print(f"  Still open: {still_open}")
    print(f"  API errors (not found): {api_errors}")
    print(f"  Found by: {found_by_method}")
    print()

    total_resolved = stats["insider_wins"] + stats["insider_losses"]
    if total_resolved > 0:
        insider_wr = stats["insider_wins"] / total_resolved * 100
        print(f"  INSIDER WIN RATE: {stats['insider_wins']}/{total_resolved} ({insider_wr:.1f}%)")
    else:
        print(f"  INSIDER WIN RATE: no data yet")

    total_pnl_flat = stats.get("total_pnl_flat", 0)
    determined = stats["insider_wins"] + stats["insider_losses"]
    roi = (total_pnl_flat / (determined * FLAT_STAKE) * 100) if determined else 0
    print(f"  REAL P&L (${FLAT_STAKE:.0f}/bet flat): ${total_pnl_flat:+,.2f} · ROI {roi:+.1f}%")
    total_pnl = stats.get("total_pnl", 0)
    print(f"  P&L notional (whale, informational): ${total_pnl:+,.0f}")

    total_model = stats["model_correct"] + stats["model_wrong"]
    if total_model > 0:
        model_acc = stats["model_correct"] / total_model * 100
        print(f"  MODEL ACCURACY: {stats['model_correct']}/{total_model} ({model_acc:.1f}%)")
    else:
        print(f"  MODEL ACCURACY: no data yet")

    # Per signal type
    if stats.get("by_signal_type"):
        print()
        print("  BY SIGNAL TYPE:")
        for st, data in sorted(stats["by_signal_type"].items()):
            total = data["insider_wins"] + data["insider_losses"]
            if total > 0:
                wr = data["insider_wins"] / total * 100
                print(f"    {st}: {data['insider_wins']}/{total} ({wr:.1f}% win rate)")
            else:
                print(f"    {st}: {data['total']} alerts, no resolved data")

    # Per AI verdict
    if stats.get("by_ai_verdict"):
        print()
        print("  BY AI VERDICT:")
        for v, data in sorted(stats["by_ai_verdict"].items()):
            total = data["insider_wins"] + data["insider_losses"]
            if total > 0:
                wr = data["insider_wins"] / total * 100
                print(f"    AI_{v}: {data['insider_wins']}/{total} ({wr:.1f}% win rate)")

    # Send Telegram summary if there were new resolutions
    # Send daily summary (always — even without new resolutions)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_resolution_summary(stats, newly_resolved)

    return stats


def send_resolution_summary(stats: Dict, newly_resolved: int):
    """Send daily resolution summary to Telegram."""
    wins = stats["insider_wins"]
    losses = stats["insider_losses"]
    determined = wins + losses
    total_resolved = stats["total_resolved"]

    msg = f"📊 STATS"
    if newly_resolved > 0:
        msg += f" · +{newly_resolved} new"
    msg += f" · {total_resolved} total\n\n"

    if determined > 0:
        wr = wins / determined * 100
        flat = stats.get("total_pnl_flat", 0)
        roi = flat / (determined * FLAT_STAKE) * 100
        msg += f"WR: {wr:.0f}% ({wins}W/{losses}L)\n"
        msg += f"💵 Real P&L (${FLAT_STAKE:.0f}/bet): ${flat:+,.2f} · ROI {roi:+.0f}%"
    else:
        msg += "No resolved data yet"

    # Per-signal breakdown
    by_st = stats.get("by_signal_type", {})
    parts = []
    for st in ["ALPHA", "CONFLICT", "INSIDER_ONLY", "TOP_TRADER"]:
        data = by_st.get(st, {})
        w = data.get("insider_wins", 0)
        l = data.get("insider_losses", 0)
        t = w + l
        if t >= 3:
            parts.append(f"{st}: {w/t*100:.0f}%")
    if parts:
        msg += "\n" + " · ".join(parts)

    # AI verdict
    by_ai = stats.get("by_ai_verdict", {})
    ai_parts = []
    for v in ["COPY", "SKIP"]:
        data = by_ai.get(v, {})
        w = data.get("insider_wins", 0)
        l = data.get("insider_losses", 0)
        t = w + l
        if t >= 3:
            ai_parts.append(f"AI_{v}: {w/t*100:.0f}%")
    if ai_parts:
        msg += "\n🤖 " + " · ".join(ai_parts)

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "disable_notification": True,
        }, timeout=10)
        print("✓ Resolution summary sent to Telegram")
    except Exception as e:
        print(f"⚠️  Failed to send Telegram summary: {e}")


def _fresh_stats() -> Dict:
    return {
        "last_run": None, "total_checked": 0, "total_resolved": 0, "total_unresolved": 0,
        "insider_wins": 0, "insider_losses": 0, "model_correct": 0, "model_wrong": 0,
        "model_na": 0, "total_pnl": 0.0, "total_pnl_flat": 0.0,
        "by_signal_type": {}, "by_category": {}, "by_ai_verdict": {}, "history": [],
    }


def rebuild_stats_from_alerts() -> Dict:
    """
    Recompute resolution_stats.json from scratch using resolutions already
    stored on disk in alerts.json — with corrected odds and flat-stake P&L.
    No network needed. This is the honest reset after the EXPIRED bug.
    """
    alerts = load_alerts()
    stats = _fresh_stats()

    for alert in alerts:
        res = alert.get("resolution")
        if not isinstance(res, dict):
            continue
        outcome = res.get("outcome")
        if outcome in (None, "EXPIRED"):
            stats["model_na"] += 1
            continue

        # Recompute from raw position so old buggy NO-odds P&L is corrected.
        insider_win = check_insider_win(alert, outcome)
        model_correct = check_model_correct(alert, outcome)
        pnls = calculate_pnls(alert, insider_win)

        stats["total_resolved"] += 1
        if insider_win is True:
            stats["insider_wins"] += 1
        elif insider_win is False:
            stats["insider_losses"] += 1
        if model_correct is True:
            stats["model_correct"] += 1
        elif model_correct is False:
            stats["model_wrong"] += 1
        else:
            stats["model_na"] += 1
        if pnls:
            stats["total_pnl"] = round(stats["total_pnl"] + pnls["notional"], 2)
            stats["total_pnl_flat"] = round(stats["total_pnl_flat"] + pnls["flat"], 2)

        signal_type = alert.get("combined_signal", {}).get("signal_type") or alert.get("type", "UNKNOWN")
        category = alert.get("irrationality", {}).get("category", "unknown")
        update_by_bucket(stats, "by_signal_type", signal_type, insider_win, model_correct)
        update_by_bucket(stats, "by_category", category, insider_win, model_correct)
        ai_verdict = alert.get("ai_verdict", "NONE")
        if ai_verdict != "NONE":
            update_by_bucket(stats, "by_ai_verdict", ai_verdict, insider_win, model_correct)

    stats["last_run"] = datetime.now(timezone.utc).isoformat()
    save_stats(stats)

    det = stats["insider_wins"] + stats["insider_losses"]
    wr = stats["insider_wins"] / det * 100 if det else 0
    print(f"REBUILT from {len(alerts)} alerts → {det} resolved")
    print(f"  WR: {stats['insider_wins']}W/{stats['insider_losses']}L ({wr:.1f}%)")
    print(f"  P&L flat (${FLAT_STAKE:.0f}/bet): ${stats['total_pnl_flat']:+,.2f}  "
          f"| ROI {stats['total_pnl_flat']/(det*FLAT_STAKE)*100:+.1f}%" if det else "")
    print(f"  P&L notional (whale, informational): ${stats['total_pnl']:+,.0f}")
    return stats


def retry_expired() -> int:
    """Clear resolution on wrongly-EXPIRED alerts so the next run re-resolves them."""
    alerts = load_alerts()
    n = 0
    for a in alerts:
        res = a.get("resolution")
        if isinstance(res, dict) and res.get("outcome") == "EXPIRED" and res.get("insider_win") is None:
            a.pop("resolution", None)
            a.pop("resolution_last_check", None)
            n += 1
    save_alerts(alerts)
    print(f"Re-queued {n} previously-EXPIRED alerts for resolution.")
    return n


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "rebuild":
        rebuild_stats_from_alerts()
    elif cmd == "retry-expired":
        retry_expired()
    else:
        run_resolution_check()
