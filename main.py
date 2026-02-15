import json
from pathlib import Path
from datetime import datetime
from detector import detect_insider_trades
from notifier import send_telegram_alert

def load_tracked_wallets():
    """Load tracked trade hashes (not wallets - we want alerts for each trade)"""
    path = Path("tracked_wallets.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                # Migration: if old format (list of wallets), convert to new format
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str) and data[0].startswith("0x"):
                    # Old format - wallet addresses
                    return {"wallets": data, "trade_hashes": []}
                elif isinstance(data, dict):
                    return data
                else:
                    return {"wallets": [], "trade_hashes": []}
        except:
            return {"wallets": [], "trade_hashes": []}
    return {"wallets": [], "trade_hashes": []}

def save_tracked_wallets(tracked_data):
    path = Path("tracked_wallets.json")
    temp_path = path.with_suffix('.tmp')
    with open(temp_path, "w") as f:
        json.dump(tracked_data, f, indent=2)
    temp_path.replace(path)

def load_alerts():
    path = Path("alerts.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_alerts(alerts):
    path = Path("alerts.json")
    temp_path = path.with_suffix('.tmp')
    with open(temp_path, "w") as f:
        json.dump(alerts, f, indent=2)
    temp_path.replace(path)

def main():
    print(f"[{datetime.now()}] Starting Polymarket insider detector...")
    
    tracked_data = load_tracked_wallets()
    tracked_hashes = set(tracked_data.get("trade_hashes", []))
    tracked_wallets = set(tracked_data.get("wallets", []))  # Keep for stats
    existing_alerts = load_alerts()
    
    new_alerts = detect_insider_trades()
    
    sent_count = 0
    for alert in new_alerts:
        trade_hash = alert.get("trade_hash", "")
        wallet = alert["wallet"]
        
        # Deduplicate by trade_hash (not wallet) - allows multiple alerts per wallet
        if trade_hash and trade_hash in tracked_hashes:
            print(f"[{datetime.now()}] Trade {trade_hash[:12]}... already alerted, skipping")
            continue
        
        if send_telegram_alert(alert):
            if trade_hash:
                tracked_hashes.add(trade_hash)
            tracked_wallets.add(wallet)  # Track wallet for stats
            existing_alerts.append(alert)
            sent_count += 1
            print(f"[{datetime.now()}] ✅ Alert sent for trade {trade_hash[:12]}... (wallet {wallet[:8]}...)")
        else:
            print(f"[{datetime.now()}] ❌ Failed to send alert for {wallet[:8]}...")
    
    # Save updated tracking data
    tracked_data = {
        "wallets": list(tracked_wallets),
        "trade_hashes": list(tracked_hashes)
    }
    save_tracked_wallets(tracked_data)
    save_alerts(existing_alerts)
    
    print(f"[{datetime.now()}] Completed. Found {len(new_alerts)} potential insiders, sent {sent_count} new alerts")

if __name__ == "__main__":
    main()
