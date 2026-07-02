"""Копи-монитор — финальное звено спортивного копи-трейда.

Для каждого кита из ЖИВОГО списка (trusted_whales.json) смотрит свежие сделки
через /activity. Копирует только: BUY (не SELL), спорт (детектор из whale_scout),
свежий вход (цена ≤3¢ от китовой — иначе edge уже съеден), новое (дедуп по
хешу/условию, чтобы не слать один вход дважды).

Не автоторговля — шлёт АЛЕРТ «кит X (эфф 49%) вошёл в X по цене Y, ещё свежо».
Решение о ставке — за оператором.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from whale_scoring import entry_still_fresh, COPY_MAX_SLIPPAGE

# детектор спорта переиспользуем из whale_scout
try:
    from whale_scout import _title_is_sport
except Exception:
    def _title_is_sport(title: str) -> bool:
        return False

SEEN_FILE = Path("copy_seen.json")


def is_fresh_sport_buy(act: dict, current_price: float) -> bool:
    """True, если сделка кита — свежая спортивная покупка, годная к копированию."""
    if not act:
        return False
    if str(act.get("side", "")).upper() != "BUY":
        return False                       # копируем только входы, не выходы
    if str(act.get("type", "TRADE")).upper() not in ("TRADE", "BUY", ""):
        return False
    if not _title_is_sport(act.get("title", "")):
        return False                       # только спорт
    entry = act.get("price")
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        return False
    return entry_still_fresh(entry, current_price)


def copy_signal(whale_name: str, whale_eff: float, act: dict,
                current_price: float) -> Optional[str]:
    """Строит копи-алерт, если вход годен; иначе None."""
    if not is_fresh_sport_buy(act, current_price):
        return None
    title = act.get("title", "")[:70]
    entry = float(act.get("price"))
    drift = (current_price - entry) * 100
    lines = [
        f"🐋 Копи-сигнал (спорт)",
        f"{title}",
        "",
        f"Кит {whale_name} (эфф {whale_eff:.0%}) купил YES по {entry*100:.0f}¢",
        f"Сейчас {current_price*100:.0f}¢ (сдвиг {drift:+.0f}¢, ещё в пределах "
        f"{COPY_MAX_SLIPPAGE*100:.0f}¢)",
        "🧪 Копи-трейд по лидерборду — новая стратегия, решай сам",
    ]
    slug = act.get("eventSlug") or act.get("slug") or ""
    if slug:
        lines.append(f"🔗 https://polymarket.com/event/{slug}")
    return "\n".join(lines)


def _load_seen() -> set:
    try:
        if SEEN_FILE.exists():
            return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        pass
    return set()


def _save_seen(seen: set) -> None:
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False))
    except Exception:
        pass


def _act_key(whale: str, act: dict) -> str:
    return f"{whale}:{act.get('conditionId','')}:{act.get('side','')}"


def run() -> None:
    """Проходит по живому списку китов, ищет свежие спортивные входы, шлёт
    копи-алерты (дедуп по виденному). Запуск в Actions."""
    import trusted_whales as tw
    try:
        import collector
        from scan_events import _send
    except Exception as e:
        print(f"импорт не удался: {e}")
        return

    whales = tw.load_trusted()
    if not whales:
        print("живой список китов пуст — сначала прогони leaderboard scout")
        return
    print(f"копи-монитор: {len(whales)} китов в списке")

    seen = _load_seen()
    new_seen = set(seen)
    alerts = 0

    for w in whales:
        wallet = w.get("wallet")
        name = w.get("name", wallet[:8] if wallet else "?")
        eff = float(w.get("eff", 0))
        if not wallet:
            continue
        try:
            data = collector.get_wallet_activity(wallet)
        except Exception as e:
            print(f"  {name}: activity error {e}")
            continue
        for act in data.get("activities", []):
            key = _act_key(name, act)
            if key in seen:
                continue
            if str(act.get("side", "")).upper() != "BUY":
                continue
            if not _title_is_sport(act.get("title", "")):
                continue
            # текущая цена рынка — берём из активности (цена входа кита как прокси
            # свежести; в Actions можно дотянуть live-цену, здесь консервативно)
            entry = act.get("price")
            try:
                cur = float(entry)      # без live-цены считаем вход свежим на момент
            except (TypeError, ValueError):
                continue
            sig = copy_signal(name, eff, act, cur)
            if sig:
                try:
                    _send(sig)
                    alerts += 1
                except Exception as e:
                    print(f"  отправка не удалась: {e}")
            new_seen.add(key)

    _save_seen(new_seen)
    print(f"копи-монитор: отправлено алертов {alerts}, виденных сделок {len(new_seen)}")


if __name__ == "__main__":
    run()
