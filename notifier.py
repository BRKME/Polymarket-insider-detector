import requests
from openai import OpenAI
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY

def generate_ai_summary(alert):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""Analyze this Polymarket trade in MAX 2 SHORT sentences.

Market: {alert['market']}
Bet: ${alert['analysis']['amount']:,.0f} @ {alert['analysis']['odds']*100:.1f}%
Wallet: {alert['analysis']['wallet_age_days']}d old, {alert['analysis']['total_activities']} activities
Flags: {', '.join(alert['analysis']['flags'])}

Write ONLY 1-2 concise sentences explaining the main concern. Be brief."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,  # Reduced from 150
            temperature=0.5  # Reduced from 0.7 for more focused output
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating AI summary: {e}")
        return "AI analysis unavailable."

def format_alert_message(alert):
    analysis = alert["analysis"]
    
    message = f"""🚨 INSIDER ALERT (Score: {analysis['score']}/110)

📊 {alert['market']}

💰 Bet: ${analysis['amount']:,.0f} @ {analysis['odds']*100:.1f}%

🔍 Suspicious:
{chr(10).join(['✓ ' + flag for flag in analysis['flags']])}

👛 Wallet: `{alert['wallet']}`
📍 {alert.get('market_url', f"https://polymarket.com/event/{alert['market_slug']}")}

🤖 AI Analysis:
{generate_ai_summary(alert)}"""
    
    return message

def send_telegram_alert(alert):
    try:
        message = format_alert_message(alert)
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")
        return False
