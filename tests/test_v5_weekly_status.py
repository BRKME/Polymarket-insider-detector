"""Тесты v5_weekly_status — воскресный статус живой стратегии вместо
ежедневной эпитафии похороненной whale-copy (852 ставки, WR 44%, ROI −4%).

Статус отвечает на три вопроса оператора без сети: что открыто (и подтверждено
ончейном), как копится калибровка, сколько дней до чекпойнтов вердикта.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v5_weekly_status import build_status

NOW = datetime(2026, 6, 14, 8, 0, tzinfo=timezone.utc)   # воскресенье


def _journal():
    return [
        {"condition_id": "0x1", "status": "open", "fill_source": "onchain",
         "category": "geopolitics", "stake_actual": 40.0},
        {"condition_id": "0x2", "status": "open",
         "category": "crypto"},
        {"condition_id": "0x3", "status": "closed", "fill_source": "onchain",
         "category": "crypto"},
        {"condition_id": "0x4", "status": "re_alert",
         "category": "crypto"},
    ]


def _calib(n=36, short=10):
    rows = []
    for i in range(n):
        rows.append({"condition_id": f"0xc{i}",
                     "horizon_days": 20.0 if i < short else 400.0,
                     "would_bet": i % 3 == 0})
    return rows


class TestStatus:
    def test_positions_counted_correctly(self):
        msg = build_status(_journal(), _calib(), now=NOW)
        # open=2 (re_alert и closed не считаются), onchain из открытых=1
        assert "Открыто: 2" in msg
        assert "ончейн: 1" in msg

    def test_calibration_progress(self):
        msg = build_status(_journal(), _calib(n=36, short=10), now=NOW)
        assert "36" in msg                 # всего оценок
        assert "10" in msg                 # короткий горизонт (≤45д)

    def test_checkpoint_countdown(self):
        msg = build_status(_journal(), _calib(), now=NOW)
        # до ворот вердикта 22.07 от 14.06 — 38 дней
        assert "22.07" in msg and "37" in msg

    def test_v5_branding_no_legacy(self):
        msg = build_status(_journal(), _calib(), now=NOW)
        assert "v5" in msg
        for legacy in ("ALPHA", "TOP_TRADER", "AI_COPY", "852"):
            assert legacy not in msg

    def test_empty_journal_safe(self):
        msg = build_status([], [], now=NOW)
        assert "Открыто: 0" in msg
