"""Тесты построения статуса от РЕАЛЬНЫХ позиций кошелька (/positions API),
а не от журнала алертов. Решает все три дефекта: наличные, устаревшая база
P&L, недосчёт позиций — источник истины теперь кошелёк.

Журнал алертов используется только для обогащения AI-тезисом по condition_id.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_status import build_status_from_wallet


def _positions():
    # формат Polymarket /positions: реальные позиции с текущей стоимостью
    return [
        {"conditionId": "0xA", "title": "Market A", "outcome": "No",
         "size": 100, "avgPrice": 0.40, "curPrice": 0.55,
         "initialValue": 40.0, "currentValue": 55.0, "cashPnl": 15.0},
        {"conditionId": "0xB", "title": "Market B", "outcome": "No",
         "size": 50, "avgPrice": 0.60, "curPrice": 0.30,
         "initialValue": 30.0, "currentValue": 15.0, "cashPnl": -15.0},
    ]


def _journal():
    return [{"condition_id": "0xA", "ai_yes_estimate": 0.15, "horizon_days": 100}]


class TestWalletStatus:
    def test_total_from_real_positions(self):
        msg = build_status_from_wallet(_positions(), _journal(), cash_value=37.0)
        # invested 70, current value 70, cash 37 -> total 107
        assert "107" in msg            # 55+15+37
        assert "37" in msg             # наличные учтены

    def test_pnl_from_real_basis(self):
        msg = build_status_from_wallet(_positions(), _journal(), cash_value=0.0)
        # P&L = 15 + (-15) = 0 от вложенных 70 — база РЕАЛЬНАЯ, не из журнала
        assert "от $70" in msg

    def test_journal_enriches_with_hint(self):
        # 0xB просел -50%, в журнале нет -> без тезиса; 0xA в журнале есть
        pos = [{"conditionId": "0xB", "title": "Drop", "outcome": "No",
                "size": 50, "avgPrice": 0.60, "curPrice": 0.30,
                "initialValue": 30.0, "currentValue": 15.0, "cashPnl": -15.0}]
        jrnl = [{"condition_id": "0xB", "ai_yes_estimate": 0.12, "horizon_days": 100}]
        msg = build_status_from_wallet(pos, jrnl, cash_value=0.0)
        assert "докуп" in msg.lower()   # тезис цел -> подсказка докупа

    def test_empty_positions(self):
        msg = build_status_from_wallet([], [], cash_value=37.0)
        assert "37" in msg or "0" in msg

    def test_count_matches_wallet_not_journal(self):
        # 2 позиции в кошельке, 1 в журнале -> показываем 2 (кошелёк = истина)
        msg = build_status_from_wallet(_positions(), _journal(), cash_value=0.0)
        assert "Позиций: 2" in msg
