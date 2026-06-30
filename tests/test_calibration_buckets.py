"""Калибровка Grok по корзинам: когда Grok говорит 60-80% YES, как часто YES
реально случается? Проверка гипотезы оператора: Grok недооценивает фаворитов,
поэтому механический NO против них убыточен."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v5_weekly_status import calibration_buckets


def test_underconfident_grok_detected():
    # Grok говорил 0.6-0.8, но YES случался почти всегда (0.9) -> недооценка
    resolved = [(0.85, 0.70, 1.0)] * 9 + [(0.85, 0.70, 0.0)] * 1
    lines = calibration_buckets(resolved)
    txt = "\n".join(lines)
    assert "0.6-0.8" in txt
    assert "90%" in txt        # реальный YES 90% против оценки Grok 70%


def test_empty():
    assert calibration_buckets([]) == []


def test_bucket_counts():
    resolved = [(0.5, 0.55, 1.0), (0.5, 0.55, 0.0),   # корзина 0.4-0.6
                (0.9, 0.90, 1.0)]                       # корзина 0.8-1.0
    lines = calibration_buckets(resolved)
    txt = "\n".join(lines)
    assert "n=2" in txt or "n=1" in txt
