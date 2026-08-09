"""Полевой баг 03-05.08.2026: daily_status падал 3 дня подряд с
TypeError: can't compare offset-naive and offset-aware datetimes.

Polymarket отдаёт endDate в двух форматах — часть с 'Z' (aware), часть без
(naive). Парсинг обеих проходил, но sorted() сравнивал их между собой и падал.
Все даты должны приводиться к aware (UTC)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from daily_status import realized_block


def _recent(days_ago=1, aware=True):
    """Дата внутри окна отчёта, ОТНОСИТЕЛЬНО сейчас — иначе тест протухает
    (упал 09.08, т.к. был написан 08.08 с жёсткими датами 01-02.08)."""
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ" if aware else "%Y-%m-%dT%H:%M:%S")


def _pos(end, pnl, title):
    return {"endDate": end, "initialValue": 10, "cashPnl": pnl,
            "title": title, "size": 1, "currentValue": 0, "redeemable": True}


def test_mixed_naive_and_aware_dates_do_not_crash():
    resolved = [_pos(_recent(1, True), -10, "aware"),
                _pos(_recent(2, False), 5, "naive")]
    out = realized_block(resolved)      # раньше: TypeError
    assert out is not None
    assert "aware" in out or "naive" in out


def test_all_naive_still_works():
    resolved = [_pos(_recent(1, False), -10, "a"),
                _pos(_recent(2, False), 5, "b")]
    assert realized_block(resolved) is not None


def test_all_aware_still_works():
    resolved = [_pos(_recent(1, True), -10, "a"),
                _pos(_recent(2, True), 5, "b")]
    assert realized_block(resolved) is not None


def test_garbage_date_skipped_not_crash():
    resolved = [_pos("not-a-date", -10, "bad"),
                _pos(_recent(2, True), 5, "good")]
    out = realized_block(resolved)
    assert out is not None and "good" in out


def test_resolved_positions_handles_naive_dates():
    """Та же ловушка во втором месте: resolved_positions сравнивает end <= now."""
    from daily_status import resolved_positions
    positions = [_pos("2026-08-01T00:00:00", -10, "naive"),
                 _pos(_recent(1, True), -10, "aware")]
    out = resolved_positions(positions)   # раньше: TypeError на naive
    assert len(out) == 2
