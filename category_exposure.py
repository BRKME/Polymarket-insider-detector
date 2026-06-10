"""
category_exposure.py — tag positions by thesis category and show how much of
the bankroll sits in each.

Why: all our NO bets are short "the dramatic thing happens". Twenty of them is
one big short-vol bet on a calm world — a single crisis flips a correlated
cluster at once, and at $15-70 stakes that's the real ruin risk. The exposure
LIMIT stays an operator rule (manual mode, deliberately not enforced in code);
this module only does the counting, so the operator sees the number instead of
keeping a spreadsheet.

Categories are keyword-based and intentionally coarse — they exist to catch
"half my book is one geopolitical thesis", not to be a taxonomy.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional

from config import STAKE_MIN, STAKE_MAX, BANKROLL, CATEGORY_EXPOSURE_CAP

# Order matters: first match wins. Keep markers lowercase.
_CATEGORIES = [
    ("geopolitics", [
        "war", "ceasefire", "peace deal", "invade", "invasion", "missile",
        "nuclear", "sanction", "nato", "iran", "russia", "ukraine", "israel",
        "gaza", "taiwan", "north korea", "strike on", "treaty",
    ]),
    ("crypto", [
        "bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "stablecoin",
        "binance", "coinbase",
    ]),
    ("elections", [
        "election", "president", "presidential", "prime minister", "senate",
        "parliament", "governor", "mayor", "primary", "nominee", "impeach",
    ]),
    ("companies", [
        "ipo", "market cap", "acquisition", "merger", "stock", "earnings",
        "ceo", "spacex", "openai", "tesla", "apple", "nvidia",
    ]),
    ("macro", [
        "fed", "rate cut", "rate hike", "inflation", "cpi", "gdp", "recession",
        "tariff", "shutdown",
    ]),
]


def classify(question: str) -> str:
    """Coarse thesis category for a market question. 'other' if nothing hits."""
    q = f" {str(question).lower()} "
    for cat, markers in _CATEGORIES:
        for m in markers:
            if re.search(r"\b" + re.escape(m) + r"\b", q):
                return cat
    return "other"


def _stake(row: dict) -> float:
    s = row.get("stake_actual")
    try:
        s = float(s)
        if s > 0:
            return s
    except (TypeError, ValueError):
        pass
    return (STAKE_MIN + STAKE_MAX) / 2.0


def exposure_by_category(rows: List[dict]) -> Dict[str, float]:
    """Dollars at risk per category across OPEN positions.

    Uses the on-chain stake when present, the stake-range midpoint otherwise.
    Rows without a stored category are classified on the fly from the question.
    """
    out: Dict[str, float] = {}
    for r in rows:
        if str(r.get("status", "open")).lower() != "open":
            continue
        cat = r.get("category") or classify(r.get("question", ""))
        out[cat] = out.get(cat, 0.0) + _stake(r)
    return out


def over_cap(exposure: Dict[str, float], bankroll: float = BANKROLL,
             cap: float = CATEGORY_EXPOSURE_CAP) -> Dict[str, float]:
    """Categories whose exposure exceeds cap*bankroll -> {cat: fraction}."""
    if bankroll <= 0:
        return {}
    warns = {}
    for cat, usd in exposure.items():
        frac = usd / bankroll
        if frac > cap:
            warns[cat] = round(frac, 3)
    return warns


def format_exposure(exposure: Dict[str, float],
                    bankroll: float = BANKROLL) -> str:
    """One human line: 'geopolitics $40 (4%) · crypto $25 (2%)'."""
    if not exposure:
        return "экспозиция: нет открытых позиций"
    parts = []
    for cat, usd in sorted(exposure.items(), key=lambda kv: -kv[1]):
        pct = (usd / bankroll * 100) if bankroll > 0 else 0
        parts.append(f"{cat} ${usd:.0f} ({pct:.0f}%)")
    return "экспозиция: " + " · ".join(parts)
