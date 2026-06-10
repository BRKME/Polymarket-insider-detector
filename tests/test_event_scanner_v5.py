"""
Tests for the v5 event-market scanner (event_scanner.py) and the probability
parser in ai_context.py.

These cover the parts the v5 strategy actually relies on:
  • sport/HFT exclusion must not misfire on ordinary words ("beat", "rematch")
  • the suspicious-edge guard must flag likely linked/grouped markets
  • thesis dedup must collapse date-variants of one bet into a single position
  • PROB/CONF parsing must be robust to Grok's formatting drift

Run: python -m pytest tests/test_event_scanner_v5.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import event_scanner as es


# ── helpers ─────────────────────────────────────────────────────────────────

def _market(question, yes, no, liq=50_000, hours_out=240, events=None,
            condition_id="0xabc", slug="s"):
    """Build a minimal Gamma-shaped market dict for tests."""
    from datetime import datetime, timezone, timedelta
    end = (datetime.now(timezone.utc) + timedelta(hours=hours_out)).isoformat()
    m = {
        "question": question,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{yes}", "{no}"]',
        "liquidity": liq,
        "endDate": end,
        "conditionId": condition_id,
        "slug": slug,
    }
    if events is not None:
        m["events"] = events
    return m


def _ai(prob, conf="high", why="test"):
    """A stand-in for estimate_probability with a fixed answer."""
    return lambda _q: {"prob": prob, "conf": conf, "why": why}


# ═══════════════════════════════════════════════════════════════
# Sport / HFT exclusion
# ═══════════════════════════════════════════════════════════════

class TestSportHftExclusion:
    def test_obvious_sport_excluded(self):
        assert es._is_sport_or_hft("Lakers vs Celtics moneyline") is True

    def test_hft_excluded(self):
        assert es._is_sport_or_hft("BTC up or down this hour?") is True

    def test_plain_event_not_excluded(self):
        assert es._is_sport_or_hft(
            "US x Iran permanent peace deal by August 31, 2026?") is False

    # These are the false positives the substring matcher is prone to.
    def test_beat_expectations_not_sport(self):
        # "beat " as a bare substring would wrongly match this economic market.
        assert es._is_sport_or_hft(
            "Will Q3 earnings beat expectations?") is False

    def test_rematch_not_sport(self):
        # "match" as a bare substring would wrongly match "rematch".
        assert es._is_sport_or_hft(
            "Will there be a Trump-Biden rematch announced?") is False


# ═══════════════════════════════════════════════════════════════
# Suspicious-edge guard (likely linked/grouped markets)
# ═══════════════════════════════════════════════════════════════

class TestSuspiciousGuard:
    def test_huge_edge_near_5050_is_suspicious(self):
        # market YES 0.49, AI says 0.02 -> edge 0.47, NO sits at ~0.51 (≈50/50)
        m = _market("Will bitcoin hit $1m before GTA VI?", 0.49, 0.51)
        c = es.evaluate(m, _ai(0.02))
        assert c is not None
        assert c.suspicious is True

    def test_clean_large_edge_not_suspicious(self):
        # big edge but NO is genuinely cheap (0.16) -> not the 50/50 trap
        m = _market("Will candidate X win?", 0.84, 0.16)
        c = es.evaluate(m, _ai(0.55))   # edge 0.29, NO 0.16
        assert c is not None
        assert c.suspicious is False


# ═══════════════════════════════════════════════════════════════
# Thesis dedup — date-variants of one bet must collapse to one
# ═══════════════════════════════════════════════════════════════

class TestThesisDedup:
    def test_iran_date_variants_share_thesis_key(self):
        k1 = es._thesis_key("US x Iran permanent peace deal by August 31, 2026?")
        k2 = es._thesis_key("US x Iran permanent peace deal by October 31, 2026?")
        assert k1 == k2

    def test_scan_keeps_only_best_edge_per_thesis(self):
        aug = _market("US x Iran peace deal by August 31, 2026?",
                      0.42, 0.58, condition_id="0xaug")
        octo = _market("US x Iran peace deal by October 31, 2026?",
                       0.57, 0.43, condition_id="0xoct")
        # AI says 0.12 for both -> Aug edge 0.30, Oct edge 0.45
        out = es.scan([aug, octo], _ai(0.12, conf="medium"))
        assert len(out) == 1
        assert out[0].condition_id == "0xoct"   # the higher-edge variant survives


# ═══════════════════════════════════════════════════════════════
# Structural gate
# ═══════════════════════════════════════════════════════════════

class TestGate:
    def test_no_out_of_band_rejected(self):
        # NO at 0.80 is above NO_ODDS_MAX -> rejected
        m = _market("Will some event happen?", 0.20, 0.80)
        assert es.passes_gate(m) is None

    def test_low_liquidity_rejected(self):
        m = _market("Will some event happen?", 0.70, 0.30, liq=100)
        assert es.passes_gate(m) is None

    def test_named_outcome_market_rejected(self):
        m = _market("Who wins?", 0.40, 0.30)
        m["outcomes"] = '["Trump", "Biden"]'
        m["outcomePrices"] = '["0.40", "0.30"]'
        assert es.passes_gate(m) is None


# ═══════════════════════════════════════════════════════════════
# Probability parser (ai_context._parse_probability)
# ═══════════════════════════════════════════════════════════════

class TestProbabilityParser:
    def _parse(self, text):
        from ai_context import _parse_probability
        return _parse_probability(text)

    def test_standard_format(self):
        r = self._parse("PROB: 45\nCONF: medium\nWHY: some reason")
        assert r["prob"] == 0.45
        assert r["conf"] == "medium"
        assert "reason" in r["why"]

    def test_decimal_percentage(self):
        r = self._parse("PROB: 12.5 / CONF: high / WHY: x")
        assert r["prob"] == 0.125
        assert r["conf"] == "high"

    def test_fallback_to_bare_percentage(self):
        r = self._parse("I estimate about 30% chance. No structured fields.")
        assert r is not None
        assert r["prob"] == 0.30
        assert r["conf"] == "low"   # no CONF field -> defaults low

    def test_unparseable_returns_none(self):
        assert self._parse("no numbers here at all") is None


# ═══════════════════════════════════════════════════════════════
# Calibration logging (scan_events._make_logging_estimator)
# ═══════════════════════════════════════════════════════════════

class TestCalibrationLogging:
    def test_logs_every_estimate_including_rejects(self, tmp_path, monkeypatch):
        import scan_events as se
        monkeypatch.setattr(se, "CALIB", tmp_path / "calib.jsonl")

        # Two markets: one will clear EDGE_MIN, one won't.
        bet = _market("Will big event happen by 2026?", 0.80, 0.20,
                      condition_id="0xbet")
        skip = _market("Will small event happen by 2026?", 0.55, 0.45,
                       condition_id="0xskip")
        markets = [bet, skip]

        # AI says P(YES)=0.40 for both: bet edge 0.40 (>=0.15), skip edge 0.15.
        est_fn = se._make_logging_estimator(markets)
        # Patch the underlying estimator the wrapper calls.
        monkeypatch.setattr(se, "estimate_probability",
                            lambda q: {"prob": 0.40, "conf": "high", "why": "x"})
        # Rebuild wrapper so it closes over the patched estimator.
        est_fn = se._make_logging_estimator(markets)

        est_fn(bet["question"])
        est_fn(skip["question"])

        import json as _json
        lines = (tmp_path / "calib.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2   # BOTH logged, not just the bet
        rows = [_json.loads(l) for l in lines]
        by_cid = {r["condition_id"]: r for r in rows}
        assert by_cid["0xbet"]["would_bet"] is True
        assert by_cid["0xbet"]["market_yes_price"] == 0.80
        assert by_cid["0xbet"]["ai_yes_estimate"] == 0.40
        assert by_cid["0xbet"]["edge"] == 0.40
