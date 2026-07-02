"""Посткалибровка оценок Grok по фактической таблице корзин.

Вердикт (n=38): Grok систематически промахивается — в корзине 0.0-0.2 реально
YES 100%, в 0.2-0.4 реально 77%. Это измеренная функция ошибки. Мы её применяем
как поправку: сырую оценку Grok пересчитываем в откалиброванную по тому, что
РЕАЛЬНО случалось в этой корзине.

Критично: таблица копится на резолвах и уточняется. Где n мал (корзина из 3-5
точек) — доверять нельзя, поправка УСАЖИВАЕТСЯ к сырой оценке (shrinkage), чтобы
не выучить шум вместо смещения. По мере накопления резолвов поправка крепнет.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

CALIB_TABLE = Path("calibration_table.json")

# Корзины оценки Grok
_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]

# Сколько резолвов в корзине нужно, чтобы доверять ей ПОЛНОСТЬЮ. Меньше —
# поправка усаживается к сырой оценке пропорционально n/FULL_TRUST_N.
FULL_TRUST_N = 25


def _bucket_key(p: float) -> str:
    for lo, hi in _BUCKETS:
        if lo <= p < hi:
            return f"{lo:.1f}-{min(hi,1.0):.1f}"
    return "0.8-1.0"


def build_calibration_table(resolved: list) -> dict:
    """Из списка (market_yes, ai_yes, actual_yes) строит таблицу корзин:
    {bucket: {actual: средняя реальная частота YES, n: число точек}}."""
    by_bucket: dict[str, list] = {}
    for _, ai, actual in resolved:
        k = _bucket_key(float(ai))
        by_bucket.setdefault(k, []).append(float(actual))
    table = {}
    for k, ys in by_bucket.items():
        table[k] = {"actual": sum(ys) / len(ys), "n": len(ys)}
    return table


def calibrate(raw_prob: float, table: Optional[dict]) -> float:
    """Пересчитывает сырую оценку Grok в откалиброванную по таблице корзин.

    С усадкой по n: если в корзине мало резолвов, доверяем её слабо и тянемся
    к сырой оценке. weight = min(1, n / FULL_TRUST_N).
    calibrated = raw + weight * (bucket_actual - raw).
    """
    if not table:
        return raw_prob
    rec = table.get(_bucket_key(float(raw_prob)))
    if not rec or rec.get("n", 0) <= 0:
        return raw_prob
    actual = float(rec["actual"])
    n = int(rec["n"])
    weight = min(1.0, n / FULL_TRUST_N)
    calibrated = raw_prob + weight * (actual - raw_prob)
    return max(0.0, min(1.0, calibrated))


def load_table() -> dict:
    """Читает сохранённую таблицу калибровки (мягкий fail-safe).

    В CI (тестах) файл НЕ читаем — иначе внешний артефакт на диске делает тесты
    evaluate/scan недетерминированными (калибровка меняет edge и рушит моки,
    которые её не ожидают). Тесты самой калибровки передают таблицу явно."""
    import os
    if os.getenv("CI"):
        return {}
    try:
        if CALIB_TABLE.exists():
            return json.loads(CALIB_TABLE.read_text())
    except Exception:
        pass
    return {}


def save_table(table: dict) -> None:
    try:
        CALIB_TABLE.write_text(json.dumps(table, ensure_ascii=False, indent=0))
    except Exception:
        pass
