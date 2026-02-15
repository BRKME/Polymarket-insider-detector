# VERSION: 2026-01-31-HOTFIX-17:15-UTC
# CRITICAL FIX: NO position calculation
# Force reload to clear any cached bytecode
import sys
sys.dont_write_bytecode = True

# Debug flag - will print calculation details to logs
DEBUG_CALCULATIONS = True

import requests
from openai import OpenAI
import openai
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY
from typing import Dict, Optional
from functools import lru_cache
import hashlib

def determine_position(trade_data, odds):
    """Determine YES/NO position from trade data"""
    if trade_data:
        outcome = trade_data.get('outcome')
        if outcome:
            outcome_lower = str(outcome).lower()
            if 'yes' in outcome_lower:
                return 'YES'
            if 'no' in outcome_lower:
                return 'NO'
    
    # Fallback
    return '~YES' if odds > 0.5 else '~NO'

def format_trade_info(alert):
    """Format trade information with correct profit calculation"""
    # Print version to confirm this code is running
    if DEBUG_CALCULATIONS:
        print(f"[DEBUG] format_trade_info() called - VERSION: 2026-01-31-HOTFIX-17:15-UTC")
    
    analysis = alert["analysis"]
    trade_data = alert.get("trade_data", {})
    
    odds = analysis['odds']  # YES token price (always!)
    amount = analysis['amount']
    yes_price = odds
    no_price = 1 - odds
    
    position = determine_position(trade_data, odds)
    is_estimated = position.startswith('~')
    
    if 'YES' in position:
        implied_prob = yes_price * 100
        tokens_bought = amount / yes_price if yes_price > 0 else 0
        payout_if_win = tokens_bought * 1.0
        potential_profit = payout_if_win - amount
        position_display = f"YES @ {yes_price*100:.1f}¢"
    else:
        implied_prob = no_price * 100
        tokens_bought = amount / no_price if no_price > 0 else 0
        payout_if_win = tokens_bought * 1.0
        potential_profit = payout_if_win - amount
        position_display = f"NO @ {no_price*100:.1f}¢"
        
        # DEBUG: Print calculation details
        if DEBUG_CALCULATIONS:
            print(f"[DEBUG] NO POSITION CALCULATION:")
            print(f"  YES price (odds): {yes_price:.4f} ({yes_price*100:.1f}¢)")
            print(f"  NO price: {no_price:.4f} ({no_price*100:.1f}¢)")
            print(f"  Amount: ${amount:,.0f}")
            print(f"  Tokens bought: {tokens_bought:,.0f}")
            print(f"  Potential profit: ${potential_profit:,.0f}")
            print(f"  Position display: {position_display}")
    
    if is_estimated:
        position_display += " ⚠️"
    
    # Calculate ROI
    roi_percent = (potential_profit / amount * 100) if amount > 0 else 0
    roi_multiplier = roi_percent / 100
    
    # Format ROI display
    if roi_multiplier < 0.1:
        roi_display = f"{roi_multiplier:.2f}x"  # 0.04x for small ROI
    elif roi_multiplier < 100:
        roi_display = f"{roi_multiplier:.1f}x"  # 5.7x for medium ROI
    else:
        roi_display = f"{roi_multiplier:.0f}x"  # 200x for large ROI
    
    return {
        'position': position_display,
        'implied_prob': f"{implied_prob:.1f}%",
        'profit': f"${potential_profit:,.0f}",
        'roi_percent': roi_percent,
        'roi_display': roi_display,
        'is_estimated': is_estimated,
        'amount': f"${amount:,.0f}",
        'tokens': f"{tokens_bought:,.0f}"
    }

def format_wallet_classification(wallet_stats: Optional[Dict]) -> str:
    """Format wallet classification with emoji"""
    if not wallet_stats:
        return "🆕 New Wallet"
    
    classification = wallet_stats.get('classification', 'Unknown')
    insider_score = wallet_stats.get('insider_score', 0)
    
    emoji_map = {
        'Probable Insider': '🔴',
        'Syndicate/Whale': '🟠',
        'Professional': '🟡',
        'Retail': '🟢',
        'New': '🆕'
    }
    
    emoji = emoji_map.get(classification, '⚪')
    return f"{emoji} {classification} (Score: {insider_score:.0f}/100)"

def format_latency_alert(latency: Optional[Dict]) -> str:
    """Format latency information with severity indicators"""
    if not latency or not latency.get('is_pre_event'):
        return ""
    
    minutes = abs(latency['latency_minutes'])
    severity = latency['severity']
    
    severity_emoji = {
        'CRITICAL': '🚨🚨🚨',
        'HIGH': '🚨🚨',
        'MEDIUM': '🚨',
        'LOW': '⏰'
    }
    
    emoji = severity_emoji.get(severity, '⏰')
    
    return f"\n{emoji} PRE-EVENT DETECTED: {minutes:.0f} minutes BEFORE event"

