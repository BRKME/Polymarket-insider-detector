"""
diag_sources.py — probe how to get EVENT markets WITH prices + liquidity.

The volume-sorted /markets feed returns HFT junk with null prices. This tries
several strategies and prints what each returns, so we can pick the right loader.
Run once in Actions, read the log, then we build the real loader from facts.
"""
import json
import requests
from config import GAMMA_API_URL, CLOB_API_URL

S = requests.Session()
S.headers.update({"User-Agent": "pm-diag"})


def show(title, market):
    print(f"  [{title}]")
    for k in ("question", "outcomes", "outcomePrices", "liquidity", "liquidityNum",
              "volume", "volumeNum", "volume24hr", "endDate", "active", "closed",
              "clobTokenIds", "conditionId", "slug"):
        if k in market:
            print(f"    {k}: {type(market[k]).__name__} = {repr(market[k])[:70]}")
    print()


print("=" * 60)
print("STRATEGY 1: /markets active, sorted by liquidity (not volume)")
print("=" * 60)
try:
    r = S.get(f"{GAMMA_API_URL}/markets", params={
        "active": "true", "closed": "false", "limit": 5,
        "order": "liquidityNum", "ascending": "false",
    }, timeout=30)
    print(f"  HTTP {r.status_code}, returned {len(r.json())} markets")
    data = r.json()
    has_prices = sum(1 for m in data if m.get("outcomePrices"))
    print(f"  with non-null outcomePrices: {has_prices}/{len(data)}")
    if data:
        show("sample", data[0])
except Exception as e:
    print(f"  ERROR: {e}\n")

print("=" * 60)
print("STRATEGY 2: /events (grouped), active, by volume")
print("=" * 60)
try:
    r = S.get(f"{GAMMA_API_URL}/events", params={
        "active": "true", "closed": "false", "limit": 3, "order": "volume24hr",
        "ascending": "false",
    }, timeout=30)
    print(f"  HTTP {r.status_code}")
    data = r.json()
    print(f"  returned {len(data)} events")
    if data:
        ev = data[0]
        print(f"  event title: {ev.get('title')!r}")
        mkts = ev.get("markets", [])
        print(f"  markets in event: {len(mkts)}")
        if mkts:
            show("first market in event", mkts[0])
except Exception as e:
    print(f"  ERROR: {e}\n")

print("=" * 60)
print("STRATEGY 3: CLOB price for a token (if strat 1 gave clobTokenIds)")
print("=" * 60)
try:
    r = S.get(f"{GAMMA_API_URL}/markets", params={
        "active": "true", "closed": "false", "limit": 20, "order": "liquidityNum",
        "ascending": "false",
    }, timeout=30)
    data = r.json()
    # find a binary Yes/No market with clobTokenIds
    target = None
    for m in data:
        outs = m.get("outcomes")
        if isinstance(outs, str):
            try: outs = json.loads(outs)
            except Exception: outs = []
        labels = {str(o).strip().lower() for o in (outs or [])}
        if labels == {"yes", "no"} and m.get("clobTokenIds"):
            target = m
            break
    if not target:
        print("  no binary Yes/No market with clobTokenIds found in top-20 by liquidity")
    else:
        toks = target.get("clobTokenIds")
        if isinstance(toks, str):
            toks = json.loads(toks)
        print(f"  market: {target.get('question')!r}")
        print(f"  clobTokenIds: {toks}")
        # try CLOB price endpoint for first token
        tok = toks[0]
        for ep in (f"{CLOB_API_URL}/price?token_id={tok}&side=buy",
                   f"{CLOB_API_URL}/midpoint?token_id={tok}"):
            try:
                pr = S.get(ep, timeout=15)
                print(f"  {ep[:55]}... -> HTTP {pr.status_code} {pr.text[:80]}")
            except Exception as e:
                print(f"  {ep[:55]}... -> ERR {e}")
except Exception as e:
    print(f"  ERROR: {e}")
