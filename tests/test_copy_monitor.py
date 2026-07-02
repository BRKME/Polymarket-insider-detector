"""Копи-монитор: свежие спортивные входы доверенных китов → копи-алерт.
Только BUY, только спорт, только свежий вход (цена ≤3¢ от китовой), только
новые (не дублировать уже виденное)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copy_monitor import copy_signal, is_fresh_sport_buy


def _act(side="BUY", price=0.60, title="England vs France", type_="TRADE"):
    return {"side": side, "price": price, "title": title, "type": type_,
            "conditionId": "0xabc", "size": 500}


def test_fresh_sport_buy_accepted():
    assert is_fresh_sport_buy(_act(), current_price=0.62) is True   # 2¢ — свежо


def test_sell_ignored():
    assert is_fresh_sport_buy(_act(side="SELL"), current_price=0.60) is False


def test_nonsport_ignored():
    a = _act(title="Will Fed cut rates?")
    assert is_fresh_sport_buy(a, current_price=0.60) is False


def test_stale_entry_ignored():
    # цена убежала на 6¢ от входа кита — копировать поздно
    assert is_fresh_sport_buy(_act(price=0.60), current_price=0.66) is False


def test_copy_signal_builds_alert():
    sig = copy_signal(whale_name="easymoney9", whale_eff=0.49,
                      act=_act(price=0.60), current_price=0.61)
    assert sig is not None
    assert "easymoney9" in sig
    assert "England" in sig


def test_copy_signal_none_when_stale():
    sig = copy_signal(whale_name="x", whale_eff=0.3,
                      act=_act(price=0.60), current_price=0.70)
    assert sig is None
