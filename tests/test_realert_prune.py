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

    def test_migrated_entry_with_no_edge_does_not_alert(self):
        # legacy entry (last_edge None) was ALREADY alerted under the old set
        # format — re-alerting it spams duplicates of known positions. The
        # current edge must be recorded silently instead (see run()).
        seen = {"0xAAA": {"last_edge": None}}
        assert se._should_alert("0xAAA", current_edge=0.20, seen=seen) is False


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


class TestAntiRatchet:
    def test_suppression_must_not_update_last_edge(self):
        # If suppressed runs pulled last_edge up to the current edge, a slow
        # 5pp-per-run creep would never accumulate to the 10pp re-alert
        # threshold. last_edge must stay at the value of the last ALERT.
        seen = {"0xAAA": {"last_edge": 0.12}}
        # creep: 0.17 (suppressed), then 0.23 — vs ORIGINAL 0.12 that's +11pp
        assert se._should_alert("0xAAA", 0.17, seen) is False
        # ... seen must still hold 0.12, so 0.23 re-alerts:
        assert se._should_alert("0xAAA", 0.23, seen) is True


class TestReAlertJournalStatus:
    def test_realert_rows_marked_not_open(self):
        # a true edge-growth re-alert is the SAME position — its journal row
        # must not double-count in exposure / fills / mark-to-market
        import event_scanner as es
        c = es.Candidate(
            question="Q", condition_id="0xAAA", market_yes_price=0.7,
            no_price=0.3, ai_yes_estimate=0.4, edge=0.3, liquidity=50000,
            end_date="2026-12-31", reasoning="r")
        row = se._journal_row(c, re_alert=True)
        assert row["status"] == "re_alert"
        row2 = se._journal_row(c, re_alert=False)
        assert row2["status"] == "open"


class TestCrossRunThesisMemory:
    """SpaceX-кейс 10.06: «above \$2.2T» заалертили вчера, «above \$2T» — тот же
    тезис с другим cid — пришёл сегодня отдельным прогоном и продублировал по
    смыслу. Память тезисов в seen закрывает дыру: новый cid известного тезиса
    подавляется, пока edge не вырос на REALERT_EDGE_GROWTH."""

    def _seen_with_thesis(self, edge=0.44):
        return {"0xOLD": {"last_edge": edge, "alerted_at": "t",
                          "resolved": False,
                          "thesis_key": "spacex ipo closing market cap above"}}

    def test_same_thesis_new_cid_suppressed(self):
        seen = self._seen_with_thesis(edge=0.44)
        assert se._should_alert_thesis(
            "0xNEW", "spacex ipo closing market cap above",
            current_edge=0.44, seen=seen) is False

    def test_same_thesis_edge_grew_alerts(self):
        seen = self._seen_with_thesis(edge=0.30)
        assert se._should_alert_thesis(
            "0xNEW", "spacex ipo closing market cap above",
            current_edge=0.41, seen=seen) is True

    def test_unrelated_thesis_alerts(self):
        seen = self._seen_with_thesis()
        assert se._should_alert_thesis(
            "0xNEW", "us iran ceasefire extension",
            current_edge=0.30, seen=seen) is True

    def test_own_cid_not_compared_to_itself(self):
        seen = self._seen_with_thesis(edge=0.44)
        assert se._should_alert_thesis(
            "0xOLD", "spacex ipo closing market cap above",
            current_edge=0.44, seen=seen) is True
