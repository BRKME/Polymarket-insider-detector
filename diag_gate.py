"""
diag_gate.py — one-off diagnostic. Shows WHY markets fail the structural gate
on live Gamma data. Run once in Actions, read the log, then delete.
"""
import json
import collector
import event_scanner as es

markets = collector.get_active_markets(limit=100)
print(f"fetched {len(markets)} markets\n")

# Show raw field shapes of the first market
if markets:
    m0 = markets[0]
    print("=== sample market field types ===")
    for k in ("question", "outcomes", "outcomePrices", "liquidity", "volume",
              "endDate", "conditionId", "slug", "active", "closed"):
        v = m0.get(k)
        print(f"  {k}: {type(v).__name__} = {repr(v)[:80]}")
    print()

# Count failures per gate stage
reasons = {"sport_or_hft": 0, "not_binary_yesno": 0, "no_out_of_band": 0,
           "low_liquidity": 0, "bad_time": 0, "PASS": 0}
no_prices_seen = []
liq_seen = []

for m in markets:
    q = m.get("question", "") or m.get("title", "")
    if not q or es._is_sport_or_hft(q):
        reasons["sport_or_hft"] += 1
        continue
    parsed = es._parse_prices(m)
    if not parsed:
        reasons["not_binary_yesno"] += 1
        continue
    yes, no = parsed
    no_prices_seen.append(round(no, 2))
    if not (es.NO_ODDS_MIN <= no < es.NO_ODDS_MAX):
        reasons["no_out_of_band"] += 1
        continue
    liq = float(m.get("liquidity", 0) or m.get("volume", 0) or 0)
    liq_seen.append(liq)
    if liq < es.MIN_LIQUIDITY:
        reasons["low_liquidity"] += 1
        continue
    hrs = es._hours_to_resolve(m)
    if hrs is None or not (es.MIN_HOURS_TO_RESOLVE <= hrs <= es.MAX_DAYS_TO_RESOLVE * 24):
        reasons["bad_time"] += 1
        continue
    reasons["PASS"] += 1

print("=== gate funnel (100 markets) ===")
for k, v in reasons.items():
    print(f"  {k}: {v}")
print()
print(f"NO prices seen (binary mkts): n={len(no_prices_seen)}")
if no_prices_seen:
    print(f"  sample: {sorted(no_prices_seen)[:20]}")
    in_band = [p for p in no_prices_seen if 0.10 <= p < 0.50]
    print(f"  in 0.10-0.50 band: {len(in_band)}")
if liq_seen:
    print(f"liquidity of band-passing mkts: sample {sorted(liq_seen)[:10]}")
