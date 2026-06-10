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
import ai_cache
from ai_context import estimate_probability

JOURNAL = Path("event_journal.jsonl")   # one JSON line per alerted candidate
CALIB = Path("calibration_journal.jsonl")  # one line per AI estimate (paid-for data)
SEEN = Path("event_seen.json")          # condition_ids already alerted
AI_CACHE = Path("ai_cache.json")        # cached Grok estimates per condition_id
MARKET_FETCH_LIMIT = 1000                # deeper slice — more mid-liquidity events
MAX_AI_CALLS = 40                        # cap Grok calls per run (cost control)


def _load_ai_cache() -> dict:
    if AI_CACHE.exists():
        try:
            d = json.loads(AI_CACHE.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _save_ai_cache(store: dict) -> None:
    try:
        AI_CACHE.write_text(json.dumps(store, ensure_ascii=False, sort_keys=True))
    except Exception as e:
        print(f"  ⚠️ ai_cache save failed: {e}")


# Re-alert when a previously-seen market's edge has grown by at least this much.
# A market we passed on at 12pp but that's now 25pp is a genuinely better setup,
# not a duplicate — suppressing it forever loses real signal.
REALERT_EDGE_GROWTH = 0.10


def _normalize_seen(raw) -> dict:
    """Accept either the legacy flat list of cids or the new dict form.

    Legacy entries get last_edge=None so the next scan alerts once (capturing
    their edge), instead of being silently suppressed forever.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {cid: {"last_edge": None, "alerted_at": None, "resolved": False}
                for cid in raw}
    return {}


def _load_seen() -> dict:
    if SEEN.exists():
        try:
            return _normalize_seen(json.loads(SEEN.read_text()))
        except Exception:
            return {}
    return {}


def _save_seen(seen: dict) -> None:
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, sort_keys=True, indent=0))


def _should_skip_pre_ai(cid: str, seen: dict) -> bool:
    """Skip BEFORE spending an AI call only if the market is resolved.

    We deliberately do NOT skip merely-seen markets here: their edge may have
    grown, and we can't know without a fresh estimate. Cost is bounded by
    MAX_AI_CALLS anyway. Resolved markets are dead — always skip.
    """
    entry = seen.get(cid)
    if not entry:
        return False
    return bool(entry.get("resolved"))


def _should_alert(cid: str, current_edge: float, seen: dict) -> bool:
    """Post-AI: alert if new, or if edge grew materially since last alert."""
    entry = seen.get(cid)
    if not entry:
        return True                      # never seen — alert
    last = entry.get("last_edge")
    if last is None:
        return True                      # migrated/legacy — alert once to record
    return (current_edge - last) >= REALERT_EDGE_GROWTH


def _prune_seen(seen: dict, resolved_cids: set) -> dict:
    """Drop resolved markets from state so the file doesn't grow without bound."""
    return {cid: v for cid, v in seen.items() if cid not in resolved_cids}


def _load_journal_rows() -> list:
    """Read journal rows (for prune-by-resolved). Empty if no journal yet."""
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


def _append_journal(candidate: es.Candidate) -> None:
    row = candidate.to_alert()
    row["alerted_at"] = datetime.now(timezone.utc).isoformat()
    row["bet_side"] = "NO"
    row["stake_plan"] = "manual $15-70 flat"
    row["status"] = "open"          # mark-to-market scans only open positions
    # Thesis category — powers the exposure-by-category visibility. The limit
    # itself is an operator rule; we just make the number visible.
    try:
        import category_exposure as cx
        row["category"] = cx.classify(candidate.question)
    except Exception:
        row["category"] = "other"
    # horizon in days from alert to resolution — lets verify_journal split the
    # Brier by horizon so the verdict on short bets doesn't wait for 2027.
    try:
        end = datetime.fromisoformat(str(candidate.end_date).replace("Z", "+00:00"))
        row["horizon_days"] = round(
            (end - datetime.now(timezone.utc)).total_seconds() / 86400, 1)
    except Exception:
        row["horizon_days"] = None
    # Filled by hand after placing the bet — verification prefers these over the
    # alert-time price/stake so it scores what was actually traded, not theory.
    row["entry_price_actual"] = None
    row["stake_actual"] = None
    with JOURNAL.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_calibration(row: dict) -> None:
    """One line per AI estimate — including rejected markets.

    We pay for every Grok call regardless of whether the market clears EDGE_MIN.
    Logging *all* of them turns the rejects into free calibration data: later we
    can score Grok's P(YES) against real outcomes (Brier) and, crucially, compare
    it to the market price's own Brier on the same markets. That comparison is
    the single question this whole strategy rests on — does Grok beat the crowd?
    The bet journal alone can't answer it (it's the selected, biased tail).
    """
    with CALIB.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _make_logging_estimator(markets: list):
    """Wrap estimate_probability so every call is journalled for calibration.

    `markets` is the gated slice we're about to evaluate. We index it by question
    text so the wrapper can attach the market's price/liquidity/condition_id to
    each logged estimate, even for markets that later get rejected on edge.
    """
    by_q = {}
    for m in markets:
        q = m.get("question", "") or m.get("title", "")
        if q:
            by_q[q] = m
    run_ts = datetime.now(timezone.utc).isoformat()

    # Per-condition_id cache so a 6h re-scan of the same slow market doesn't pay
    # for a fresh Grok call. Invalidated by age or a >5pp YES-price move.
    cache_store = _load_ai_cache()

    def _yes_for(question: str):
        m = by_q.get(question, {})
        parsed = es._parse_prices(m) if m else None
        return parsed[0] if parsed else None

    def _cid_for(question: str):
        return by_q.get(question, {}).get("conditionId", "")

    cached_real = ai_cache.make_cached_estimator(
        estimate_probability, cache_store, cid_for=_cid_for, yes_for=_yes_for)

    def _estimator(question: str, description: str = None, end_date: str = None):
        cid = _cid_for(question)
        was_cached = cid in cache_store and ai_cache.is_valid(
            cache_store.get(cid, {}), __import__("time").time(),
            _yes_for(question) or -1)
        est = cached_real(question, description, end_date)
        m = by_q.get(question, {})
        parsed = es._parse_prices(m) if m else None
        yes_price = round(parsed[0], 4) if parsed else None
        no_price = round(parsed[1], 4) if parsed else None
        ai_yes = est.get("prob") if est else None
        edge = (round(yes_price - ai_yes, 4)
                if (yes_price is not None and ai_yes is not None) else None)
        # horizon to resolution — lets the Brier verdict split short vs long so
        # short-horizon bets give an early read without waiting on 2027 resolves.
        horizon_days = None
        try:
            from datetime import datetime as _dt
            _end = _dt.fromisoformat(str(m.get("endDate", "")).replace("Z", "+00:00"))
            horizon_days = round(
                (_end - _dt.now(timezone.utc)).total_seconds() / 86400, 1)
        except Exception:
            pass
        # Only log calibration on a REAL Grok call — a cache hit is the same
        # estimate and would double-count in the Brier sample.
        if not was_cached:
          try:
            _append_calibration({
                "estimated_at": run_ts,
                "condition_id": m.get("conditionId", ""),
                "question": question,
                "market_yes_price": yes_price,   # the crowd's P(YES) — baseline
                "no_price": no_price,
                "ai_yes_estimate": ai_yes,       # Grok's P(YES) — what we score
                "ai_conf": est.get("conf") if est else None,
                "edge": edge,
                "liquidity": round(float(m.get("liquidity", 0) or 0), 2),
                "end_date": str(m.get("endDate", "")),
                "horizon_days": horizon_days,
                # Will this market produce a NO bet? (mirrors scanner thresholds)
                "would_bet": bool(
                    est and ai_yes is not None and edge is not None
                    and edge >= es.EDGE_MIN
                    and es._CONF_RANK.get(est.get("conf", "low"), 0)
                        >= es._CONF_RANK[es.MIN_CONFIDENCE]
                ),
            })
          except Exception as e:
            print(f"  ⚠️ calibration log failed: {e}")
        return est

    # expose the cache store so run() can persist it after the scan
    _estimator._cache_store = cache_store
    return _estimator


def _market_url(c: es.Candidate) -> str:
    # /event/<eventSlug> is the only slug the site reliably resolves. The market
    # slug carries a numeric id tail that 404s and can't be safely trimmed
    # (the date looks like the same tail), so we don't guess — if there's no
    # event slug, link to a site search by the question, which always resolves.
    if c.event_slug:
        return f"https://polymarket.com/event/{c.event_slug}"
    from urllib.parse import quote_plus
    return f"https://polymarket.com/markets?_q={quote_plus(c.question)}"


def _format_alert(c: es.Candidate) -> str:
    """Compact alert: the decision in line 1, one line of context, one of action.

    The old format restated the same numbers three times across four divider
    rules. Contract now: NO price · edge · deadline up top; Grok-vs-market in
    one line; Grok's why in one line; suspicious is a single warning line.
    """
    if c.suspicious:
        fire = "⚠️"
    elif c.edge >= 0.25:
        fire = "🔥"
    else:
        fire = "✅"
    url = _market_url(c)

    # deadline + days to go
    end = c.end_date[:10] if c.end_date else "?"
    days = ""
    try:
        _end = datetime.fromisoformat(str(c.end_date).replace("Z", "+00:00"))
        d = int((_end - datetime.now(timezone.utc)).total_seconds() // 86400)
        if d >= 0:
            days = f" ({d}д)"
    except Exception:
        pass

    # suggested stake — scaled by edge & book depth, rounded to $5
    size_part = ""
    try:
        from config import STAKE_MIN, STAKE_MAX
        edge_factor = max(0.0, min(1.0, (c.edge - es.EDGE_MIN) / 0.25))
        liq_ok = c.liquidity >= 3 * es.MIN_LIQUIDITY
        size = STAKE_MIN + (STAKE_MAX - STAKE_MIN) * edge_factor * (1.0 if liq_ok else 0.5)
        size = round(size / 5) * 5
        size_part = f"Размер ~${size:.0f}"
    except Exception:
        pass

    # category + current cluster load at sizing time
    cat_part = ""
    try:
        import category_exposure as cx
        from config import BANKROLL, CATEGORY_EXPOSURE_CAP
        cat = cx.classify(c.question)
        cur = cx.exposure_by_category(_load_journal_rows()).get(cat, 0.0)
        pct = cur / BANKROLL * 100 if BANKROLL > 0 else 0
        warn = " ⚠️ЛИМИТ" if BANKROLL > 0 and \
            (cur / BANKROLL) > CATEGORY_EXPOSURE_CAP else ""
        cat_part = f"{cat}: открыто ${cur:.0f} ({pct:.0f}% банка){warn}"
    except Exception:
        pass
    size_line = " · ".join(p for p in (size_part, cat_part) if p)

    liq_k = f"${c.liquidity/1000:.0f}k" if c.liquidity >= 1000 else f"${c.liquidity:.0f}"
    lines = [
        f"{fire} NO {c.no_price*100:.0f}% · edge {c.edge*100:.0f}пп · до {end}{days}",
        f"{c.question}",
        "",
        f"Grok: YES {c.ai_yes_estimate*100:.0f}% ({c.ai_conf}) · "
        f"рынок: {c.market_yes_price*100:.0f}% · ликв. {liq_k}",
    ]
    if c.reasoning:
        lines.append(f"→ {c.reasoning}")
    if c.suspicious:
        lines.append("⚠️ Похоже на связанный/групповой рынок — читай правила резолва")
    lines.append("")
    if size_line:
        lines.append(size_line)
    lines.append("Перед входом: цена → правила резолва → лимит")
    if url:
        lines.append(f"🔗 {url}")
    return "\n".join(lines)


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
    # Prune resolved markets from seen state so the file doesn't grow forever.
    # A position closed in the journal is resolved/exited — its cid is dead.
    try:
        resolved = {r.get("condition_id", "") for r in _load_journal_rows()
                    if str(r.get("status", "open")).lower() == "closed"}
        if resolved:
            before = len(seen)
            seen = _prune_seen(seen, resolved)
            if len(seen) < before:
                print(f"  pruned {before - len(seen)} resolved cids from seen")
    except Exception:
        pass

    markets = collector.get_active_markets(limit=MARKET_FETCH_LIMIT)
    print(f"  fetched {len(markets)} active markets")

    # Show the raw field shapes of the first market once — lets us spot when
    # live Gamma returns prices/liquidity in a different format than expected.
    if markets:
        m0 = markets[0]
        print("  --- sample market fields ---")
        for k in ("question", "outcomes", "outcomePrices", "liquidity",
                  "volume", "endDate", "conditionId", "slug", "eventSlug"):
            print(f"    {k}: {type(m0.get(k)).__name__} = {repr(m0.get(k))[:70]}")

    # Cheap structural gate first (no AI). Track WHY each market fails so a
    # zero-candidate run is debuggable from the log alone.
    funnel = {"sport_or_hft": 0, "not_binary_yesno": 0, "no_out_of_band": 0,
              "low_liquidity": 0, "bad_time": 0, "already_seen": 0, "PASS": 0}
    no_band_count = 0
    gated = []
    for m in markets:
        cid = m.get("conditionId", "")
        if _should_skip_pre_ai(cid, seen):
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
        too_late = (es.MAX_DAYS_TO_RESOLVE is not None
                    and hrs is not None and hrs > es.MAX_DAYS_TO_RESOLVE * 24)
        if hrs is None or hrs < es.MIN_HOURS_TO_RESOLVE or too_late:
            funnel["bad_time"] += 1
            continue
        funnel["PASS"] += 1
        gated.append(m)

    print(f"  --- gate funnel ---")
    for k, v in funnel.items():
        print(f"    {k}: {v}")
    print(f"  {len(gated)} passed structural gate (event + NO {es.NO_ODDS_MIN}-{es.NO_ODDS_MAX} + liquid)")

    # The AI-call cap slices the FRONT of this list, so order matters: with raw
    # Gamma order the best candidates can fall past the cap and never get an AI
    # estimate. Prioritise (1) NO inside the validated core band 0.10-0.50, then
    # (2) NO nearest the centre of that band (where the event-bias edge is
    # cleanest), then (3) deeper liquidity (better fills, more reliable price).
    def _priority(m):
        parsed = es._parse_prices(m) or (0.0, 0.0)
        no_price = parsed[1]
        in_core = es.CORE_NO_MIN <= no_price < es.CORE_NO_MAX
        core_centre = (es.CORE_NO_MIN + es.CORE_NO_MAX) / 2
        liq = float(m.get("liquidity", 0) or m.get("volume", 0) or 0)
        # sort key: core first (False<True so negate), then closeness to centre,
        # then more liquidity first (negate).
        return (not in_core, abs(no_price - core_centre), -liq)

    gated.sort(key=_priority)
    gated = gated[:MAX_AI_CALLS]  # cost cap (now applied to the best slice)

    # Wrap the estimator so every Grok call (rejects included) lands in the
    # calibration journal — see _append_calibration for why this matters.
    logging_estimator = _make_logging_estimator(gated)
    candidates = es.scan(gated, logging_estimator)
    print(f"  {len(candidates)} candidates after AI mispricing check")

    sent = 0
    suppressed = 0
    now = datetime.now(timezone.utc).isoformat()
    for c in candidates:
        cid = c.condition_id
        if not _should_alert(cid, c.edge, seen):
            # already alerted and edge hasn't grown enough — record latest edge
            # for future comparison, but don't re-fire or duplicate the journal.
            if cid in seen:
                seen[cid]["last_edge"] = c.edge
            suppressed += 1
            continue
        if _send(_format_alert(c)):
            sent += 1
        _append_journal(c)
        seen[cid] = {"last_edge": c.edge, "alerted_at": now, "resolved": False}

    _save_seen(seen)
    # Persist the AI estimate cache for the next run.
    if hasattr(logging_estimator, "_cache_store"):
        _save_ai_cache(logging_estimator._cache_store)
    print(f"[{datetime.now()}] done — {sent} alerts sent, "
          f"{suppressed} suppressed (seen), journal updated")


if __name__ == "__main__":
    run()
