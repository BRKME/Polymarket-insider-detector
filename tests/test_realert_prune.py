"""
Tests for the re-alert / prune logic on event_seen state (scan_events).

Old behaviour: event_seen was a flat set of condition_ids. Once a market was
alerted it was suppressed forever — even if its edge later grew a lot — and the
file grew without bound. New behaviour: a dict {cid: {last_edge, alerted_at,
resolved}} so we can (a) re-alert when edge grows materially and (b) prune
resolved markets.

Run: python -m pytest tests/test_realert_prune.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scan_events as se


class TestMigrateSeen:
    def test_legacy_list_migrates_to_dict(self):
        legacy = ["0xAAA", "0xBBB"]
        d = se._normalize_seen(legacy)
        assert isinstance(d, dict)
        assert set(d.keys()) == {"0xAAA", "0xBBB"}
        # migrated entries have no recorded edge -> any new edge can re-alert
        assert d["0xAAA"].get("last_edge") is None

    def test_dict_passes_through(self):
        d_in = {"0xAAA": {"last_edge": 0.2, "alerted_at": "t", "resolved": False}}
        d = se._normalize_seen(d_in)
        assert d["0xAAA"]["last_edge"] == 0.2


class TestShouldSkipPreAI:
    # Pre-AI gate: should we skip this market WITHOUT spending an AI call?
    def test_unseen_market_not_skipped(self):
        assert se._should_skip_pre_ai("0xNEW", {}) is False

    def test_resolved_market_skipped(self):
        seen = {"0xAAA": {"last_edge": 0.2, "resolved": True}}
        assert se._should_skip_pre_ai("0xAAA", seen) is True


class TestShouldReAlert:
    # Post-AI: given a fresh edge, do we alert again on an already-seen market?
    def test_new_market_alerts(self):
        assert se._should_alert("0xNEW", current_edge=0.20, seen={}) is True

    def test_seen_same_edge_suppressed(self):
        seen = {"0xAAA": {"last_edge": 0.20}}
        assert se._should_alert("0xAAA", current_edge=0.21, seen=seen) is False

    def test_seen_edge_grew_realerts(self):
        # edge grew 0.12 -> 0.25 (=+13pp >= 10pp threshold) -> re-alert
        seen = {"0xAAA": {"last_edge": 0.12}}
        assert se._should_alert("0xAAA", current_edge=0.25, seen=seen) is True

    def test_seen_edge_grew_below_threshold_suppressed(self):
        # +5pp < 10pp threshold -> still suppressed
        seen = {"0xAAA": {"last_edge": 0.12}}
        assert se._should_alert("0xAAA", current_edge=0.17, seen=seen) is False

    def test_migrated_entry_with_no_edge_alerts_once(self):
        # legacy entry (last_edge None) should alert once so we capture its edge
        seen = {"0xAAA": {"last_edge": None}}
        assert se._should_alert("0xAAA", current_edge=0.20, seen=seen) is True


class TestPruneResolved:
    def test_prune_removes_resolved(self):
        seen = {
            "0xAAA": {"last_edge": 0.2, "resolved": True},
            "0xBBB": {"last_edge": 0.2, "resolved": False},
        }
        pruned = se._prune_seen(seen, resolved_cids={"0xAAA"})
        assert "0xAAA" not in pruned
        assert "0xBBB" in pruned

    def test_prune_marks_then_drops(self):
        # a cid newly known to be resolved is dropped from state
        seen = {"0xAAA": {"last_edge": 0.2, "resolved": False}}
        pruned = se._prune_seen(seen, resolved_cids={"0xAAA"})
        assert "0xAAA" not in pruned
