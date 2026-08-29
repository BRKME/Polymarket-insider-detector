"""Мониторинг выхода для YES-позиций (зеркало NO-логики).

Пробел, найденный 08.08.2026: реальные позиции оператора — все YES, а
mark_to_market их пропускал (его правила NO-центричны и при применении к YES
дают обратный смысл — в июле это давало ложные «РЕЖЬ»). В итоге по живым
деньгам не было ни «фиксируй прибыль», ни «режь убыток»: Antonelli +27%
и «Новые люди» −44% остались без единого сигнала.

Для YES прибыль растёт, когда цена ИДЁТ ВВЕРХ (вход 57.8c → сейчас 73.7c)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mark_to_market import decide_exit_yes, position_pnl_yes


def test_take_partial_on_run_up():
    assert decide_exit_yes(entry=0.578, current=0.82) == "TAKE_PARTIAL"


def test_close_full_near_resolution_price():
    assert decide_exit_yes(entry=0.578, current=0.92) == "CLOSE_FULL"


def test_hold_when_flat():
    assert decide_exit_yes(entry=0.578, current=0.60) is None


def test_cut_on_deep_drawdown():
    # «Новые люди»: 40.3c -> 22.5c = -44%, тезис сломан
    assert decide_exit_yes(entry=0.403, current=0.225) == "CUT"


def test_small_dip_is_not_a_cut():
    assert decide_exit_yes(entry=0.64, current=0.62) is None


def test_pnl_yes_profit_direction():
    # YES: цена вверх = прибыль (в отличие от NO)
    p = position_pnl_yes(entry=0.578, current=0.737, stake=15.0)
    assert p["unrealised"] > 0
    assert p["ret_pct"] > 0


def test_pnl_yes_loss_direction():
    p = position_pnl_yes(entry=0.403, current=0.225, stake=5.0)
    assert p["unrealised"] < 0


def test_pnl_zero_entry_safe():
    p = position_pnl_yes(entry=0, current=0.5, stake=10)
    assert p["unrealised"] == 0
