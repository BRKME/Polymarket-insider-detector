"""Whale scout — ДИАГНОСТИКА, не торговля.

Вопрос до постройки копи-трейда: существуют ли вообще спортивные киты, проходящие
строгие пороги (WR≥65%, N≥15, 90д)? Этот скрипт собирает недавние спортивные
сделки, группирует по кошелькам, считает спортивный WR по резолвам и печатает
список кандидатов. НИКАКИХ алертов и ставок — только ответ «есть рыба или нет».

Запуск в Actions (data-api доступен): python3 whale_scout.py
"""
from __future__ import annotations
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

try:
    import requests
except Exception:
    requests = None

from config import DATA_API_URL
from whale_scoring import (sport_win_rate, is_trusted_whale, WhaleStats,
                           _is_sport, WHALE_MIN_WR, WHALE_MIN_N,
                           WHALE_WINDOW_DAYS)

GAMMA_API = "https://gamma-api.polymarket.com"
PAGES = 40
LIMIT = 500
MIN_TRADE_USD = 100          # ниже порог — не упустить китов ЧМ

# Спорт определяем по НАЗВАНИЮ рынка (категория в Gamma часто пустая).
# ТОЛЬКО однозначные маркеры — общие глаголы ('to win') ловят политику.
_SPORT_TITLE_KW = [
    " vs ", " vs. ", "nba", "nfl", "mlb", "nhl", "ncaa",
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
    "champions league", "world cup", "super bowl", "playoff",
    "ufc", "mma", "boxing match", "atp", "wta", "grand slam",
    "grand prix", " pga ", "wimbledon", "us open tennis",
    "nba finals", "nfl ", "stanley cup", "premier league",
]
# эспорт исключаем — по прежней логике collector (нет доказанного edge)
_ESPORTS_KW = ["counter-strike", "cs2", "valorant", "dota", "league of legends",
               "lol:", "overwatch", "map winner", "esports"]


def _title_is_sport(title: str) -> bool:
    t = (title or "").lower()
    if not t:
        return False
    if any(k in t for k in _ESPORTS_KW):
        return False
    return any(k in t for k in _SPORT_TITLE_KW)


def _fetch_recent_trades() -> list:
    """Недавние сделки из data-api (постранично)."""
    out = []
    for page in range(PAGES):
        try:
            r = requests.get(f"{DATA_API_URL}/trades",
                             params={"limit": LIMIT, "offset": page * LIMIT,
                                     "sortBy": "TIMESTAMP",
                                     "sortDirection": "DESC"}, timeout=25)
            if r.status_code != 200:
                break
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < LIMIT:
                break
        except Exception as e:
            print(f"  fetch error page {page}: {e}")
            break
    return out


