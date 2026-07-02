"""Живой список доверенных спорт-китов: пересобирается еженедельно из лидерборда,
сохраняется в trusted_whales.json. Новые проходят фильтр → добавляются, выпавшие
из топа → уходят. Копи-монитор читает актуальный набор."""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trusted_whales import build_trusted, save_trusted, load_trusted, MIN_EFF


def _row(wallet, name, pnl, vol):
    return {"proxyWallet": wallet, "userName": name, "pnl": pnl, "vol": vol}


def test_build_keeps_consistent_and_efficient():
    week = [_row("0xA", "alpha", 50000, 100000),   # эфф 50% — ок
            _row("0xB", "beta", 5000, 100000)]      # эфф 5% — ниже порога
    month = [_row("0xA", "alpha", 80000, 160000),   # в обоих окнах
             _row("0xB", "beta", 8000, 160000)]
    trusted = build_trusted(week, month)
    wallets = {w["wallet"] for w in trusted}
    assert "0xA" in wallets            # консистентен + эффективен
    assert "0xB" not in wallets        # эффективность ниже порога


def test_build_drops_non_consistent():
    # кит только в недельном топе, не в месячном -> не консистентен
    week = [_row("0xC", "gamma", 90000, 100000)]
    month = [_row("0xA", "alpha", 80000, 160000)]
    trusted = build_trusted(week, month)
    assert "0xC" not in {w["wallet"] for w in trusted}


def test_save_load_roundtrip():
    data = [{"wallet": "0xA", "name": "alpha", "eff": 0.5, "pnl": 80000}]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "tw.json")
        save_trusted(data, path=p)
        loaded = load_trusted(path=p)
        assert loaded[0]["wallet"] == "0xA"


def test_list_refreshes_new_whales():
    # новый кит появился в топе -> попадает в список (живой список)
    week = [_row("0xNEW", "rising", 60000, 120000)]
    month = [_row("0xNEW", "rising", 100000, 200000)]
    trusted = build_trusted(week, month)
    assert "0xNEW" in {w["wallet"] for w in trusted}


# ── ужесточение 02.07: MIN_EFF 0.10 -> 0.25 (решение оператора после того, как
# кит с ROI 19%/мес попал в копи-алерты; отменяет прежнее «держим все ~20») ──

def test_min_eff_is_tightened():
    assert MIN_EFF >= 0.25


def test_mid_efficiency_whale_rejected():
    """palegrit-кейс: eff 19% консистентен, но копировать его нельзя."""
    week = [_row("0xPALE", "palegrit", 24000, 125000)]     # eff 19.2%
    month = [_row("0xPALE", "palegrit", 240864, 1254500)]  # eff 19.2%
    trusted = build_trusted(week, month)
    assert "0xPALE" not in {w["wallet"] for w in trusted}


def test_high_efficiency_whale_kept():
    week = [_row("0xTOP", "muchobliged", 500000, 1162790)]   # eff 43%
    month = [_row("0xTOP", "muchobliged", 3141057, 7304783)]
    trusted = build_trusted(week, month)
    assert "0xTOP" in {w["wallet"] for w in trusted}


def test_scout_threshold_single_source_of_truth():
    """Порог в скауте не должен разъезжаться с порогом живого списка."""
    import leaderboard_scout as ls
    import trusted_whales as tw
    assert ls.MIN_PNL_EFFICIENCY == tw.MIN_EFF