@lru_cache(maxsize=100)
def generate_ai_summary_cached(cache_key: str, market: str, position: str, amount: str, 
                                wallet_info: str, latency_info: str):
    """
    Cached AI summary generation.
    FIX ISSUE #14: Rate limiting with caching.
    FIX ISSUE #12: Improved error handling.
    """
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Build context
        context = f"Market: {market}\n"
        context += f"Position: {position}\n"
        context += f"Bet Size: {amount}\n"
        
        if wallet_info:
            context += f"Wallet History: {wallet_info}\n"
        
        if latency_info:
            context += f"Timing: {latency_info}\n"
        
        prompt = f"""Analyze this Polymarket trade in ONE concise sentence (max 15 words).

{context}

Focus on the SPECIFIC insight, not generic patterns. Be direct and actionable.

Good examples:
- "Unusual pre-event timing suggests advance knowledge of announcement"
- "Pattern matches previous insider trades from this wallet"
- "Coordinated timing with other large bets indicates organized group"

Bad examples (too generic):
- "Large bet suggests potential insider information"
- "Extreme confidence may indicate knowledge"

Write ONE specific insight (max 15 words):"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.5
        )
        
        summary = response.choices[0].message.content.strip()
        
        # Remove quotes if AI added them
        summary = summary.strip('"').strip("'")
        
        return summary
        
    except openai.RateLimitError:
        return "⚠️ AI analysis rate limited - high-probability insider signal detected"
    except openai.APIError as e:
        return f"⚠️ AI analysis unavailable (API error)"
    except Exception as e:
        print(f"Error generating AI summary: {e}")
        return "High-probability insider signal detected"

def generate_ai_summary(alert):
    """
    Generate AI analysis with caching.
    FIX ISSUE #14: Cache identical alerts to reduce API costs.
    """
    trade_info = format_trade_info(alert)
    wallet_stats = alert.get('wallet_stats')
    latency = alert.get('latency')
    
    # Build wallet info string
    wallet_info = ""
    if wallet_stats and wallet_stats['total_trades'] >= 1:  # Lowered from 3 to show all wallet history
        wallet_info = f"{wallet_stats['total_trades']} trades, insider score {wallet_stats['insider_score']:.0f}"
    
    # Build latency info string
    latency_info = ""
    if latency and latency.get('is_pre_event'):
        latency_info = f"{latency['latency_minutes']:.0f} minutes BEFORE event"
    
    # Create cache key
    cache_key = hashlib.md5(
        f"{alert['market']}:{trade_info['position']}:{trade_info['amount']}:{wallet_info}:{latency_info}".encode()
    ).hexdigest()
    
    return generate_ai_summary_cached(
        cache_key,
        alert['market'],
        trade_info['position'],
        trade_info['amount'],
        wallet_info,
        latency_info
    )

def format_institutional_alert(alert):
    """
    Format alert in institutional-grade style with irrationality analysis.
    
    Signal types:
    - 🔥 ALPHA: Insider NO + mispricing confirmed
    - ⚠️ CONFLICT: Insider YES + market overpriced
    - 🚨 INSIDER_CONFIRMED: Insider YES + market underpriced
    - 👁️ INSIDER_ONLY: Insider activity without clear mispricing
    """
    from datetime import datetime, timezone
    
    analysis = alert["analysis"]
    trade_info = format_trade_info(alert)
    wallet_stats = alert.get('wallet_stats')
    latency = alert.get('latency')
    
    # Get irrationality data (new)
    combined_signal = alert.get('combined_signal', {})
    irrationality = alert.get('irrationality', {})
    mispricing = alert.get('mispricing', {})
    
    signal_type = combined_signal.get('signal_type', 'INSIDER_ONLY')
    signal_emoji = combined_signal.get('signal_emoji', '👁️')
    signal_strength = combined_signal.get('signal_strength', analysis.get('score', 0))
    
    # Determine header based on signal type
    if signal_type == "ALPHA":
        header = f"{signal_emoji} ALPHA SIGNAL — Insider + Mispricing Aligned"
    elif signal_type == "CONFLICT":
        header = f"{signal_emoji} CONFLICT — Insider vs Statistics"
    elif signal_type == "INSIDER_CONFIRMED":
        header = f"{signal_emoji} INSIDER CONFIRMED — Real Information Likely"
    elif signal_type == "CONTRARIAN_INSIDER":
        header = f"{signal_emoji} CONTRARIAN — Unusual Insider Behavior"
    else:
        header = f"{signal_emoji} INSIDER ACTIVITY"
    
    # Market category
    category = irrationality.get('category', 'other')
    category_display = category.replace('_', ' ').title()
    
    # Get YES price for display
    yes_price = alert.get('trade_data', {}).get('price', 0)
    no_price = 1 - yes_price
    
    # Wallet classification
    if wallet_stats and wallet_stats.get('classification'):
        classification = wallet_stats['classification']
        insider_score = wallet_stats.get('insider_score', 0)
        profile = f"{classification} ({insider_score:.0f}/100)"
    else:
        profile = "New Participant"
    
    # Lead time
    if latency and latency.get('is_pre_event'):
        lead_time_min = int(latency['latency_minutes'])
        if lead_time_min < 120:
            lead_time = f"{lead_time_min}m"
        elif lead_time_min < 1440:
            lead_time = f"{lead_time_min/60:.0f}h"
        else:
            lead_time = f"{lead_time_min/1440:.1f}d"
    else:
        lead_time = "N/A"
    
    # Build message
    message = f"""{header}
