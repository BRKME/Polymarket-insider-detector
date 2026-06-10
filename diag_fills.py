"""
diag_fills.py — ONE-OFF diagnostic. Does Polymarket's Data API return OUR
trades by address, and in what shape? Output drives the real fill-matcher.

Prints, for /trades and /activity:
  • HTTP status, record count
  • field names of the first record
  • two full records (so we see how price / size / token / time are encoded)

Also pulls a couple of open journal condition_ids and shows whether any returned
trade plausibly matches (by token/market), so we know the join key works.

Read-only. Address is public (on-chain anyway). No keys. Delete after use.

Run:  python diag_fills.py
"""
import json
from pathlib import Path

import requests

ADDR = "0xbd8338C6D4e1E25B28D1A95Db926D2CeF689632f"
BASE = "https://data-api.polymarket.com"


def _dump(ep, params):
    url = f"{BASE}/{ep}"
    try:
        r = requests.get(url, params=params, timeout=20)
        print(f"\n===== /{ep}  HTTP {r.status_code} =====")
        if r.status_code != 200:
            print("body:", r.text[:300])
            return []
        data = r.json()
        n = len(data) if isinstance(data, list) else "not-a-list"
        print(f"records: {n}")
        if isinstance(data, list) and data:
            print("keys:", sorted(data[0].keys()))
            print(json.dumps(data[:2], indent=2, ensure_ascii=False)[:3000])
            return data
        else:
            print("raw:", json.dumps(data, ensure_ascii=False)[:800])
    except Exception as e:
        print(f"/{ep} error: {e}")
    return []


def main():
    print(f"Address: {ADDR}")

    trades = _dump("trades", {"user": ADDR, "limit": 10})
    _dump("activity", {"user": ADDR, "type": "TRADE", "limit": 10})

    # Show what our journal expects to join on.
    jp = Path("event_journal.jsonl")
    if jp.exists():
        rows = [json.loads(l) for l in jp.read_text().splitlines() if l.strip()]
        open_rows = [r for r in rows if str(r.get("status", "open")).lower() == "open"]
        print(f"\n===== JOURNAL: {len(rows)} total, {len(open_rows)} open =====")
        for r in open_rows[:8]:
            print(f"  cid={r.get('condition_id','')[:20]}… "
                  f"NO={r.get('no_price')} q={r.get('question','')[:45]}")

        # Naive join probe: do any returned trades carry a condition_id /
        # market field that equals one of our journal cids?
        if trades:
            jcids = {r.get("condition_id", "") for r in open_rows}
            print("\n===== JOIN PROBE (trade fields that look like a market id) =====")
            t0 = trades[0]
            for k, v in t0.items():
                if isinstance(v, str) and v.startswith("0x") and len(v) > 40:
                    hit = "✅ in journal" if v in jcids else "—"
                    print(f"  trade.{k} = {v[:24]}…  {hit}")
    else:
        print("\n(no event_journal.jsonl found)")


if __name__ == "__main__":
    main()
