"""
Tests for ai_cache.py — cache Grok estimates per condition_id to avoid paying
for the same estimate every 6h scan. Event markets move slowly, so a recent
estimate is reusable UNLESS the price has moved materially or it's gone stale.

Run: python -m pytest tests/test_ai_cache.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_cache


class TestCacheValidity:
    def test_fresh_unmoved_is_hit(self):
        entry = {"prob": 0.3, "conf": "high", "why": "x",
                 "yes_price": 0.80, "cached_at_epoch": 1000}
        # now +1h, price unchanged -> reuse
        assert ai_cache.is_valid(entry, now_epoch=1000 + 3600,
                                 current_yes=0.80) is True

    def test_stale_by_time_is_miss(self):
        entry = {"prob": 0.3, "conf": "high", "why": "x",
                 "yes_price": 0.80, "cached_at_epoch": 1000}
        # now + 8 days (> MAX_AGE) -> expired
        too_old = 1000 + ai_cache.MAX_AGE_SECONDS + 1
        assert ai_cache.is_valid(entry, now_epoch=too_old,
                                 current_yes=0.80) is False

    def test_price_moved_over_threshold_is_miss(self):
        entry = {"prob": 0.3, "conf": "high", "why": "x",
                 "yes_price": 0.80, "cached_at_epoch": 1000}
        # price moved 0.80 -> 0.86 (=6pp > 5pp) -> re-estimate
        assert ai_cache.is_valid(entry, now_epoch=1000 + 3600,
                                 current_yes=0.86) is False

    def test_price_moved_under_threshold_is_hit(self):
        entry = {"prob": 0.3, "conf": "high", "why": "x",
                 "yes_price": 0.80, "cached_at_epoch": 1000}
        # 4pp move < 5pp -> still reusable
        assert ai_cache.is_valid(entry, now_epoch=1000 + 3600,
                                 current_yes=0.84) is True

    def test_missing_fields_is_miss(self):
        assert ai_cache.is_valid({}, now_epoch=1000, current_yes=0.8) is False


class TestCachedEstimator:
    def test_hit_skips_underlying_call(self):
        calls = {"n": 0}

        def underlying(q, description=None, end_date=None):
            calls["n"] += 1
            return {"prob": 0.3, "conf": "high", "why": "x"}

        store = {}
        est = ai_cache.make_cached_estimator(
            underlying, store,
            cid_for=lambda q: "0xAAA",
            yes_for=lambda q: 0.80,
            now_epoch=lambda: 1000,
        )
        # first call: miss -> underlying called, result stored
        r1 = est("Q")
        assert calls["n"] == 1
        assert r1["prob"] == 0.3
        assert "0xAAA" in store

        # second call, same price/time: hit -> underlying NOT called again
        r2 = est("Q")
        assert calls["n"] == 1
        assert r2["prob"] == 0.3

    def test_price_move_triggers_refresh(self):
        calls = {"n": 0}
        prices = {"v": 0.80}

        def underlying(q, description=None, end_date=None):
            calls["n"] += 1
            return {"prob": 0.3, "conf": "high", "why": "x"}

        store = {}
        est = ai_cache.make_cached_estimator(
            underlying, store,
            cid_for=lambda q: "0xAAA",
            yes_for=lambda q: prices["v"],
            now_epoch=lambda: 1000,
        )
        est("Q")
        assert calls["n"] == 1
        prices["v"] = 0.90          # +10pp -> invalidate
        est("Q")
        assert calls["n"] == 2

    def test_none_result_not_cached(self):
        calls = {"n": 0}

        def underlying(q, description=None, end_date=None):
            calls["n"] += 1
            return None

        store = {}
        est = ai_cache.make_cached_estimator(
            underlying, store,
            cid_for=lambda q: "0xAAA",
            yes_for=lambda q: 0.80,
            now_epoch=lambda: 1000,
        )
        assert est("Q") is None
        assert "0xAAA" not in store     # don't cache failures
