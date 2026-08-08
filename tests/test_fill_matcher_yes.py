"""Полевой баг 08.08.2026: реальные YES-позиции оператора не сопоставлялись.

fill_matcher писался под NO-стратегию и жёстко отбрасывал всё, кроме
outcome='no'. Оператор перешёл на YES средней зоны, купил 8 позиций — ни одна
не получила stake_actual, значит считалась «фантомом» и не мониторилась вовсе
(а mark_to_market вдобавок пропускает YES-строки). Позиции были слепой зоной.

Сопоставлять нужно по СТОРОНЕ строки журнала, а не всегда по NO."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fill_matcher import match_position


def _trade(outcome, price=0.578, size=26.0, cid="0xA"):
    return {"conditionId": cid, "side": "BUY", "outcome": outcome,
            "price": price, "size": size, "usdcSize": round(price * size, 2),
            "transactionHash": "0xtx"}


def test_yes_trade_matched_when_side_is_yes():
    got = match_position("0xA", [_trade("Yes")], side="YES")
    assert got is not None
    assert abs(got["entry_price_actual"] - 0.578) < 1e-6
    assert got["stake_actual"] > 0


def test_no_trade_still_matched_by_default():
    got = match_position("0xA", [_trade("No", price=0.30)])
    assert got is not None
    assert abs(got["entry_price_actual"] - 0.30) < 1e-6


def test_yes_side_does_not_match_no_trades():
    assert match_position("0xA", [_trade("No")], side="YES") is None


def test_no_side_does_not_match_yes_trades():
    assert match_position("0xA", [_trade("Yes")], side="NO") is None


def test_case_insensitive_outcome():
    assert match_position("0xA", [_trade("YES")], side="YES") is not None


def test_apply_fills_passes_side_from_row():
    """Сквозной: YES-строка журнала должна получить stake_actual из YES-сделки."""
    from fill_matcher import apply_fills
    rows = [{"condition_id": "0xA", "status": "open", "side": "YES",
             "question": "Kimi Antonelli"}]
    rows, n = apply_fills(rows, lambda cid: [_trade("Yes")])
    assert n == 1
    assert rows[0]["stake_actual"] > 0
    assert abs(rows[0]["entry_price_actual"] - 0.578) < 1e-6
