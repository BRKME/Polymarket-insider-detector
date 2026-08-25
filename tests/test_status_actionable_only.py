"""Секция «двигались» должна содержать только строки, требующие решения.

15.08.2026: из шести строк подсказка была у одной. Остальные повторяли числа
из шапки («в плюсе 7 / в минусе 4») и не говорили, что делать. Принцип обоих
проектов: сообщение либо требует действия, либо подтверждает, что система жива;
строка без подсказки не делает ни того, ни другого."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_status import build_status_from_wallet


def _pos(cid, title, invested, current):
    return {"conditionId": cid, "title": title, "initialValue": invested,
            "currentValue": current, "avgPrice": 0.54, "curPrice": 0.78,
            "size": 10, "redeemable": False}


def test_position_without_hint_is_not_detailed():
    # +29%: двигалась, но правило не сработало -> в деталях её быть не должно
    pos = [_pos("0xA", "Antonelli", 15.0, 19.35)]
    pos[0]["avgPrice"] = 0.578
    pos[0]["curPrice"] = 0.75
    out = build_status_from_wallet(pos, [], now=None)
    assert "Antonelli" not in out


def test_position_with_hint_is_detailed():
    # +43% -> порог фиксации сработал, строка нужна
    pos = [_pos("0xB", "US-Iran", 5.5, 7.86)]
    journal = [{"condition_id": "0xB", "side": "YES", "ai_yes_estimate": 0.8}]
    out = build_status_from_wallet(pos, journal, now=None)
    assert "US-Iran" in out
    assert "зафиксировать" in out


def test_header_still_shows_overall_picture():
    pos = [_pos("0xA", "Quiet", 15.0, 15.2)]
    out = build_status_from_wallet(pos, [], now=None)
    assert "Позиций: 1" in out


def test_footer_not_no_centric():
    pos = [_pos("0xB", "US-Iran", 5.5, 7.86)]
    journal = [{"condition_id": "0xB", "side": "YES", "ai_yes_estimate": 0.8}]
    out = build_status_from_wallet(pos, journal, now=None)
    assert "NO можно продать" not in out
