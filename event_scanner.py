"""
event_scanner.py — direct event-market scanner (v5 strategy).

Replaces the whale-copy approach. Instead of reacting to large trades (which
skew toward sports, where we have no edge), we scan event markets directly and
flag the only region with a validated, theory-backed edge:

    EVENT (not sport) + NO side underpriced + market overprices YES.

Edge source: optimism/longshot bias on binary event markets. Crowds overpay for
"YES, it will happen", so NO is systematically underpriced. Confirmed in our data
(NO on events: WR ~81%). Sport has no such bias and is excluded.

Pipeline:
  1. Fetch active markets (collector.get_active_markets / priority).
  2. Gate: event-only, binary, NO in [0.10, 0.50], min liquidity, time window.
  3. AI estimates true P(YES). Trade only if market overprices YES by >= EDGE_MIN.
  4. Emit candidate with explicit "market X% vs estimate Y%" reasoning.

This module is pure logic + Gamma reads. AI call is injected so it can be tested
offline. No keys handled here.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable

from config import (
    ODDS_FILTER_MIN, ODDS_FILTER_MAX,
)

# ── Strategy constants (frozen; see changelog) ─────────────────────────────
NO_ODDS_MIN = 0.07          # skip NO cheaper than this (resolution-risk longshots)
NO_ODDS_MAX = 0.60          # widened from 0.50 to capture more event mispricing
CORE_NO_MIN = 0.10          # validated "core" band (for journal tagging)
CORE_NO_MAX = 0.50
MIN_LIQUIDITY = 5_000       # $ — thin markets have unreliable prices & bad fills
MIN_HOURS_TO_RESOLVE = 12   # avoid HFT/last-minute markets (lower bound only)
MAX_DAYS_TO_RESOLVE = None  # no upper cap — event markets resolve months out
EDGE_MIN = 0.15             # required gap: market P(YES) - AI P(YES) >= 15pp
# Suspicious-edge guard: in an honest single market, NO price ≈ P(NO). If the
# AI claims a huge mispricing (edge >= SUSPICIOUS_EDGE) yet the market still
# prices NO near 50/50, the market disagrees with us hard — usually because it's
# a LINKED/grouped market ("what happens first") where our single-event logic
# doesn't apply. Flag, don't trust.
SUSPICIOUS_EDGE = 0.35
SUSPICIOUS_NO_LOW = 0.40    # NO price band where a huge edge is implausible
SUSPICIOUS_NO_HIGH = 0.60
MIN_CONFIDENCE = "medium"   # ignore low-confidence AI estimates (too noisy to trade)
_CONF_RANK = {"low": 0, "medium": 1, "high": 2}

# Sport / HFT exclusion — these are the streams where we have NO edge.
SPORT_MARKERS = [
    " vs ", " vs. ", "win on", "beat ", "handicap", "-1.5", "+1.5", "-2.5", "+2.5",
    "moneyline", "nba", "nfl", "nhl", "mlb", "wta", "atp", "fifa", "ucl", "epl",
    "la liga", "serie a", "bundesliga", "friendly", "match", "vs the",
]
HFT_MARKERS = ["15m", "15 min", "updown", "up or down", "this hour", "next hour"]


@dataclass
class Candidate:
    question: str
    condition_id: str
    market_yes_price: float     # market-implied P(YES)
    no_price: float             # price of the NO token (our entry)
    ai_yes_estimate: float      # AI's independent P(YES)
    edge: float                 # market_yes_price - ai_yes_estimate
    liquidity: float
    end_date: str
    reasoning: str
    slug: str = ""               # market slug (fallback)
    event_slug: str = ""         # event slug — this is what /event/<slug> needs
    band: str = "core"          # "core" (0.10-0.50, validated) or "extended"
    suspicious: bool = False    # likely a linked/grouped market — treat with care

    def to_alert(self) -> Dict:
        return asdict(self)


def _is_sport_or_hft(question: str) -> bool:
    q = f" {question.lower()} "
    return any(m in q for m in SPORT_MARKERS) or any(m in q for m in HFT_MARKERS)


def _parse_prices(market: Dict) -> Optional[tuple]:
    """Return (yes_price, no_price) for a binary Yes/No market, else None."""
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    # Gamma returns these as JSON strings sometimes.
    if isinstance(outcomes, str):
        try: outcomes = json.loads(outcomes)
        except Exception: return None
    if isinstance(prices, str):
        try: prices = json.loads(prices)
        except Exception: return None
    if not outcomes or not prices or len(outcomes) != 2 or len(prices) != 2:
        return None
    labels = [str(o).strip().lower() for o in outcomes]
    if set(labels) != {"yes", "no"}:
        return None  # named / multi-outcome market — no YES/NO bias to exploit
    try:
        pmap = {labels[i]: float(prices[i]) for i in range(2)}
    except Exception:
        return None
    yes, no = pmap.get("yes", 0.0), pmap.get("no", 0.0)
    if not (0 < yes < 1 and 0 < no < 1):
        return None
    return yes, no


def _hours_to_resolve(market: Dict) -> Optional[float]:
    ed = market.get("endDate") or market.get("end_date")
    if not ed:
        return None
    try:
        end = datetime.fromisoformat(str(ed).replace("Z", "+00:00"))
        return (end - datetime.now(timezone.utc)).total_seconds() / 3600
    except Exception:
        return None


def passes_gate(market: Dict) -> Optional[tuple]:
    """
    Structural gate (no AI yet). Returns (yes_price, no_price, liq, hours) if the
    market is a tradeable event-NO candidate, else None.
    """
    q = market.get("question", "") or market.get("title", "")
    if not q or _is_sport_or_hft(q):
        return None

    parsed = _parse_prices(market)
    if not parsed:
        return None
    yes_price, no_price = parsed

    # NO must be in the underpriced band.
    if not (NO_ODDS_MIN <= no_price < NO_ODDS_MAX):
        return None

    liq = float(market.get("liquidity", 0) or market.get("volume", 0) or 0)
    if liq < MIN_LIQUIDITY:
        return None

    hrs = _hours_to_resolve(market)
    if hrs is None or hrs < MIN_HOURS_TO_RESOLVE:
        return None
    if MAX_DAYS_TO_RESOLVE is not None and hrs > MAX_DAYS_TO_RESOLVE * 24:
        return None

    return yes_price, no_price, liq, hrs


def evaluate(market: Dict, ai_estimate_fn: Callable[[str], Optional[dict]]) -> Optional[Candidate]:
    """
    Full evaluation: structural gate + AI mispricing check.
    `ai_estimate_fn(question)` returns {"prob": 0..1, "conf": str, "why": str} or None.
    Injected for testability.
    """
    gated = passes_gate(market)
    if not gated:
        return None
    yes_price, no_price, liq, _ = gated

    q = market.get("question", "") or market.get("title", "")
    est = ai_estimate_fn(q)
    if not est or est.get("prob") is None:
        return None

    # Skip low-confidence estimates — they're too noisy to bet on.
    if _CONF_RANK.get(est.get("conf", "low"), 0) < _CONF_RANK[MIN_CONFIDENCE]:
        return None

    ai_yes = float(est["prob"])
    if not (0 <= ai_yes <= 1):
        return None

    edge = yes_price - ai_yes          # market overprices YES by this much
    if edge < EDGE_MIN:
        return None                    # not enough mispricing — skip

    suspicious = (edge >= SUSPICIOUS_EDGE
                  and SUSPICIOUS_NO_LOW <= no_price <= SUSPICIOUS_NO_HIGH)

    why = est.get("why", "")
    reasoning = (
        f"Рынок оценивает YES в {yes_price*100:.0f}%, "
        f"независимая оценка — {ai_yes*100:.0f}% (увер.: {est.get('conf')}). "
        f"YES переоценён на {edge*100:.0f} п.п. → NO недооценён. "
        f"Вход в NO по {no_price*100:.0f}%."
    )
    if suspicious:
        reasoning = (
            f"⚠️ ПОДОЗРИТЕЛЬНО: разрыв {edge*100:.0f} п.п., но NO стоит "
            f"{no_price*100:.0f}% (≈50/50). Вероятно связанный/групповой рынок — "
            f"наша логика одиночного события может не работать. Проверь вручную.\n"
            + reasoning
        )
    if why:
        reasoning += f"\n{why}"
    # The site opens markets at /event/<eventSlug>. Market.slug often carries a
    # numeric conditionId tail that 404s. Prefer the parent event's slug.
    ev_slug = ""
    events = market.get("events")
    if isinstance(events, list) and events and isinstance(events[0], dict):
        ev_slug = events[0].get("slug", "") or ""
    if not ev_slug:
        ev_slug = market.get("eventSlug", "") or ""

    return Candidate(
        question=q,
        condition_id=market.get("conditionId", ""),
        market_yes_price=round(yes_price, 4),
        no_price=round(no_price, 4),
        ai_yes_estimate=round(ai_yes, 4),
        edge=round(edge, 4),
        liquidity=round(liq, 2),
        end_date=str(market.get("endDate", "")),
        reasoning=reasoning,
        slug=market.get("slug", ""),
        event_slug=ev_slug,
        band=("core" if CORE_NO_MIN <= no_price < CORE_NO_MAX else "extended"),
        suspicious=suspicious,
    )


def _thesis_key(question: str) -> str:
    """Collapse near-identical questions (same event, different date) to one key.

    'US x Iran peace deal by August 31' and '...by October 31' share a thesis;
    betting both isn't diversification, it's one doubled position. We strip
    dates/months/years and keep the stable head of the question.
    """
    import re as _re
    q = question.lower()
    q = _re.sub(r'\b(by|before|on|until)\b.*$', '', q)          # drop "by <date>" tail
    q = _re.sub(r'\b\d{4}\b', '', q)                            # years
    q = _re.sub(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b', '', q)
    q = _re.sub(r'[^a-z0-9 ]', ' ', q)
    q = _re.sub(r'\s+', ' ', q).strip()
    return ' '.join(q.split()[:6])      # stable head


def scan(markets: List[Dict], ai_estimate_fn: Callable[[str], Optional[dict]]) -> List[Candidate]:
    """Run the full pipeline, dedup theses, return ranked candidates."""
    out = []
    for m in markets:
        try:
            c = evaluate(m, ai_estimate_fn)
            if c:
                out.append(c)
        except Exception:
            continue

    # Dedup by thesis: keep the single best-edge candidate per thesis so two
    # date-variants of the same bet don't masquerade as two positions.
    best: Dict[str, Candidate] = {}
    for c in out:
        k = _thesis_key(c.question)
        if k not in best or c.edge > best[k].edge:
            best[k] = c
    deduped = list(best.values())

    # Clean (non-suspicious) candidates first, then by edge.
    deduped.sort(key=lambda c: (c.suspicious, -c.edge))
    return deduped