Category: {category_display}

Market: {alert['market']}
YES: {yes_price*100:.0f}¢ | NO: {no_price*100:.0f}¢

INSIDER ACTIVITY
Wallet: {alert['wallet'][:10]}...{alert['wallet'][-8:]}
Bet: {trade_info['amount']} {trade_info['position']}
Lead Time: {lead_time}
Profile: {profile}"""
    
    # Historical performance
    if wallet_stats and wallet_stats.get('total_trades', 0) >= 1:
        total = wallet_stats['total_trades']
        pre_event = wallet_stats.get('pre_event_trades', 0)
        message += f"\nHistory: {total} trades | {pre_event} pre-event"
    
    # Irrationality analysis section
    irr_score = irrationality.get('irrationality_score', 0)
    irr_flags = irrationality.get('flags', [])
    
    message += f"\n\nIRRATIONALITY ANALYSIS"
    message += f"\nScore: {irr_score}/100"
    
    for flag in irr_flags[:3]:  # Max 3 flags
        message += f"\n• {flag}"
    
    # Mispricing analysis section  
    edge = mispricing.get('edge_percent', 0)
    rational_est = mispricing.get('rational_estimate', 0)
    edge_quality = mispricing.get('edge_quality', 'NONE')
    is_mispriced = mispricing.get('is_mispriced', False)
    
    message += f"\n\nMISPRICING ANALYSIS"
    
    if is_mispriced:
        message += f"\n✅ CONFIRMED"
    else:
        message += f"\n❌ NOT CONFIRMED"
    
    message += f"\nRational estimate: ~{rational_est*100:.0f}%"
    message += f"\nMarket price: {yes_price*100:.0f}%"
    message += f"\nEdge: {edge:+.1f}% ({edge_quality})"
    
    # Combined signal interpretation
    interpretation = combined_signal.get('interpretation', '')
    action = combined_signal.get('action_suggestion', '')
    
    message += f"\n\nSIGNAL"
    message += f"\nType: {signal_type}"
    message += f"\nStrength: {signal_strength}/250"
    message += f"\n{interpretation}"
    
    if action:
        message += f"\n\n💡 {action}"
    
    # Suspicion factors from insider analysis
    flags = analysis.get('flags', [])[:3]
    if flags:
        message += f"\n\nINSIDER FLAGS"
        for flag in flags:
            message += f"\n• {flag}"
    
    # Footer
    market_slug = alert.get('market_slug', '')
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    
    message += f"\n\nSource: https://polymarket.com/event/{market_slug}"
    message += f"\nRadar | {timestamp} UTC"
    
    # Estimation warning
    if trade_info.get('is_estimated'):
        message += f"\n\n⚠️ Position estimated from odds"
    
    # Truncate if needed
    if len(message) > 4000:
        message = message[:4000] + "\n\n[Truncated]"
    
    return message

def send_telegram_alert(alert):
    """
    Send institutional-grade alert to Telegram.
    FIX ISSUE #12: Improved error handling with fallback.
    """
    try:
        message = format_institutional_alert(alert)
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✓ Alert sent successfully")
        return True
        
    except requests.exceptions.HTTPError as e:
        # Markdown parsing failed, try without markdown
        print(f"⚠️  Markdown parsing failed, retrying without formatting: {e}")
        try:
            payload["parse_mode"] = None
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"✓ Alert sent (without markdown)")
            return True
        except Exception as e2:
            print(f"❌ Alert sending failed completely: {e2}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"❌ Telegram API timeout")
        return False
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error sending alert: {e}")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error sending alert: {e}")
        return False
