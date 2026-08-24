"""Полевой баг 15.08.2026: дневной статус показывал −29% при реальном +2%.

Два дефекта:
1. P&L брался из cashPnl — в Polymarket это РЕАЛИЗОВАННЫЙ денежный поток, а не
   нереализованная прибыль открытой позиции. Само сообщение себе противоречило:
   «P&L −$25 от $86» и рядом «Позиции: $91» (86 вложено + 91 стоит = +5, не −25).
2. Подсказки печатали «NO 54¢→25¢» для YES-позиций, инвертируя текущую цену и
   не инвертируя вход. Antonelli: реально +29.7%, бот показывал −55%.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_status import position_pnl_value, position_action_hint


def test_pnl_from_value_not_cashpnl():
    # cashPnl врёт (реализованный поток), считаем по стоимости
    p = {"initialValue": 15.0, "currentValue": 19.45, "cashPnl": -8.0}
    assert position_pnl_value(p) > 0


def test_pnl_matches_reality():
    # Antonelli: вложено $15, стоит $19.45 -> +$4.45
    p = {"initialValue": 15.0, "currentValue": 19.45}
    assert abs(position_pnl_value(p) - 4.45) < 0.01


def test_loss_still_negative():
    p = {"initialValue": 5.0, "currentValue": 2.72}
    assert position_pnl_value(p) < 0


def test_hint_labels_yes_side():
    h = position_action_hint(0.543, 0.736, ai_yes=0.8, horizon_days=None, side="YES")
    assert h is None or "NO" not in h


def test_hint_still_labels_no_side():
    h = position_action_hint(0.30, 0.85, ai_yes=0.1, horizon_days=None, side="NO")
    assert h is not None and "NO" in h
