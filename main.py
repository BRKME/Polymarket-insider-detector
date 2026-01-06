import json
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.detector import detect_insider_trades
from src.notifier import send_telegram_alert

def load_tracked_wallets():
    path = Path("data/tracked_wallets.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_tracked_wallets(wallets):
    path = Path("data/tracked_wallets.json")
    path.parent.mkdir(exist_ok=True, parents=True)
    
    temp_path = path.with_suffix('.tmp')
    with open(temp_path, "w") as f:
        json.dump(wallets, f, indent=2)
    temp_path.replace(path)

def load_alerts():
    path = Path("data/alerts.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_alerts(alerts):
    path = Path("data/alerts.json")
    path.parent.mkdir(exist_ok=True, parents=True)
    
    temp_path = path.with_suffix('.tmp')
    with open(temp_path, "w") as f:
        json.dump(alerts, f, indent=2)
    temp_path.replace(path)

def main():
    print(f"[{datetime.now()}] Starting Polymarket insider detector...")
    
    tracked_wallets = load_tracked_wallets()
    existing_alerts = load_alerts()
    
    new_alerts = detect_insider_trades()
    
    sent_count = 0
    for alert in new_alerts:
        wallet = alert["wallet"]
        
        if wallet in tracked_wallets:
            print(f"[{datetime.now()}] Wallet {wallet[:8]}... already tracked, skipping")
            continue
        
        if send_telegram_alert(alert):
            tracked_wallets.append(wallet)
            existing_alerts.append(alert)
            sent_count += 1
            print(f"[{datetime.now()}] ✅ Alert sent for {wallet[:8]}...")
        else:
            print(f"[{datetime.now()}] ❌ Failed to send alert for {wallet[:8]}...")
    
    save_tracked_wallets(tracked_wallets)
    save_alerts(existing_alerts)
    
    print(f"[{datetime.now()}] Completed. Found {len(new_alerts)} potential insiders, sent {sent_count} new alerts")

if __name__ == "__main__":
    main()
