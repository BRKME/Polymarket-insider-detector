"""Промежуточный чекпойнт 02.09.2026: первая проверка узкой зоны 50-65%
на реальных ставках. Счётчик вердикта перезапущен 02.08 (смена границы)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v5_weekly_status import CHECKPOINTS


def test_september_checkpoint_registered():
    labels = [c[0] for c in CHECKPOINTS]
    assert "02.09" in labels


def test_checkpoint_has_meaningful_name():
    cp = [c for c in CHECKPOINTS if c[0] == "02.09"][0]
    assert "узк" in cp[2].lower() or "зона" in cp[2].lower()


def test_checkpoints_chronological():
    dates = [c[1] for c in CHECKPOINTS]
    assert dates == sorted(dates)
