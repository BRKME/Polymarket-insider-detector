import requests
from openai import OpenAI
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY

def determine_position(trade_data, odds):
    """
    Determine trading position (YES/NO) from trade data.
    Falls back to heuristic if data unavailable.
    """
    # Try to get explicit side/outcome from trade data
    if trade_data:
        # Method 1: Check 'side' field
        side = trade_data.get('side')
        if side:
            return side.upper()
        
        # Method 2: Check 'outcome' field
        outcome = trade_data.get('outcome')
        if outcome:
            return outcome.upper()
        
        # Method 3: Check 'asset' or 'assetId' (might contain YES/NO)
        asset = trade_data.get('asset', '')
        if 'yes' in str(asset).lower():
            return 'YES'
        if 'no' in str(asset).lower():
            return 'NO'
        
        # Method 4: Check tokenId (even token = YES, odd = NO in some markets)
        token_id = trade_data.get('tokenId')
        if token_id:
            try:
                # This is speculation - may not be accurate
                return 'YES' if int(token_id) % 2 == 0 else 'NO'
            except:
                pass
    
    # Fallback: Heuristic based on odds
    # If odds > 50% = likely betting YES, otherwise NO
    return '~YES' if odds > 0.5 else '~NO'

def format_trade_info(alert):
    """Format trade information with position detection"""
    analysis = alert["analysis"]
    trade_data = alert.get("trade_data", {})
    
    odds = analysis['odds']
    amount = analysis['amount']
    
    # Determine position
    position = determine_position(trade_data, odds)
    is_estimated = position.startswith('~')
    
    # Calculate implied probability and potential profit
    if 'YES' in position:
        implied_prob = odds * 100
        potential_profit = amount * (1 - odds)
        position_clean = 'YES'
    else:
        implied_prob = (1 - odds) * 100
        potential_profit = amount * odds
        position_clean = 'NO'
    
    # Format position display
    position_display = f"{position_clean} @ {odds*100:.1f}¢"
    if is_estimated:
        position_display += " ⚠️"
    
    return {
        'position': position_display,
        'implied_prob': f"{implied_prob:.1f}%",
        'profit': f"${potential_profit:,.0f}",
        'is_estimated': is_estimated,
        'amount': f"${amount:,.0f}"
    }

def generate_ai_summary(alert):
    """Generate concise AI analysis of suspicious trade"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        trade_info = format_trade_info(alert)
        
        prompt = f"""Analyze this suspicious Polymarket trade in 1 SHORT sentence (max 15 words).

Market: {alert['market']}
Position: {trade_info['position']}
Bet Size: {trade_info['amount']}
Wallet: {alert['analysis']['wallet_age_days']}d old, {alert['analysis']['total_activities']} activities

Focus on: Why THIS specific bet is suspicious (not generic "new wallet" comments).
Examples: 
- "Betting against 95% consensus suggests insider info on policy change"
- "Extreme confidence on uncertain event indicates potential leak"

Write ONLY ONE critical insight (max 15 words):"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.5
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating AI summary: {e}")
        return "AI analysis unavailable."

def format_alert_message(alert):
    """Format alert message with enhanced trade information"""
    analysis = alert["analysis"]
    trade_info = format_trade_info(alert)
    
    # Build message
    message = f"""🚨 INSIDER ALERT (Score: {analysis['score']}/110)

📊 {alert['market']}

💰 Trade Details:
   • Bet Size: {trade_info['amount']}
   • Position: {trade_info['position']}
   • Implied Probability: {trade_info['implied_prob']}
   • Potential Profit: {trade_info['profit']}

🔍 Suspicious Signals:
{chr(10).join(['   ✓ ' + flag for flag in analysis['flags']])}

👛 Wallet: `{alert['wallet']}`
📍 {alert.get('market_url', f"https://polymarket.com/event/{alert['market_slug']}")}

🤖 AI Analysis:
{generate_ai_summary(alert)}"""

    # Add estimation warning if position was guessed
    if trade_info['is_estimated']:
        message += "\n\n⚠️ Position (YES/NO) estimated from odds. Check market for exact details."
    
    return message

def send_telegram_alert(alert):
    """Send formatted alert to Telegram"""
    try:
        message = format_alert_message(alert)
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
            "parse_mode": "Markdown"  # Enable markdown for better formatting
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")
        # Try without markdown if it fails
        try:
            payload["parse_mode"] = None
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except:
            return False
