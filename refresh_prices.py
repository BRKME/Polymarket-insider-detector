"""
refresh_prices.py — re-check current prices before you place a manual bet.

The scanner runs every 6h, so by the time you actually open Polymarket and
bet, the alert price can be stale — and at $15-70 stakes a few cents of drift
is the difference between edge and no edge. This pulls fresh NO prices for open
journal positions and shows how far the edge has moved since the alert, so you
enter on a price you've just verified, not one logged hours ago.

This does NOT place trades. Read-only.

Run:  python refresh_prices.py
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Dict, List

JOURNAL = Path("event_journal.jsonl")


def _load_journal() -> List[dict]:
    if not JOURNAL.exists():
        return []
    rows = []
    for line in JOURNAL.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _default_fetch(condition_id: str) -> Optional[Dict]:
    import resolution_tracker as rt
    m = rt.fetch_market_by_condition_id(condition_id)
    if not m:
        m = rt.fetch_market_by_clob(condition_id)
    return m


def refresh(
    rows: List[dict],
    fetch_fn: Callable[[str], Optional[Dict]] = _default_fetch,
) -> List[dict]:
    """For each open position, compare alert-time NO/edge to current."""
    import event_scanner as es
    out = []
    for row in rows:
        if str(row.get("status", "open")).lower() != "open":
            continue
        cid = row.get("condition_id", "")
        if not cid:
            continue
        market = fetch_fn(cid)
        if not market:
            continue
        parsed = es._parse_prices(market)
        if not parsed:
            continue
        yes_now, no_now = parsed
        ai_yes = row.get("ai_yes_estimate")
        edge_now = None
        try:
            edge_now = round(yes_now - float(ai_yes), 4)
        except (TypeError, ValueError):
            pass
        alert_no = row.get("no_price")
        alert_edge = row.get("edge")
        out.append({
            "question": row.get("question", ""),
            "condition_id": cid,
            "alert_no": alert_no,
            "current_no": round(no_now, 4),
            "alert_edge": alert_edge,
            "current_edge": edge_now,
            # still worth entering? edge must still clear EDGE_MIN.
            "still_tradeable": bool(edge_now is not None and edge_now >= es.EDGE_MIN),
        })
    return out


def run() -> None:
    rows = _load_journal()
    results = refresh(rows)
    print(f"[{datetime.now(timezone.utc).isoformat()}] refresh: "
          f"{len(results)} open positions re-priced\n")
    for r in results:
        flag = "✅ ставить" if r["still_tradeable"] else "⚠️ edge просел — проверь"
        ae = f"{r['alert_edge']*100:.0f}пп" if r["alert_edge"] is not None else "?"
        ce = f"{r['current_edge']*100:.0f}пп" if r["current_edge"] is not None else "?"
        an = f"{r['alert_no']*100:.0f}%" if r["alert_no"] is not None else "?"
        print(f"  {flag}")
        print(f"    {r['question'][:70]}")
        print(f"    NO {an}→{r['current_no']*100:.0f}% · edge {ae}→{ce}\n")


if __name__ == "__main__":
    run()
