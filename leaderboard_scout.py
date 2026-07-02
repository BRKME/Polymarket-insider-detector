"""Leaderboard scout — диагностика спортивных китов через ОФИЦИАЛЬНЫЙ лидерборд.

Polymarket сам ведёт лидерборд с фильтром category=SPORTS (docs подтвердили).
Отдаёт pnl и vol (НЕ winrate — его нет в API). Компенсируем отсутствие winrate
двумя фильтрами эксперта:

1. Консистентность: кит в топе И за WEEK, И за MONTH — отсекает разовых
   везунчиков (разбогател на одной ставке и исчез).
2. Эффективность: высокий pnl/vol (прокси-ROI) — отсекает тех, кто «заработал»
   гонянием огромного объёма с мизерным edge (невоспроизводимо на малом банке).

Оба фильтра вместе = «мало, но надёжных». Диагностика: печатает, кто проходит,
БЕЗ алертов и ставок. Запуск в Actions: python3 leaderboard_scout.py
"""
from __future__ import annotations

try:
    import requests
except Exception:
    requests = None

LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"

# Единый источник правды порога — trusted_whales.MIN_EFF (иначе диагностика
# скаута и живой список разъезжаются и печатают разных «качественных» китов).
from trusted_whales import MIN_EFF as MIN_PNL_EFFICIENCY
TOP_N = 50                    # смотрим топ-50 каждого окна


def _fetch_leaderboard(period: str) -> list:
    """Спортивный лидерборд за период (WEEK/MONTH), сортировка по PNL."""
    try:
        r = requests.get(LEADERBOARD_URL, params={
            "category": "SPORTS", "timePeriod": period,
            "orderBy": "PNL", "limit": 50}, timeout=25)
        if r.status_code != 200:
            print(f"  {period}: HTTP {r.status_code}")
            return []
        return r.json() or []
    except Exception as e:
        print(f"  {period}: ошибка {e}")
        return []


def scout() -> None:
    if requests is None:
        print("requests недоступен")
        return
    print("Leaderboard scout — спортивные киты (официальный лидерборд Polymarket)")

    week = _fetch_leaderboard("WEEK")
    month = _fetch_leaderboard("MONTH")
    print(f"  топ SPORTS за неделю: {len(week)} · за месяц: {len(month)}")

    if not week and not month:
        print("  лидерборд пуст/недоступен — data-api заблокирован или нет данных")
        return

    # индексируем по кошельку
    def _by_wallet(rows):
        d = {}
        for r in rows:
            w = r.get("proxyWallet")
            if w:
                d[w] = r
        return d

    w_week, w_month = _by_wallet(week), _by_wallet(month)

    # ФИЛЬТР 1 — консистентность: в топе обоих окон
    both = set(w_week) & set(w_month)
    print(f"\n  в топе И за неделю, И за месяц (консистентные): {len(both)}")

    # ФИЛЬТР 2 — эффективность: pnl/vol ≥ порога (по месячным данным)
    qualified = []
    for w in both:
        m = w_month[w]
        pnl = float(m.get("pnl", 0) or 0)
        vol = float(m.get("vol", 0) or 0)
        if vol <= 0 or pnl <= 0:
            continue
        eff = pnl / vol
        if eff >= MIN_PNL_EFFICIENCY:
            qualified.append((w, m.get("userName", "")[:16], pnl, vol, eff))

    qualified.sort(key=lambda x: -x[4])

    print(f"\n=== КАЧЕСТВЕННЫЕ СПОРТ-КИТЫ (консистентны + pnl/vol≥{MIN_PNL_EFFICIENCY:.0%}) ===")
    if qualified:
        for w, name, pnl, vol, eff in qualified:
            print(f"  {w[:10]}… {name:16} · pnl ${pnl:,.0f} · vol ${vol:,.0f} "
                  f"· эфф {eff:.0%}")
    else:
        print("  НЕТ китов, проходящих оба фильтра.")

    # для картины — топ по месяцу без фильтра эффективности
    print(f"\n=== ТОП-5 SPORTS за месяц (для контекста) ===")
    for r in sorted(month, key=lambda x: -float(x.get("pnl", 0) or 0))[:5]:
        pnl = float(r.get("pnl", 0) or 0)
        vol = float(r.get("vol", 0) or 0)
        eff = (pnl / vol) if vol > 0 else 0
        print(f"  {r.get('userName','')[:16]:16} · pnl ${pnl:,.0f} · "
              f"vol ${vol:,.0f} · эфф {eff:.0%}")

    print(f"\nИТОГ: качественных спорт-китов {len(qualified)}. "
          f"{'Есть основа для копи-трейда.' if qualified else 'Основы нет — никто не проходит оба фильтра.'}")

    # Сохраняем ЖИВОЙ список — пересобирается каждый прогон. Копи-монитор читает
    # актуальный набор: выпавшие киты уходят, новые прошедшие фильтр добавляются.
    try:
        import trusted_whales as tw
        trusted = tw.build_trusted(week, month)
        tw.save_trusted(trusted)
        print(f"  живой список обновлён: {len(trusted)} китов в trusted_whales.json")
    except Exception as e:
        print(f"  список не сохранён: {e}")


if __name__ == "__main__":
    scout()
