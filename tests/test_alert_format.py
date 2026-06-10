"""
Tests for the compact alert format (scan_events._format_alert) and the
reasoning/presentation split in event_scanner.

The old format repeated the same numbers three times (header, prose paragraph,
entry line) across four divider rules. The new contract:
  • the decision lives in the first line: NO price · edge · deadline
  • Grok's estimate vs market is ONE line; Grok's why is ONE line
  • suspicious is ONE warning line, not a paragraph
  • no '—————' dividers, no prose restating the header

Run: python -m pytest tests/test_alert_format.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import event_scanner as es
import scan_events as se


def _candidate(**kw):
    base = dict(
        question="US-Iran nuclear deal before 2027?",
        condition_id="0xAAA",
        market_yes_price=0.64,
        no_price=0.36,
        ai_yes_estimate=0.28,
        edge=0.36,
        liquidity=134497.0,
        end_date="2026-12-31T12:00:00Z",
        reasoning="Persistent core disagreements make a full deal unlikely",
        ai_conf="medium",
        event_slug="us-iran-nuclear-deal-before-2027",
    )
    base.update(kw)
    return es.Candidate(**base)


class TestReasoningIsJustWhy:
    def test_evaluate_reasoning_carries_only_grok_why(self):
        from datetime import datetime, timezone, timedelta
        end = (datetime.now(timezone.utc) + timedelta(days=100)).isoformat()
        m = {"question": "Will X happen?", "outcomes": '["Yes","No"]',
             "outcomePrices": '["0.80","0.20"]', "liquidity": 50000,
             "endDate": end, "conditionId": "0x1"}
        c = es.evaluate(m, lambda q, d=None, e=None: {
            "prob": 0.30, "conf": "high", "why": "clean structural reason"})
        assert c.reasoning == "clean structural reason"
        # no duplicated prose restating the numbers
        assert "переоценён" not in c.reasoning
        assert c.ai_conf == "high"


class TestCompactAlert:
    def test_first_line_carries_the_decision(self):
        msg = se._format_alert(_candidate())
        first = msg.splitlines()[0]
        assert "NO 36%" in first
        assert "36пп" in first or "36 пп" in first
        assert "2026" in first

    def test_one_line_estimate_comparison(self):
        msg = se._format_alert(_candidate())
        assert "Grok: YES 28% (medium)" in msg
        assert "рынок: 64%" in msg

    def test_no_dividers_and_no_duplicated_prose(self):
        msg = se._format_alert(_candidate())
        assert "—————" not in msg
        assert "переоценён" not in msg
        # the why is present exactly once
        assert msg.count("Persistent core disagreements") == 1

    def test_suspicious_is_one_line(self):
        msg = se._format_alert(_candidate(suspicious=True, no_price=0.56,
                                          market_yes_price=0.44, edge=0.36))
        assert "связанный" in msg or "групповой" in msg
        # a single warning line, not the old paragraph
        warn_lines = [l for l in msg.splitlines() if "⚠️" in l and "связан" in l]
        assert len(warn_lines) == 1

    def test_link_present(self):
        msg = se._format_alert(_candidate())
        assert "polymarket.com/event/us-iran-nuclear-deal-before-2027" in msg
