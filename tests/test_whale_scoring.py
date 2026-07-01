"""Скоринг спортивного кита для копи-трейда. Четыре ворота (все обязательны):
спортивный WR≥65%, N≥15 спортивных резолвов, окно 90д, свежесть входа ≤3¢.
Решение эксперта: мало, но надёжных. Защита от survivorship bias через N."""
import os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whale_scoring import is_trusted_whale, sport_win_rate, WhaleStats


def _stats(wr, n, days_since_last=1):
    return WhaleStats(sport_wr=wr, sport_n=n,
                      last_trade_ts=datetime.now(timezone.utc) - timedelta(days=days_since_last))


def test_trusted_when_all_gates_pass():
    assert is_trusted_whale(_stats(0.70, 20)) is True


def test_rejected_low_wr():
    assert is_trusted_whale(_stats(0.60, 20)) is False   # WR<65%


def test_rejected_small_sample():
    # даже 100% WR на малой выборке — не доверяем (survivorship bias)
    assert is_trusted_whale(_stats(1.0, 8)) is False      # N<15


def test_rejected_stale():
    # трек давно не обновлялся -> кит мог потерять инсайд
    assert is_trusted_whale(_stats(0.70, 20, days_since_last=120)) is False


def test_sport_wr_ignores_nonsport():
    # WR считается ТОЛЬКО по спортивным резолвам
    trades = [
        {"category": "sports", "won": True},
        {"category": "sports", "won": True},
        {"category": "sports", "won": False},
        {"category": "crypto", "won": False},   # не спорт — игнор
        {"category": "politics", "won": False}, # не спорт — игнор
    ]
    wr, n = sport_win_rate(trades)
    assert n == 3                     # только спортивные
    assert abs(wr - 2/3) < 0.01       # 2 из 3, крипто/политика не считаются


def test_entry_freshness():
    from whale_scoring import entry_still_fresh
    assert entry_still_fresh(0.60, 0.62) is True     # 2¢ — свежо
    assert entry_still_fresh(0.60, 0.63) is True     # ровно 3¢ — граница
    assert entry_still_fresh(0.60, 0.66) is False    # 6¢ — убежала
    assert entry_still_fresh(None, 0.60) is False
