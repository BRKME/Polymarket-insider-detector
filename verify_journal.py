"""
verify_journal.py — honest scorecard for the v5 event strategy.

Reads event_journal.jsonl (one alerted NO-candidate per line), resolves each
market's real outcome, and reports:
  • WR / ROI at flat stake on the NO bets we actually flagged
  • AI calibration: did AI's P(YES) track reality? (the core untested assumption)
  • Diversification: max simultaneous open positions vs the ~20 the math needs
    (per habr.com/ru/articles/1042056 — too few concurrent bets => variance ruins
     even a real edge)

Resolution reuses the fixed cascade from resolution_tracker (Gamma condition_ids
-> CLOB winner flag). No bets are placed; this only scores what was logged.

Run:  python verify_journal.py
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import resolution_tracker as rt

JOURNAL = Path("event_journal.jsonl")
FLAT_STAKE = 10.0          # $ we assume per NO bet, for scoring
TARGET_CONCURRENT = 20     # diversification target from the math in the article


def _load() -> list:
    if not JOURNAL.exists():
        print("No journal yet — nothing to verify.")
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


def _resolve_no_outcome(condition_id: str) -> Optional[bool]:
    """
    Did the NO side win? Returns True (NO won), False (NO lost), None (unresolved).
    Uses the same multi-source lookup we fixed in resolution_tracker.
    """
    market = rt.fetch_market_by_condition_id(condition_id)
    if not market:
        market = rt.fetch_market_by_clob(condition_id)
    if not market:
        return None
    resolution = rt.determine_resolution(market)
    if not resolution or resolution in ("EXPIRED", "UNRESOLVED"):
        return None
    # determine_resolution returns the winning side as "Yes"/"No" (or similar).
    r = str(resolution).strip().lower()
    if r in ("no", "false", "0"):
        return True       # NO side won → our bet won
    if r in ("yes", "true", "1"):
        return False      # YES won → our NO bet lost
    return None


def verify() -> None:
    rows = _load()
    if not rows:
        return
    print(f"Journal entries: {len(rows)}")

    wins = losses = unresolved = 0
    pnl = 0.0
    calib = []   # (ai_yes, no_won) for calibration check

    for r in rows:
        cid = r.get("condition_id", "")
        no_price = float(r.get("no_price", 0) or 0)
        ai_yes = float(r.get("ai_yes_estimate", 0) or 0)
        if not cid or no_price <= 0:
            unresolved += 1
            continue
        no_won = _resolve_no_outcome(cid)
        if no_won is None:
            unresolved += 1
            continue
        calib.append((ai_yes, no_won))
        if no_won:
            wins += 1
            pnl += FLAT_STAKE * (1.0 / no_price - 1.0)   # payout at NO entry odds
        else:
            losses += 1
            pnl -= FLAT_STAKE

    decided = wins + losses
    print("\n=== STRATEGY SCORECARD (NO on events) ===")
    if decided:
        wr = wins / decided * 100
        roi = pnl / (decided * FLAT_STAKE) * 100
        print(f"  Resolved bets : {decided}  ({unresolved} still open/unresolved)")
        print(f"  Win rate      : {wins}W/{losses}L = {wr:.0f}%")
        print(f"  P&L (${FLAT_STAKE:.0f}/bet): ${pnl:+,.2f}  ·  ROI {roi:+.1f}%")
    else:
        print(f"  No resolved bets yet ({unresolved} pending). Come back later.")

    # AI calibration: when AI said YES was unlikely (low ai_yes), did NO win more?
    if calib:
        print("\n=== AI CALIBRATION (is the estimate trustworthy?) ===")
        for lo, hi in [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]:
            b = [no_won for ay, no_won in calib if lo <= ay < hi]
            if b:
                no_rate = sum(b) / len(b) * 100
                print(f"  AI P(YES) {lo:.2f}-{hi:.2f}: NO won {no_rate:.0f}% (n={len(b)})")
        print("  (lower AI P(YES) should mean NO wins more — if flat, AI adds no signal)")

    # Diversification: max simultaneous open positions.
    print("\n=== DIVERSIFICATION (variance control) ===")
    intervals = []
    for r in rows:
        a = r.get("alerted_at")
        e = r.get("end_date")
        if not a or not e:
            continue
        try:
            start = datetime.fromisoformat(a.replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(e).replace("Z", "+00:00"))
            intervals.append((start, end))
        except Exception:
            continue
    max_concurrent = 0
    if intervals:
        points = []
        for s, e in intervals:
            points.append((s, 1))
            points.append((e, -1))
        points.sort(key=lambda x: x[0])
        cur = 0
        for _, d in points:
            cur += d
            max_concurrent = max(max_concurrent, cur)
    print(f"  Max simultaneous open positions: {max_concurrent} (target ~{TARGET_CONCURRENT})")
    if max_concurrent < TARGET_CONCURRENT:
        print(f"  ⚠️ Below target — too few concurrent bets means variance can sink")
        print(f"     even a real edge. Widen the funnel or wait for more candidates.")


if __name__ == "__main__":
    verify()
