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
    
    if is_estimated:
        position_display += " ⚠️"
    
    return {
        'position': position_display,
        'implied_prob': f"{implied_prob:.1f}%",
        'profit': f"${potential_profit:,.0f}",
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
        
        prompt = f"""Analyze this suspicious Polymarket trade in 1 sentence (max 20 words).

{context}

Focus on WHY this specific combination is suspicious. Be concise and specific.
Examples:
- "Pre-event positioning with proven track record suggests insider knowledge"
- "Extreme confidence 30 minutes before announcement indicates information advantage"

Write ONLY ONE insight (max 20 words):"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.5
        )
        
        return response.choices[0].message.content.strip()
        
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
    if wallet_stats and wallet_stats['total_trades'] >= 3:
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
    Format alert in institutional-grade style.
    
    Style: Terminal/Bloomberg minimalist
    - No ASCII separators
    - Minimal emojis
    - Compact mobile-first layout
    - Financial terminology
    """
    from datetime import datetime, timezone
    
    analysis = alert["analysis"]
    trade_info = format_trade_info(alert)
    wallet_stats = alert.get('wallet_stats')
    latency = alert.get('latency')
    
    # Determine signal class from market question
    market_question = alert['market'].lower()
    if any(kw in market_question for kw in ['president', 'election', 'nominee', 'senate', 'congress']):
        signal_class = "Political"
    elif any(kw in market_question for kw in ['bitcoin', 'ethereum', 'crypto', 'price', 'stock']):
        signal_class = "Market"
    elif any(kw in market_question for kw in ['war', 'ceasefire', 'treaty', 'invasion']):
        signal_class = "Macro"
    else:
        signal_class = "Governance"
    
    # Wallet classification (clean format)
    if wallet_stats and wallet_stats.get('classification'):
        classification = wallet_stats['classification']
        insider_score = wallet_stats.get('insider_score', 0)
        profile = f"{classification} ({insider_score:.0f}/100)"
    else:
        profile = "New Participant"
    
    # Lead time
    if latency and latency.get('is_pre_event'):
        lead_time_min = int(latency['latency_minutes'])
        lead_time = f"{lead_time_min} min"
    else:
        lead_time = "N/A"
    
    # Build message
    message = f"""ALPHA SIGNAL — Insider Activity
Signal Class: {signal_class}

Market: {alert['market']}

Trade Snapshot
Bet: {trade_info['amount']} | Position: {trade_info['position']}
Implied Prob: {trade_info['implied_prob']} | Potential PnL: {trade_info['profit']}
Lead Time: {lead_time}

Wallet Intelligence
{alert['wallet'][:10]}...{alert['wallet'][-6:]}
Profile: {profile}"""
    
    # Historical performance (if available)
    if wallet_stats and wallet_stats.get('total_trades', 0) >= 3:
        total = wallet_stats['total_trades']
        pre_event = wallet_stats.get('pre_event_trades', 0)
        message += f"\nHistory: {total} trades | {pre_event} pre-event"
    
    # Suspicion factors (max 4 lines)
    message += f"\n\nSuspicion Factors"
    flags = analysis.get('flags', [])[:4]  # Max 4 factors
    for flag in flags:
        message += f"\n• {flag}"
    
    # Score and interpretation
    score = analysis.get('score', 0)
    ai_summary = generate_ai_summary(alert)
    
    message += f"\n\nSignal Score: {score}/150"
    message += f"\nInterpretation: {ai_summary}"
    
    # Footer with source and timestamp
    market_slug = alert.get('market_slug', '')
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    
    message += f"\n\nSource: https://polymarket.com/event/{market_slug}"
    message += f"\nRadar | {timestamp} UTC"
    
    # Estimation warning if needed (compact)
    if trade_info.get('is_estimated'):
        message += f"\n\nNote: Position estimated from odds"
    
    # Check length (Telegram limit 4096)
    if len(message) > 4000:
        # Truncate factors if needed
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
