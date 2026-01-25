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
    FIX ISSUE #24: Check message length to avoid Telegram truncation.
    
    Style: Hedge fund research desk
    """
    analysis = alert["analysis"]
    trade_info = format_trade_info(alert)
    wallet_stats = alert.get('wallet_stats')
    latency = alert.get('latency')
    
    # Header
    classification = format_wallet_classification(wallet_stats)
    
    message = f"""{'='*50}
🎯 ALPHA SIGNAL: POTENTIAL INSIDER DETECTED
{'='*50}

📊 Market: {alert['market']}

💰 Trade Details:
   • Bet Size: {trade_info['amount']}
   • Position: {trade_info['position']}
   • Implied Win Probability: {trade_info['implied_prob']}
   • Potential Profit: {trade_info['profit']}"""

    # Latency Alert (if pre-event)
    if latency and latency.get('is_pre_event'):
        message += format_latency_alert(latency)
    
    # Wallet Intelligence
    message += f"\n\n👛 Wallet Intelligence:"
    message += f"\n   • Address: `{alert['wallet'][:10]}...{alert['wallet'][-8:]}`"
    message += f"\n   • Classification: {classification}"
    
    if wallet_stats and wallet_stats['total_trades'] >= 3:
        message += f"\n   • Historical Performance:"
        message += f"\n      - Total Trades: {wallet_stats['total_trades']}"
        message += f"\n      - Pre-Event Trades: {wallet_stats['pre_event_trades']}"
        
        if wallet_stats.get('avg_latency_seconds', 0) > 0:
            avg_latency_min = wallet_stats['avg_latency_seconds'] / 60
            message += f"\n      - Avg Pre-Event Latency: {avg_latency_min:.0f} minutes"
    else:
        message += f"\n   • Status: New wallet (first {wallet_stats['total_trades'] if wallet_stats else 0} trades)"
    
    # Suspicious Signals
    message += f"\n\n🔍 Suspicious Signals:"
    for flag in analysis['flags']:
        message += f"\n   ✓ {flag}"
    
    # Confidence Score
    message += f"\n\n📈 Analysis:"
    message += f"\n   • Insider Probability Score: {analysis['score']}/150"
    message += f"\n   • {generate_ai_summary(alert)}"
    
    # Market Link
    message += f"\n\n🔗 Market: https://polymarket.com/event/{alert.get('market_slug', '')}"
    
    # Footer
    message += f"\n{'='*50}"
    
    # Estimation warning if needed
    if trade_info['is_estimated']:
        message += "\n\n⚠️ Note: Position (YES/NO) estimated from odds. Verify on market page."
    
    # FIX ISSUE #24: Truncate if too long
    if len(message) > 4000:
        # Remove wallet history section
        message = message[:4000]
        message += "\n\n[Message truncated - see market page for full details]"
    
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
