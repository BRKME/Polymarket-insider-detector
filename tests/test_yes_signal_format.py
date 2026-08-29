"""Полевой баг 29.08.2026: mark_to_market падал 3 прогона подряд с
KeyError: 'ret_pct' на YES-сигнале.

position_pnl_yes возвращала {pnl, pct}, а _format_signal (написанный под NO)
ждёт {shares, value, unrealised, ret_pct}. Локально не проявлялось: YES-позиции
были, но ни одна не давала сигнала, пока US-Iran не выросла до +43%.

Обе версии P&L обязаны отдавать ОДИН контракт — иначе форматтер ломается на
той стороне, которую не проверяли."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mark_to_market import position_pnl, position_pnl_yes, _format_signal


def test_yes_pnl_has_same_keys_as_no():
    no = position_pnl(0.30, 0.85, 42.0)
    yes = position_pnl_yes(0.543, 0.78, 5.5)
    assert set(no.keys()) == set(yes.keys())


def test_yes_signal_formats_without_keyerror():
    pnl = position_pnl_yes(0.543, 0.78, 5.5)
    sig = {"question": "US-Iran", "condition_id": "0xA", "side": "YES",
           "entry_no": 0.543, "current_no": 0.78, "stake": 5.5,
           "action": "TAKE_PARTIAL", "current_edge": None, **pnl}
    out = _format_signal(sig)          # раньше: KeyError 'ret_pct'
    assert "US-Iran" in out


def test_yes_pnl_direction_preserved():
    up = position_pnl_yes(0.50, 0.75, 10.0)
    down = position_pnl_yes(0.50, 0.25, 10.0)
    assert up["unrealised"] > 0 and down["unrealised"] < 0


def test_yes_zero_entry_safe():
    p = position_pnl_yes(0, 0.5, 10)
    assert p["unrealised"] == 0 and p["ret_pct"] == 0
