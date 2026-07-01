"""Живой список доверенных спорт-китов.

Пересобирается еженедельно из официального лидерборда Polymarket (category=SPORTS)
и сохраняется в trusted_whales.json. Список ДЫШИТ: кит, выпавший из топа, уходит;
новый, прошедший фильтры — добавляется. Копи-монитор читает актуальный набор, а
не захардкоженный — иначе через месяц копировались бы вчерашние чемпионы.

Два фильтра (как в диагностике):
1. Консистентность — в топе И за неделю, И за месяц (не разовый везунчик).
2. Эффективность — pnl/vol ≥ MIN_EFF (не объёмщик с тонким edge).

Решение эксперта: держим ВСЕ прошедшие фильтр (~20), не сужаем до топ-5 —
диверсификация важнее концентрации, т.к. каждый кит это ставка на сохранение
прошлого edge, и одна остывшая звезда не должна ломать выборку.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

TRUSTED_FILE = Path("trusted_whales.json")
MIN_EFF = 0.10          # pnl/vol ≥ 10% — прокси-ROI


def _index(rows: list) -> dict:
    d = {}
    for r in rows or []:
        w = r.get("proxyWallet")
        if w:
            d[w] = r
    return d


def build_trusted(week: list, month: list) -> list:
    """Список доверенных: консистентные (оба окна) И эффективные (pnl/vol≥MIN_EFF).
    Эффективность считаем по МЕСЯЧНЫМ данным (устойчивее недельных)."""
    w_week, w_month = _index(week), _index(month)
    both = set(w_week) & set(w_month)
    out = []
    for wallet in both:
        m = w_month[wallet]
        pnl = float(m.get("pnl", 0) or 0)
        vol = float(m.get("vol", 0) or 0)
        if vol <= 0 or pnl <= 0:
            continue
        eff = pnl / vol
        if eff < MIN_EFF:
            continue
        out.append({"wallet": wallet, "name": m.get("userName", "")[:20],
                    "eff": round(eff, 3), "pnl": round(pnl)})
    out.sort(key=lambda x: -x["eff"])
    return out


def save_trusted(trusted: list, path: Optional[str] = None) -> None:
    p = Path(path) if path else TRUSTED_FILE
    try:
        p.write_text(json.dumps(trusted, ensure_ascii=False, indent=0))
    except Exception:
        pass


def load_trusted(path: Optional[str] = None) -> list:
    p = Path(path) if path else TRUSTED_FILE
    try:
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return []