def _market_category(condition_id: str, cache: dict) -> str:
    """Категория рынка по conditionId (Gamma), с кэшем."""
    if condition_id in cache:
        return cache[condition_id]
    cat = ""
    try:
        r = requests.get(f"{GAMMA_API}/markets",
                         params={"condition_ids": condition_id}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            rec = data[0] if isinstance(data, list) and data else data
            if isinstance(rec, dict):
                # категория может лежать в разных полях
                cat = (rec.get("category") or "").lower()
                # эвристика по тегам событий
                if not cat:
                    events = rec.get("events") or []
                    if events and isinstance(events, list):
                        cat = (events[0].get("category") or "").lower()
    except Exception:
        pass
    cache[condition_id] = cat
    return cat


def scout() -> None:
    if requests is None:
        print("requests недоступен")
        return
    print(f"[{datetime.now(timezone.utc).isoformat()}] Whale scout — сбор спортивных китов")
    trades = _fetch_recent_trades()
    print(f"  собрано сделок: {len(trades)}")
    if not trades:
        print("  data-api не отдал сделок (заблокирован или пусто)")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=WHALE_WINDOW_DAYS)
    # кошелёк -> список {category, won, ts}
    by_wallet: dict = defaultdict(list)
    last_ts: dict = {}
    sport_trade_count = 0
    sample_titles = []

    for t in trades:
        wallet = t.get("proxyWallet")
        if not wallet:
            continue
        usd = float(t.get("usdcSize", 0) or t.get("size", 0) or 0)
        if usd < MIN_TRADE_USD:
            continue
        ts_raw = t.get("timestamp", 0)
        try:
            ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        except Exception:
            continue
        if ts < cutoff:
            continue
        title = t.get("title", "") or ""
        if not _title_is_sport(title):
            continue
        sport_trade_count += 1
        if len(sample_titles) < 8:
            sample_titles.append(title[:60])
        # исход: resolved-поле сделки, если есть
        won = t.get("won")
        if won is None:
            payout = t.get("payout")
            if payout is not None:
                won = float(payout) > 0
        by_wallet[wallet].append({"category": "sports", "won": won})
        last_ts[wallet] = max(last_ts.get(wallet, ts), ts)

    print(f"  спортивных сделок (по названию, ≥${MIN_TRADE_USD}): {sport_trade_count}")
    print(f"  спортивных кошельков: {len(by_wallet)}")
    if sample_titles:
        print("  примеры спортивных названий:")
        for s in sample_titles:
            print(f"    • {s}")

    # ДИАГНОСТИКА: какие футбольные/ЧМ названия НЕ попали в спорт (детектор
    # мог их пропустить). Показываем уникальные названия с футбольными словами.
    football_words = ["world cup", "fifa", "vs", "brazil", "argentina", "france",
                      "spain", "germany", "england", "portugal", "netherlands",
                      "group ", "quarterfinal", "semifinal", "knockout"]
    missed = {}
    for t in trades:
        title = (t.get("title", "") or "")
        tl = title.lower()
        if any(w in tl for w in football_words) and not _title_is_sport(title):
            missed[title[:70]] = missed.get(title[:70], 0) + 1
    if missed:
        print(f"\n  ⚠️ НЕ распознаны как спорт, но похожи на футбол/ЧМ "
              f"({len(missed)} уникальных):")
        for title, cnt in sorted(missed.items(), key=lambda x: -x[1])[:15]:
            print(f"    ✗ [{cnt}x] {title}")

    # скоринг
    trusted, near = [], []
    for wallet, tr in by_wallet.items():
        wr, n = sport_win_rate(tr)
        stats = WhaleStats(sport_wr=wr, sport_n=n, last_trade_ts=last_ts.get(wallet))
        if is_trusted_whale(stats):
            trusted.append((wallet, wr, n))
        elif n >= 5 and wr >= 0.55:      # близкие к порогу — для картины
            near.append((wallet, wr, n))

    trusted.sort(key=lambda x: (-x[1], -x[2]))
    near.sort(key=lambda x: (-x[1], -x[2]))

    print("\n=== ДОВЕРЕННЫЕ КИТЫ (WR≥{:.0%}, N≥{}, 90д) ===".format(
        WHALE_MIN_WR, WHALE_MIN_N))
    if trusted:
        for w, wr, n in trusted:
            print(f"  {w[:10]}… · спорт WR {wr:.0%} · N={n}")
    else:
        print("  НЕТ китов, проходящих строгие пороги.")
    print(f"\n=== БЛИЗКИЕ (WR≥55%, N≥5) — для оценки, есть ли потенциал ===")
    if near:
        for w, wr, n in near[:15]:
            print(f"  {w[:10]}… · спорт WR {wr:.0%} · N={n}")
    else:
        print("  Нет и близких.")

    print(f"\nИТОГ: доверенных {len(trusted)}, близких {len(near)}. "
          f"{'Есть основа для копи-трейда.' if trusted else 'Основы пока нет — порог не проходит никто.'}")


if __name__ == "__main__":
    scout()
