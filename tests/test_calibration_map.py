"""Посткалибровка: пересчёт сырой оценки Grok по фактической таблице корзин.
Таблица копится на резолвах и уточняется. Где данных мало (малый n) — поправка
слабее (тянемся к сырой оценке), чтобы не довериться шуму."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibration_map import calibrate, build_calibration_table


def test_corrects_underestimate():
    # таблица: когда Grok говорил 0.2-0.4, реально YES 0.77 (на хорошем n)
    table = {"0.2-0.4": {"actual": 0.77, "n": 30}}
    out = calibrate(0.30, table)
    assert out > 0.30                 # подняли вверх к реальности
    assert 0.5 < out <= 0.77


def test_low_n_shrinks_toward_raw():
    # тот же сдвиг, но n=3 -> доверяем слабо, ближе к сырой 0.30
    weak = calibrate(0.30, {"0.2-0.4": {"actual": 0.77, "n": 3}})
    strong = calibrate(0.30, {"0.2-0.4": {"actual": 0.77, "n": 30}})
    assert abs(weak - 0.30) < abs(strong - 0.30)


def test_no_table_returns_raw():
    assert calibrate(0.30, {}) == 0.30
    assert calibrate(0.30, None) == 0.30


def test_build_table_from_resolved():
    # (market, ai, actual) — строим таблицу корзин
    resolved = [(0.8, 0.30, 1.0), (0.8, 0.35, 1.0), (0.8, 0.32, 0.0)]
    table = build_calibration_table(resolved)
    assert "0.2-0.4" in table
    assert table["0.2-0.4"]["n"] == 3
    assert abs(table["0.2-0.4"]["actual"] - 2/3) < 0.01


def test_calibrated_in_range():
    table = {"0.0-0.2": {"actual": 1.0, "n": 10}}
    out = calibrate(0.1, table)
    assert 0.0 <= out <= 1.0


def test_save_table_noop_under_pytest(tmp_path, monkeypatch):
    """save_table в pytest НЕ пишет на диск: тест v5_weekly_status однажды
    перезаписал БОЕВУЮ таблицу мусорным артефактом (та же дыра, что и
    load_table до фикса 91959cf, только на записи)."""
    import calibration_map as cm
    fake = tmp_path / "calibration_table.json"
    monkeypatch.setattr(cm, "CALIB_TABLE", fake)
    cm.save_table({"0.0-0.2": {"actual": 0.5, "n": 99}})
    assert not fake.exists(), "save_table записал файл во время pytest"
