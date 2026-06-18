"""Уже открытую длинную позицию (>30д до резолва) не гнать через дорогой
поиск Grok: за сутки edge на полугодовом тезисе не меняется, решение докупить
даёт движение цены (дневной статус, без AI). Экономит поиск-вызовы.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan_events import _should_skip_pre_ai, HELD_LONG_SKIP_DAYS


def test_held_long_position_skipped():
    seen = {"0xHeld": {"resolved": False, "last_edge": 0.3}}
    # открыта (в журнале) + далеко до резолва -> пропускаем дорогой поиск
    assert _should_skip_pre_ai("0xHeld", seen, held_cids={"0xHeld"},
                               hours_to_resolve=200 * 24) is True


def test_held_but_near_resolution_not_skipped():
    seen = {"0xHeld": {"resolved": False, "last_edge": 0.3}}
    # открыта, но резолв близко (5д) -> переоцениваем (важный момент)
    assert _should_skip_pre_ai("0xHeld", seen, held_cids={"0xHeld"},
                               hours_to_resolve=5 * 24) is False


def test_not_held_long_not_skipped():
    seen = {}
    # новый кандидат, далёкий -> оцениваем (надо решить, входить ли)
    assert _should_skip_pre_ai("0xNew", seen, held_cids=set(),
                               hours_to_resolve=200 * 24) is False


def test_resolved_always_skipped():
    seen = {"0xDead": {"resolved": True}}
    assert _should_skip_pre_ai("0xDead", seen, held_cids=set(),
                               hours_to_resolve=100) is True


def test_backward_compatible_no_extra_args():
    # старый вызов без новых аргументов всё ещё работает (resolved-only)
    assert _should_skip_pre_ai("0xX", {"0xX": {"resolved": True}}) is True
    assert _should_skip_pre_ai("0xX", {"0xX": {"resolved": False}}) is False
