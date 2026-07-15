# -*- coding: utf-8 -*-
"""Баги 15.07 из полевого использования.

1. Дубли exit-сигналов: run() слал один и тот же сигнал каждый 2ч-крон
   (18:27 и 20:19 — идентичные «РЕЖЬ»), дедупа не было.
2. Невидимый реализованный P&L: проигранная позиция (currentValue=0,
   redeemable=False) молча выпадала из filter_open_positions и не попадала
   ни в какой учёт — оператор проиграл $45, статус показывал −$1.
3. Лейбл CUT «edge развернулся» вешался и на прибыльную конвергенцию
   (NO 42→68¢, +61%): рынок сошёлся к AI-оценке, это фиксация, не паника.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import daily_status as ds
import mark_to_market as mtm
from exit_dedup import should_notify

NOW = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)


# ── 1. дедуп exit-сигналов ──────────────────────────────────────────────────

def test_first_signal_notifies():
    seen = {}
    assert should_notify(seen, "0xabc", "CUT", NOW) is True
    assert seen["0xabc"]["action"] == "CUT"


def test_same_action_within_day_is_silenced():
    seen = {"0xabc": {"action": "CUT",
                      "ts": (NOW - timedelta(hours=2)).isoformat()}}
    assert should_notify(seen, "0xabc", "CUT", NOW) is False


def test_same_action_after_24h_renotifies():
    seen = {"0xabc": {"action": "CUT",
                      "ts": (NOW - timedelta(hours=25)).isoformat()}}
    assert should_notify(seen, "0xabc", "CUT", NOW) is True


def test_action_escalation_notifies_immediately():
    seen = {"0xabc": {"action": "TAKE_PARTIAL",
                      "ts": (NOW - timedelta(minutes=10)).isoformat()}}
    assert should_notify(seen, "0xabc", "CLOSE_FULL", NOW) is True


# ── 2. реализованный P&L в статусе ──────────────────────────────────────────

def _open_pos():
    return {"conditionId": "0xopen", "title": "Open market", "size": 10,
            "currentValue": 20.0, "initialValue": 15.0, "cashPnl": 5.0,
            "redeemable": False, "curPrice": 0.5, "avgPrice": 0.4,
            "endDate": (NOW + timedelta(days=30)).isoformat()}


def _lost_pos(days_ago=1, stake=15.0, title="France leading at halftime?"):
    return {"conditionId": f"0xlost{days_ago}{stake}", "title": title,
            "size": 30, "currentValue": 0.0, "initialValue": stake,
            "cashPnl": -stake, "redeemable": False, "curPrice": 0.0,
            "avgPrice": 0.5,
            "endDate": (NOW - timedelta(days=days_ago)).isoformat()}


def _won_pos(days_ago=2, pnl=8.0):
    return {"conditionId": "0xwon", "title": "Won market", "size": 20,
            "currentValue": 20.0, "initialValue": 12.0, "cashPnl": pnl,
            "redeemable": True, "curPrice": 1.0, "avgPrice": 0.6,
            "endDate": (NOW - timedelta(days=days_ago)).isoformat()}


def test_resolved_positions_split_from_open():
    pos = [_open_pos(), _lost_pos(), _won_pos()]
    resolved = ds.resolved_positions(pos, now=NOW)
    assert {p["conditionId"] for p in resolved} == {"0xlost115.0", "0xwon"}
    # существующий фильтр открытых не сломан
    assert [p["conditionId"] for p in ds.filter_open_positions(pos)] == ["0xopen"]


def test_lost_position_without_end_date_not_marked_resolved():
    """currentValue=0 без прошедшего endDate может быть мусором API — не резолв."""
    p = _lost_pos()
    p["endDate"] = None
    assert ds.resolved_positions([p], now=NOW) == []


def test_realized_block_shows_recent_loss():
    pos = [_open_pos(),
           _lost_pos(days_ago=1, stake=15.0),
           _lost_pos(days_ago=1, stake=20.0, title="France to win?"),
           _lost_pos(days_ago=1, stake=10.0, title="France both halves?"),
           _lost_pos(days_ago=30, stake=99.0, title="Old loss")]
    block = ds.realized_block(ds.resolved_positions(pos, now=NOW),
                              now=NOW, window_days=7)
    assert block is not None
    assert "$-45" in block
    assert "Old loss" not in block           # вне окна — не в списке
    assert "France" in block


def test_realized_block_none_when_nothing_recent():
    pos = [_open_pos(), _lost_pos(days_ago=30)]
    assert ds.realized_block(ds.resolved_positions(pos, now=NOW),
                             now=NOW, window_days=7) is None


def test_status_header_includes_realized():
    pos = [_open_pos(), _lost_pos(days_ago=1, stake=45.0)]
    msg = ds.build_status_from_wallet(pos, journal=[], cash_value=None, now=NOW)
    assert "Реализовано за 7д" in msg
    assert "45" in msg


# ── 3. лейбл конвергенции вместо «РЕЖЬ» на прибыльной позиции ───────────────

def test_cut_label_on_profitable_position_is_convergence():
    s = {"question": "Will Bitcoin dip to $50,000 by December 31, 2026?",
         "condition_id": "0xbtc", "entry_no": 0.42, "current_no": 0.68,
         "stake": 27.0, "action": "CUT", "current_edge": -0.06,
         "shares": 64.29, "value": 43.72, "unrealised": 16.25, "ret_pct": 61.0}
    txt = mtm._format_signal(s)
    assert "РЕЖЬ" not in txt
    assert "EDGE ИСЧЕРПАН" in txt


def test_cut_label_on_losing_position_stays_cut():
    s = {"question": "Some market", "condition_id": "0x1", "entry_no": 0.42,
         "current_no": 0.30, "stake": 27.0, "action": "CUT",
         "current_edge": -0.06, "shares": 64.29, "value": 19.29,
         "unrealised": -7.71, "ret_pct": -28.6}
    txt = mtm._format_signal(s)
    assert "РЕЖЬ" in txt
