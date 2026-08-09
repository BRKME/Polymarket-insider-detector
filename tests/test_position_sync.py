"""Синхронизация журнала с реальным портфелем — обнаружение ПРОДАЖ.

Дыра, найденная 09.08.2026: журнал помечает позицию закрытой только когда рынок
РЕЗОЛВИТСЯ. Когда оператор продаёт сам, система не знает — строка висит
'open', экспозиция завышается, mark_to_market шлёт сигналы по проданному.
Вчера шесть таких пришлось закрывать вручную; сегодня журнал числил $109.61
вложенных при портфеле $84.89.

Источник истины — /positions кошелька. Нет позиции там → продана."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from position_sync import detect_sold, apply_sold


def _row(cid, q="Q", stake=10.0, status="open"):
    return {"condition_id": cid, "question": q, "stake_actual": stake,
            "status": status, "side": "YES"}


def _pos(cid, size=10.0, value=9.0):
    return {"conditionId": cid, "size": size, "currentValue": value,
            "redeemable": False}


def test_missing_from_wallet_is_sold():
    rows = [_row("0xA"), _row("0xB")]
    sold = detect_sold(rows, [_pos("0xA")])      # 0xB нет в кошельке
    assert [r["condition_id"] for r in sold] == ["0xB"]


def test_present_position_not_flagged():
    assert detect_sold([_row("0xA")], [_pos("0xA")]) == []


def test_unfilled_rows_ignored():
    # строка без подтверждённого входа — это кандидат, не позиция
    row = {"condition_id": "0xC", "status": "open", "question": "Q"}
    assert detect_sold([row], []) == []


def test_already_closed_ignored():
    assert detect_sold([_row("0xA", status="closed")], []) == []


def test_empty_wallet_response_is_not_mass_close():
    # ЗАЩИТА: пустой ответ API не должен закрыть весь журнал разом
    rows = [_row("0xA"), _row("0xB"), _row("0xC")]
    assert detect_sold(rows, []) == []       # пустой портфель = скорее сбой


def test_apply_marks_closed_with_reason():
    rows = [_row("0xA"), _row("0xB")]
    rows, n = apply_sold(rows, [_pos("0xA")])
    assert n == 1
    b = [r for r in rows if r["condition_id"] == "0xB"][0]
    assert b["status"] == "closed"
    assert b["closed_reason"] == "sold_detected"
