"""Полевой баг 08.08.2026: бот слал 'EDGE ИСЧЕРПАН, фиксируй' и P&L +$59.92 по
позициям, которых у оператора НЕТ.

Причина: mark_to_market считал открытой любую строку журнала со статусом
'open', а туда пишутся ВСЕ алерты — то есть кандидаты, а не входы. Реальный
вход подтверждает fill_matcher, проставляя stake_actual. category_exposure это
уже учитывал, mark_to_market — нет: 44 из 50 'открытых' были фантомами."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mark_to_market import scan_open_positions


def _fetch(cid):
    # NO вырос с 30c до 90c — прибыль, edge исчерпан → сигнал на фиксацию
    return {"outcomes": ["Yes", "No"], "outcomePrices": ["0.10", "0.90"]}


def _row(cid, stake_actual=None, status="open"):
    return {"condition_id": cid, "status": status,
            "question": f"Q {cid}", "no_price": 0.30,
            "ai_yes_estimate": 0.20, "side": "NO",
            **({"stake_actual": stake_actual} if stake_actual is not None else {})}


def test_unfilled_candidate_is_not_monitored():
    # алерт без подтверждённого входа — не позиция, сигналов быть не должно
    out = scan_open_positions([_row("0xPHANTOM")], fetch_fn=_fetch)
    assert out == []


def test_filled_position_is_monitored():
    out = scan_open_positions([_row("0xREAL", stake_actual=26.54)], fetch_fn=_fetch)
    assert len(out) == 1


def test_mixed_only_filled_survive():
    rows = [_row("0xPHANTOM"), _row("0xREAL", stake_actual=42.0),
            _row("0xPHANTOM2")]
    out = scan_open_positions(rows, fetch_fn=_fetch)
    assert len(out) == 1
    assert out[0]["question"] == "Q 0xREAL"


def test_zero_stake_is_not_a_position():
    out = scan_open_positions([_row("0xZERO", stake_actual=0)], fetch_fn=_fetch)
    assert out == []
