"""
Tests for fill_matcher.py — auto-fill actual entry price & stake from the
Polymarket Data API by matching our journal positions to real on-chain trades.

Shapes are taken from the live /activity response for our address:
  trade = {proxyWallet, conditionId, side, outcome, outcomeIndex,
           size, price, usdcSize, timestamp, transactionHash, ...}

Run: python -m pytest tests/test_fill_matcher.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fill_matcher as fm


def _trade(cid, price, usdc, size, side="BUY", outcome="No", ts=1781028901,
           tx="0xtx"):
    return {
        "proxyWallet": "0xbd8338c6d4e1e25b28d1a95db926d2cef689632f",
        "conditionId": cid,
        "side": side,
        "outcome": outcome,
        "outcomeIndex": 1 if outcome == "No" else 0,
        "size": size,
        "price": price,
        "usdcSize": usdc,
        "timestamp": ts,
        "transactionHash": tx,
        "type": "TRADE",
    }


class TestMatchOne:
    def test_single_no_buy_matches(self):
        trades = [_trade("0xAAA", price=0.39, usdc=9.05, size=22.25)]
        fill = fm.match_position("0xAAA", trades)
        assert fill is not None
        assert fill["entry_price_actual"] == 0.39
        assert fill["stake_actual"] == 9.05
        assert fill["fill_source"] == "onchain"
        assert fill["fill_txs"] == 1

    def test_yes_side_ignored(self):
        # we only ever bet NO; a YES buy on the same market is not our position
        trades = [_trade("0xAAA", price=0.6, usdc=10, size=16, outcome="Yes")]
        assert fm.match_position("0xAAA", trades) is None

    def test_sell_ignored(self):
        trades = [_trade("0xAAA", price=0.39, usdc=9, size=22, side="SELL")]
        assert fm.match_position("0xAAA", trades) is None

    def test_other_market_ignored(self):
        trades = [_trade("0xBBB", price=0.39, usdc=9, size=22)]
        assert fm.match_position("0xAAA", trades) is None

    def test_no_trades_returns_none(self):
        assert fm.match_position("0xAAA", []) is None


class TestAggregatePartials:
    def test_multiple_buys_vwap_and_sum(self):
        # two partial NO entries on the same market -> size-weighted avg price
        # and summed stake. 100 @ .40 + 100 @ .50 -> vwap .45, stake 90
        trades = [
            _trade("0xAAA", price=0.40, usdc=40.0, size=100.0, tx="0x1"),
            _trade("0xAAA", price=0.50, usdc=50.0, size=100.0, tx="0x2"),
        ]
        fill = fm.match_position("0xAAA", trades)
        assert fill["fill_txs"] == 2
        assert abs(fill["entry_price_actual"] - 0.45) < 1e-6
        assert abs(fill["stake_actual"] - 90.0) < 1e-6
        assert abs(fill["shares_actual"] - 200.0) < 1e-6

    def test_vwap_weights_by_size_not_count(self):
        # 300 @ .20 + 100 @ .60 -> vwap = (300*.2+100*.6)/400 = .30
        trades = [
            _trade("0xAAA", price=0.20, usdc=60.0, size=300.0, tx="0x1"),
            _trade("0xAAA", price=0.60, usdc=60.0, size=100.0, tx="0x2"),
        ]
        fill = fm.match_position("0xAAA", trades)
        assert abs(fill["entry_price_actual"] - 0.30) < 1e-6


class TestApplyToJournal:
    def test_fills_open_unfilled_only(self):
        rows = [
            {"condition_id": "0xAAA", "status": "open",
             "entry_price_actual": None, "stake_actual": None},
            # already filled — must not be overwritten
            {"condition_id": "0xBBB", "status": "open",
             "entry_price_actual": 0.30, "stake_actual": 12.0,
             "fill_source": "onchain"},
            # closed — skip
            {"condition_id": "0xCCC", "status": "closed",
             "entry_price_actual": None, "stake_actual": None},
        ]

        def fake_fetch(cid):
            return [_trade(cid, price=0.39, usdc=9.05, size=22.25)]

        updated, n = fm.apply_fills(rows, fetch_trades_fn=fake_fetch)
        assert n == 1                              # only 0xAAA filled
        assert updated[0]["entry_price_actual"] == 0.39
        assert updated[0]["stake_actual"] == 9.05
        assert updated[0]["fill_source"] == "onchain"
        # untouched
        assert updated[1]["entry_price_actual"] == 0.30
        assert updated[2]["entry_price_actual"] is None

    def test_no_match_leaves_unconfirmed(self):
        rows = [{"condition_id": "0xAAA", "status": "open",
                 "entry_price_actual": None, "stake_actual": None}]
        # API returns trades for a different market -> no fill, stays None
        updated, n = fm.apply_fills(
            rows, fetch_trades_fn=lambda cid: [_trade("0xZZZ", 0.3, 9, 22)])
        assert n == 0
        assert updated[0]["entry_price_actual"] is None
        assert updated[0].get("fill_source") in (None, "unconfirmed")
