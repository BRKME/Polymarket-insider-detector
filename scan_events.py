"""
scan_events.py — runner for the v5 event-market scanner (manual-bet mode A).

Flow:
  1. Fetch active markets via collector.get_active_markets / priority.
  2. event_scanner.scan() applies gates + Grok mispricing check.
  3. Each candidate → Telegram alert + append to event_journal.jsonl.
  4. Dedup against already-alerted condition_ids (state in event_seen.json).

No bets are placed. The journal records market price, AI estimate and entry so
the edge can be validated against real outcomes after ~6-8 weeks.

Run:  python scan_events.py
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import collector
import event_scanner as es
from ai_context import estimate_probability

JOURNAL = Path("event_journal.jsonl")   # one JSON line per alerted candidate
SEEN = Path("event_seen.json")          # condition_ids already alerted
MARKET_FETCH_LIMIT = 500                 # wide slice — event NO-markets are mid-liquidity
MAX_AI_CALLS = 40                        # cap Grok calls per run (cost control)


def _load_seen() -> set:
    if SEEN.exists():
        try:
            return set(json.loads(SEEN.read_text()))
        except Exception:
            return set()
    return set()


def _save_seen(seen: set) -> None:
    SEEN.write_text(json.dumps(sorted(seen)))


def _append_journal(candidate: es.Candidate) -> None:
    row = candidate.to_alert()
    row["alerted_at"] = datetime.now(timezone.utc).isoformat()
    row["bet_side"] = "NO"
    row["stake_plan"] = "manual $5-20 flat"
    with JOURNAL.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _format_alert(c: es.Candidate) -> str:
    end = c.end_date[:10] if c.end_date else "?"
    edge_pct = c.edge * 100
    fire = "🔥" if c.edge >= 0.25 else "✅"
    url = f"https://polymarket.com/event/{c.slug}" if c.slug else ""
    msg = (
        f"{fire} СОБЫТИЕ · ставка NO (мисприсинг)\n"
        f"{c.question}\n"
        f"—————————————————————\n"
        f"Вход NO по {c.no_price*100:.0f}% · разрыв {edge_pct:.0f} п.п. · до {end}\n"
        f"Ликвидность ${c.liquidity:,.0f}\n"
        f"—————————————————————\n"
        f"{c.reasoning}"
    )
    if url:
        msg += f"\n🔗 {url}"
    return msg


def _send(msg: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠️ Telegram creds missing — printing instead:\n", msg)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                  "disable_web_page_preview": False},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"  ❌ send failed: {e}")
        return False


def run() -> None:
    print(f"[{datetime.now()}] event scan start")
    seen = _load_seen()

    markets = collector.get_active_markets(limit=MARKET_FETCH_LIMIT)
    print(f"  fetched {len(markets)} active markets")

    # Show the raw field shapes of the first market once — lets us spot when
    # live Gamma returns prices/liquidity in a different format than expected.
    if markets:
        m0 = markets[0]
        print("  --- sample market fields ---")
        for k in ("question", "outcomes", "outcomePrices", "liquidity",
                  "volume", "endDate", "conditionId", "slug"):
            print(f"    {k}: {type(m0.get(k)).__name__} = {repr(m0.get(k))[:70]}")

    # Cheap structural gate first (no AI). Track WHY each market fails so a
    # zero-candidate run is debuggable from the log alone.
    funnel = {"sport_or_hft": 0, "not_binary_yesno": 0, "no_out_of_band": 0,
              "low_liquidity": 0, "bad_time": 0, "already_seen": 0, "PASS": 0}
    no_band_count = 0
    gated = []
    for m in markets:
        cid = m.get("conditionId", "")
        if cid in seen:
            funnel["already_seen"] += 1
            continue
        q = m.get("question", "") or m.get("title", "")
        if not q or es._is_sport_or_hft(q):
            funnel["sport_or_hft"] += 1
            continue
        parsed = es._parse_prices(m)
        if not parsed:
            funnel["not_binary_yesno"] += 1
            continue
        _, no_price = parsed
        if not (es.NO_ODDS_MIN <= no_price < es.NO_ODDS_MAX):
            funnel["no_out_of_band"] += 1
            continue
        no_band_count += 1
        liq = float(m.get("liquidity", 0) or m.get("volume", 0) or 0)
        if liq < es.MIN_LIQUIDITY:
            funnel["low_liquidity"] += 1
            continue
        hrs = es._hours_to_resolve(m)
        if hrs is None or not (es.MIN_HOURS_TO_RESOLVE <= hrs <= es.MAX_DAYS_TO_RESOLVE * 24):
            funnel["bad_time"] += 1
            continue
        funnel["PASS"] += 1
        gated.append(m)

    print(f"  --- gate funnel ---")
    for k, v in funnel.items():
        print(f"    {k}: {v}")
    print(f"  {len(gated)} passed structural gate (event + NO 0.1-0.5 + liquid)")

    gated = gated[:MAX_AI_CALLS]  # cost cap

    candidates = es.scan(gated, estimate_probability)
    print(f"  {len(candidates)} candidates after AI mispricing check")

    sent = 0
    for c in candidates:
        if _send(_format_alert(c)):
            sent += 1
        _append_journal(c)
        seen.add(c.condition_id)

    _save_seen(seen)
    print(f"[{datetime.now()}] done — {sent} alerts sent, journal updated")


if __name__ == "__main__":
    run()
