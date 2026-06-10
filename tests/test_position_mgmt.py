"""
Tests for mark_to_market.py and refresh_prices.py (manual-mode position
management) plus the size-derived liquidity floor in config.

Run: python -m pytest tests/test_position_mgmt.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mark_to_market as mtm
import refresh_prices as rp
import config


# ── exit decision logic ──────────────────────────────────────────────────────

class TestDecideExit:
    def test_hold_when_below_partial(self):
        assert mtm.decide_exit(0.55, current_edge=0.20) is None

    def test_partial_at_080(self):
        assert mtm.decide_exit(0.80, current_edge=0.10) == "TAKE_PARTIAL"

    def test_full_at_090(self):
        assert mtm.decide_exit(0.92, current_edge=0.05) == "CLOSE_FULL"

    def test_profit_tier_takes_priority_over_inverted_edge(self):
        # at a profitable price, banking the gain beats "cutting" — the small/
        # negative re-marked edge there is the market converging to our thesis.
        assert mtm.decide_exit(0.85, current_edge=-0.10) == "TAKE_PARTIAL"
        assert mtm.decide_exit(0.92, current_edge=-0.10) == "CLOSE_FULL"

    def test_cut_only_below_profit_tiers(self):
        # price moved against us (still cheap NO) AND edge inverted -> cut
        assert mtm.decide_exit(0.40, current_edge=-0.08) == "CUT"

    def test_none_edge_still_uses_price(self):
        assert mtm.decide_exit(0.90, current_edge=None) == "CLOSE_FULL"


# ── P&L math ─────────────────────────────────────────────────────────────────

class TestPositionPnl:
    def test_no_position_profit(self):
        # entered NO at 0.20, now 0.40, $50 stake -> 250 shares, value $100
        p = mtm.position_pnl(entry=0.20, current=0.40, stake=50.0)
        assert p["shares"] == 250.0
        assert p["value"] == 100.0
        assert p["unrealised"] == 50.0
        assert p["ret_pct"] == 100.0

    def test_no_position_loss(self):
        p = mtm.position_pnl(entry=0.50, current=0.40, stake=50.0)
        assert p["unrealised"] == -10.0

    def test_zero_entry_safe(self):
        p = mtm.position_pnl(entry=0.0, current=0.4, stake=50.0)
        assert p["unrealised"] == 0.0


# ── stake/entry resolution from journal rows ─────────────────────────────────

class TestStakeAndEntry:
    def test_actual_stake_preferred(self):
        assert mtm.position_stake({"stake_actual": 35.0}) == 35.0

    def test_fallback_to_range_midpoint(self):
        mid = (config.STAKE_MIN + config.STAKE_MAX) / 2.0
        assert mtm.position_stake({}) == mid

    def test_actual_entry_preferred_over_alert(self):
        row = {"entry_price_actual": 0.22, "no_price": 0.20}
        assert mtm.entry_no_price(row) == 0.22

    def test_fallback_to_alert_price(self):
        assert mtm.entry_no_price({"no_price": 0.20}) == 0.20


# ── scan_open_positions with injected fetch ──────────────────────────────────

def _fake_market(no_price):
    yes = round(1 - no_price, 4)
    return {"outcomes": '["Yes","No"]',
            "outcomePrices": f'["{yes}","{no_price}"]'}


class TestScanOpenPositions:
    def test_closed_positions_skipped(self):
        rows = [{"condition_id": "0x1", "no_price": 0.2,
                 "ai_yes_estimate": 0.6, "status": "closed"}]
        out = mtm.scan_open_positions(rows, fetch_fn=lambda c: _fake_market(0.95))
        assert out == []

    def test_open_position_matured_emits_signal(self):
        # entered NO 0.20 (=> YES 0.80), AI YES 0.15 => entry edge 0.65 (clean)
        rows = [{"condition_id": "0x1", "question": "Q", "no_price": 0.20,
                 "ai_yes_estimate": 0.15, "stake_actual": 50.0}]
        # current NO 0.92 => YES 0.08, edge still +0.93*? -> matured, CLOSE_FULL
        out = mtm.scan_open_positions(rows, fetch_fn=lambda c: _fake_market(0.92))
        assert len(out) == 1
        assert out[0]["action"] == "CLOSE_FULL"
        assert out[0]["unrealised"] > 0

    def test_open_position_holding_no_signal(self):
        # entered NO 0.20, AI YES 0.15; current NO 0.50 => YES 0.50, edge +0.35
        # (still well above stop) and price below partial tier -> hold
        rows = [{"condition_id": "0x1", "question": "Q", "no_price": 0.20,
                 "ai_yes_estimate": 0.15, "stake_actual": 50.0}]
        out = mtm.scan_open_positions(rows, fetch_fn=lambda c: _fake_market(0.50))
        assert out == []


# ── refresh_prices ───────────────────────────────────────────────────────────

class TestRefresh:
    def test_edge_still_tradeable(self):
        # AI says YES 0.40; current NO 0.20 => YES 0.80 => edge 0.40 >= EDGE_MIN
        rows = [{"condition_id": "0x1", "question": "Q",
                 "no_price": 0.20, "edge": 0.40, "ai_yes_estimate": 0.40}]
        out = rp.refresh(rows, fetch_fn=lambda c: _fake_market(0.20))
        assert out[0]["still_tradeable"] is True

    def test_edge_collapsed_flagged(self):
        # current NO 0.45 => YES 0.55 => edge 0.15... exactly EDGE_MIN; push below
        rows = [{"condition_id": "0x1", "question": "Q",
                 "no_price": 0.20, "edge": 0.40, "ai_yes_estimate": 0.40}]
        out = rp.refresh(rows, fetch_fn=lambda c: _fake_market(0.50))
        # YES now 0.50, edge 0.10 < EDGE_MIN
        assert out[0]["still_tradeable"] is False

    def test_closed_skipped(self):
        rows = [{"condition_id": "0x1", "status": "closed",
                 "no_price": 0.2, "ai_yes_estimate": 0.4}]
        out = rp.refresh(rows, fetch_fn=lambda c: _fake_market(0.2))
        assert out == []


# ── size-derived liquidity floor ─────────────────────────────────────────────

class TestLiquidityFloor:
    def test_floor_keeps_max_stake_small_slice(self):
        # at the floor, STAKE_MAX must be exactly MAX_BET_FRACTION_OF_BOOK of it
        floor = config.MIN_LIQUIDITY_EVENT
        frac = config.STAKE_MAX / floor
        assert abs(frac - config.MAX_BET_FRACTION_OF_BOOK) < 1e-9

    def test_floor_above_old_5k(self):
        # sanity: with $70 max at 1.5%, floor is ~$4,667 (documented)
        assert 4000 < config.MIN_LIQUIDITY_EVENT < 5000
