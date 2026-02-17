import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple

from detector import detect_insider_trades
from notifier import send_telegram_alert


def load_tracked_wallets():
    """Load tracked trade hashes (not wallets - we want alerts for each trade)."""
    path = Path("tracked_wallets.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                # Migration: if old format (list of wallets), convert to new format
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str) and data[0].startswith("0x"):
                    return {"wallets": data, "trade_hashes": []}
                if isinstance(data, dict):
                    return data
                return {"wallets": [], "trade_hashes": []}
        except Exception:
            return {"wallets": [], "trade_hashes": []}
    return {"wallets": [], "trade_hashes": []}


def save_tracked_wallets(tracked_data):
    path = Path("tracked_wallets.json")
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w") as f:
        json.dump(tracked_data, f, indent=2)
    temp_path.replace(path)


def load_alerts():
    path = Path("alerts.json")
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_alerts(alerts):
    path = Path("alerts.json")
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w") as f:
        json.dump(alerts, f, indent=2)
    temp_path.replace(path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float conversion that never raises."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _evaluate_financial_analyst_view(alert: Dict) -> Dict:
    """Create a compact financial-analyst view for execution/risk decisions."""
    analysis = alert.get("analysis", {})
    combined = alert.get("combined_signal", {})
    mispricing = alert.get("mispricing", {})
    irrationality = alert.get("irrationality", {})
    trade_data = alert.get("trade_data", {})

    edge_percent = _safe_float(mispricing.get("edge_percent", 0))
    insider_score = _safe_float(analysis.get("score", 0))
    signal_strength = _safe_float(combined.get("signal_strength", insider_score), insider_score)
    irrationality_score = _safe_float(irrationality.get("irrationality_score", 0))
    amount = _safe_float(trade_data.get("amount", analysis.get("amount", 0)), 0)

    quality = 0
    if combined.get("signal_type") == "ALPHA":
        quality += 35
    elif combined.get("signal_type") == "INSIDER_CONFIRMED":
        quality += 25
    elif combined.get("signal_type") == "INSIDER_ONLY":
        quality += 5

    quality += min(25, max(0, edge_percent * 1.5))
    quality += min(20, insider_score / 5)
    quality += min(20, irrationality_score / 5)
    quality = round(min(100, quality), 1)

    if quality >= 75:
        stance = "HIGH_CONVICTION"
    elif quality >= 55:
        stance = "SELECTIVE"
    else:
        stance = "WATCH_ONLY"

    if amount >= 10000 and stance == "HIGH_CONVICTION":
        risk_note = "High stake detected — copy with reduced sizing (25-40% of source risk)."
    elif amount > 0:
        risk_note = "Use fixed fractional risk (1-2% bankroll) and avoid averaging down."
    else:
        risk_note = "Insufficient sizing data — treat as exploratory signal."

    return {
        "signal_quality": quality,
        "stance": stance,
        "edge_percent": round(edge_percent, 2),
        "signal_strength": signal_strength,
        "insider_score": insider_score,
        "risk_note": risk_note,
    }


def _split_by_goals(alerts: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Goal 1: Find insiders.
    Goal 2: Find irrational trades worth copying.
    """
    insiders: List[Dict] = []
    irrational_copy_candidates: List[Dict] = []

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        combined = alert.get("combined_signal", {}) if isinstance(alert.get("combined_signal", {}), dict) else {}
        mispricing = alert.get("mispricing", {}) if isinstance(alert.get("mispricing", {}), dict) else {}

        try:
            analyst_view = _evaluate_financial_analyst_view(alert)
            alert["financial_analyst"] = analyst_view
        except Exception as exc:
            print(f"[{datetime.now()}] ⚠️ Failed to build financial analyst view: {exc}")
            analyst_view = {
                "signal_quality": 0.0,
                "stance": "WATCH_ONLY",
                "edge_percent": 0.0,
                "signal_strength": 0.0,
                "insider_score": 0.0,
                "risk_note": "Analysis unavailable due to malformed alert payload.",
            }
            alert["financial_analyst"] = analyst_view

        # Goal 1: all meaningful insider alerts (existing detector already pre-filtered)
        insiders.append(alert)

        # Goal 2: copy only when there is both informational + pricing edge
        signal_type = combined.get("signal_type", "")
        edge_percent = _safe_float(mispricing.get("edge_percent", 0))
        stance = analyst_view["stance"]

        is_copy_candidate = (
            signal_type in {"ALPHA", "INSIDER_CONFIRMED"}
            and edge_percent >= 3.0
            and stance in {"HIGH_CONVICTION", "SELECTIVE"}
        )

        if is_copy_candidate:
            irrational_copy_candidates.append(alert)

    return insiders, irrational_copy_candidates


def _print_goal_summary(insiders: List[Dict], irrational_copy_candidates: List[Dict]) -> None:
    print(f"[{datetime.now()}] 🎯 Goal #1 (find insiders): {len(insiders)} signals")
    print(
        f"[{datetime.now()}] 🎯 Goal #2 (irrational trades to copy): "
        f"{len(irrational_copy_candidates)} candidates"
    )

    if irrational_copy_candidates:
        print(f"[{datetime.now()}] Top copy candidates (financial analyst view):")
        sorted_candidates = sorted(
            irrational_copy_candidates,
            key=lambda x: x.get("financial_analyst", {}).get("signal_quality", 0),
            reverse=True,
        )
        for idx, candidate in enumerate(sorted_candidates[:5], start=1):
            fa = candidate.get("financial_analyst", {}) if isinstance(candidate.get("financial_analyst", {}), dict) else {}
            sig = candidate.get("combined_signal", {}) if isinstance(candidate.get("combined_signal", {}), dict) else {}
            market = candidate.get("market", "Unknown market")
            print(
                f"  {idx}. {market[:90]} | {sig.get('signal_type', 'N/A')} | "
                f"quality {_safe_float(fa.get('signal_quality', 0))}/100 | "
                f"edge {_safe_float(fa.get('edge_percent', 0)):+.1f}%"
            )


def main():
    print(f"[{datetime.now()}] Starting Polymarket insider detector...")

    tracked_data = load_tracked_wallets()
    tracked_hashes = set(tracked_data.get("trade_hashes", []))
    tracked_wallets = set(tracked_data.get("wallets", []))  # keep for stats
    existing_alerts = load_alerts()

    try:
        new_alerts = detect_insider_trades()
    except Exception as exc:
        print(f"[{datetime.now()}] ❌ Unhandled error in detector: {exc}")
        new_alerts = []

    if not isinstance(new_alerts, list):
        print(f"[{datetime.now()}] ⚠️ Detector returned non-list payload, coercing to empty list")
        new_alerts = []
    insiders, irrational_copy_candidates = _split_by_goals(new_alerts)
    _print_goal_summary(insiders, irrational_copy_candidates)

    sent_count = 0
    for alert in insiders:
        if not isinstance(alert, dict):
            continue

        trade_hash = alert.get("trade_hash", "")
        wallet = alert.get("wallet", "")
        if not wallet:
            print(f"[{datetime.now()}] ⚠️ Skipping alert without wallet")
            continue

        # Deduplicate by trade_hash (not wallet) - allows multiple alerts per wallet
        if trade_hash and trade_hash in tracked_hashes:
            print(f"[{datetime.now()}] Trade {trade_hash[:12]}... already alerted, skipping")
            continue

        if send_telegram_alert(alert):
            if trade_hash:
                tracked_hashes.add(trade_hash)
            tracked_wallets.add(wallet)
            existing_alerts.append(alert)
            sent_count += 1
            print(f"[{datetime.now()}] ✅ Alert sent for trade {trade_hash[:12]}... (wallet {wallet[:8]}...)")
        else:
            print(f"[{datetime.now()}] ❌ Failed to send alert for {wallet[:8]}...")

    tracked_data = {
        "wallets": list(tracked_wallets),
        "trade_hashes": list(tracked_hashes),
    }
    save_tracked_wallets(tracked_data)
    save_alerts(existing_alerts)

    print(
        f"[{datetime.now()}] Completed. "
        f"Insider signals: {len(insiders)}, copy candidates: {len(irrational_copy_candidates)}, "
        f"alerts sent: {sent_count}"
    )


if __name__ == "__main__":
    main()
