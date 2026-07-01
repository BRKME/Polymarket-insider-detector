"""Скоринг спортивных китов для копи-трейда (без Grok).

Возврат спорта после провала предсказательной NO/YES-логики — но НЕ через Grok
(он проигрывает эффективному спортивному рынку), а через копирование китов с
доказанным инсайдом. Спорт-рынки эффективны для ПРЕДСКАЗАНИЯ, но кит с инсайдом
(состав, травма, договорняк) виден ончейн — за ним и следуем.

Решение эксперта: мало, но надёжных. Четыре ворота, ВСЕ обязательны:
1. Спортивный WR ≥ 65% — считается ТОЛЬКО по спортивным резолвам кошелька
   (кит, гениальный в крипте, может быть слеп в футболе).
2. N ≥ 15 спортивных резолвов — защита от survivorship bias: на малой выборке
   даже 100% WR это шум (из тысяч китов кто-то везучий случайно).
3. Окно 90 дней — недавний трек: инсайд-источник мог иссякнуть, старые победы
   не в счёт.
4. (при копировании) свежесть входа ≤3¢ — если цена убежала от точки входа
   кита, его edge уже частично съеден, копировать поздно. См. entry_still_fresh.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

WHALE_MIN_WR = 0.65
WHALE_MIN_N = 15
WHALE_WINDOW_DAYS = 90
COPY_MAX_SLIPPAGE = 0.03          # 3¢ — дальше вход считается убежавшим

_SPORT_CATS = {"sports", "sport", "nfl", "nba", "mlb", "nhl", "soccer",
               "football", "basketball", "baseball", "hockey", "tennis",
               "mma", "ufc", "boxing", "epl", "la_liga", "serie_a"}


@dataclass
class WhaleStats:
    sport_wr: float
    sport_n: int
    last_trade_ts: Optional[datetime]


def _is_sport(cat: str) -> bool:
    return (cat or "").strip().lower() in _SPORT_CATS


def sport_win_rate(trades: list) -> tuple:
    """WR и N ТОЛЬКО по спортивным резолвнувшимся сделкам кошелька.
    trades: [{category, won}]. Возвращает (wr, n)."""
    sport = [t for t in trades if _is_sport(t.get("category", ""))
             and t.get("won") is not None]
    n = len(sport)
    if n == 0:
        return 0.0, 0
    wins = sum(1 for t in sport if t.get("won"))
    return wins / n, n


def is_trusted_whale(stats: WhaleStats) -> bool:
    """Все четыре ворота (кроме свежести входа — она на этапе копирования)."""
    if stats.sport_n < WHALE_MIN_N:
        return False
    if stats.sport_wr < WHALE_MIN_WR:
        return False
    if stats.last_trade_ts is None:
        return False
    age = datetime.now(timezone.utc) - stats.last_trade_ts
    if age > timedelta(days=WHALE_WINDOW_DAYS):
        return False
    return True


def entry_still_fresh(whale_entry_price: float, current_price: float) -> bool:
    """True, если цена не убежала от точки входа кита дальше COPY_MAX_SLIPPAGE.
    Копируем, только пока вход близок к китовому — иначе edge уже съеден."""
    if whale_entry_price is None or current_price is None:
        return False
    return abs(current_price - whale_entry_price) <= COPY_MAX_SLIPPAGE + 1e-9
