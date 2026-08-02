"""Раздельный вердикт YES vs NO по РЕАЛЬНЫМ позициям (event_journal).
Калибровочный журнал не знает сторон — только сырые оценки Grok. Стороны живут
в event_journal, там же исходы. Нужно для решения: набирает ли YES свой edge."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from side_split import split_by_side, side_stats


def _row(side, market_yes, ai_yes, won=None):
    return {"side": side, "market_yes_price": market_yes,
            "ai_yes_estimate": ai_yes, "won": won}


def test_split_separates_sides():
    rows = [_row("YES", 0.6, 0.7), _row("NO", 0.8, 0.3), _row("YES", 0.55, 0.8)]
    yes, no = split_by_side(rows)
    assert len(yes) == 2 and len(no) == 1


def test_missing_side_counts_as_no():
    rows = [{"market_yes_price": 0.8, "ai_yes_estimate": 0.3}]
    yes, no = split_by_side(rows)
    assert len(no) == 1


def test_stats_wr_and_n():
    rows = [_row("YES", 0.6, 0.7, won=True), _row("YES", 0.6, 0.7, won=True),
            _row("YES", 0.6, 0.7, won=False)]
    st = side_stats(rows)
    assert st["n"] == 3
    assert abs(st["wr"] - 2/3) < 0.01


def test_stats_ignores_unresolved():
    rows = [_row("YES", 0.6, 0.7, won=True), _row("YES", 0.6, 0.7, won=None)]
    st = side_stats(rows)
    assert st["n"] == 1


def test_empty_safe():
    st = side_stats([])
    assert st["n"] == 0 and st["wr"] is None
