"""daily_status.py — дневной информационный статус Polymarket (раз в день).

Позиции НЕ бинарны: токены NO/YES торгуются непрерывно, их можно продать
(зафиксировать прибыль/убыток) или докупить, не дожидаясь резолва. Статус
показывает живую P&L-картину с МЯГКИМИ подсказками действий (наблюдения к
решению оператора, не приказы).

Формат: шапка (открытых позиций · суммарный нереал. P&L · в плюсе/минусе) +
детали ТОЛЬКО по двигавшимся заметно (≥ MOVE_THRESHOLD_PCT) или близким к
резолву. Переиспользует position_pnl/decide_exit из mark_to_market.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import mark_to_market as mtm
from config import EXIT_PARTIAL_PRICE, EXIT_STOP_EDGE

MOVE_THRESHOLD_PCT = 15.0    # цена сдвинулась на столько — позиция «двигалась»
NEAR_RESOLUTION_DAYS = 7     # ближе этого к резолву — флаг
ADD_DRAWDOWN_PCT = -15.0     # просадка глубже — кандидат на докуп (если тезис цел)
THESIS_INTACT_AI_YES = 0.40  # AI всё ещё считает YES маловероятным -> тезис цел
TAKE_PROFIT_RET_PCT = 40.0   # рост NO на столько -> подсказка зафиксировать
                             # (информационно, мягче порога авто-выхода 0.80¢)
GARBAGE_DROP_PCT = -85.0     # падение глубже -> подозрение на мусор API (пустой
                             # ордербук отдаёт ~1¢), не реальная котировка


def smart_truncate(text: str, max_len: int) -> str:
    """Обрезка по границе слова с многоточием — не рвёт слова посередине."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rstrip()
    # откатываемся до последнего пробела, чтобы не резать слово
    if " " in cut:
        cut = cut[:cut.rfind(" ")].rstrip()
    return cut + "…"


def is_plausible_price(entry: float, current: float) -> bool:
    """Отбраковка мусорных цен Data API.

    Пустой/неликвидный ордербук часто отдаёт ~1¢, что парсер принимает за
    реальную котировку и рисует −98%. Если цена обвалилась глубже
    GARBAGE_DROP_PCT от входа — это подозрение на мусор, не котировка.
    Резолв (легитимный 0/1) обрабатывается отдельно по статусу, не здесь.
    """
    if entry <= 0 or current <= 0:
        return False
    ret_pct = (current / entry - 1.0) * 100.0
    return ret_pct > GARBAGE_DROP_PCT


def position_action_hint(entry: float, current: float, ai_yes: Optional[float],
                         horizon_days: Optional[float]) -> Optional[str]:
    """Мягкая подсказка действия по небинарной позиции (или None).

    Порядок: фиксация прибыли → слом тезиса (режь) → докуп на просадке при
    целом тезисе → близость резолва. Иначе тишина.
    """
    if entry <= 0 or current <= 0:
        return None
    ret_pct = (current / entry - 1.0) * 100.0

    # 1. Прибыль доросла до зоны фиксации (по цене ИЛИ по доходности)
    if current >= EXIT_PARTIAL_PRICE or ret_pct >= TAKE_PROFIT_RET_PCT:
        return (f"NO {entry*100:.0f}¢→{current*100:.0f}¢ (+{ret_pct:.0f}%) — "
                f"можно зафиксировать (продать часть/всё), не ждать резолва")

    # текущий edge = (1 - current_no) - ai_yes — насколько NO ещё недооценён
    cur_edge = None
    if ai_yes is not None:
        cur_edge = (1 - current) - ai_yes

    # 2. Тезис сломан: цена против нас И edge инвертировался
    if ret_pct < ADD_DRAWDOWN_PCT and cur_edge is not None and cur_edge <= EXIT_STOP_EDGE:
        return (f"NO {entry*100:.0f}¢→{current*100:.0f}¢ ({ret_pct:.0f}%) — "
                f"AI пересмотрел YES вверх, тезис под вопросом → рассмотри выход (режь)")

    # 3. Просадка, но тезис цел -> кандидат на докуп
    if ret_pct < ADD_DRAWDOWN_PCT and ai_yes is not None and ai_yes <= THESIS_INTACT_AI_YES:
        return (f"NO {entry*100:.0f}¢→{current*100:.0f}¢ ({ret_pct:.0f}%) — "
                f"просадка, но тезис цел (AI YES {ai_yes*100:.0f}%) → можно докупить дешевле")

    # 4. Близко к резолву
    if horizon_days is not None and 0 <= horizon_days <= NEAR_RESOLUTION_DAYS:
        return (f"NO {current*100:.0f}¢ — резолв через {horizon_days:.0f}д, "
                f"реши: держать до конца или зафиксировать сейчас")

    return None


def _open_rows(journal: List[dict]) -> List[dict]:
    return [r for r in journal
            if str(r.get("status", "open")).lower() == "open"]


def build_daily_status(journal: List[dict],
                       price_fn: Callable[[str], Optional[float]],
                       confirmed_only: bool = True) -> str:
    """Дневной статус: шапка + детали по двигавшимся/близким к резолву.

    confirmed_only=True (по умолчанию): P&L считается ТОЛЬКО по реально
    подтверждённым ончейном позициям (fill_source=onchain + entry_price_actual).
    Журнал — это лог АЛЕРТОВ, не портфель; считать P&L по непокупленным алертам
    = фантомный убыток (баг 15.06: −$114 при банке $120 по 11 алертам).
    """
    rows = _open_rows(journal)
    if confirmed_only:
        rows = [r for r in rows
                if r.get("fill_source") == "onchain"
                and r.get("entry_price_actual")]
    n = len(rows)
    if n == 0:
        return ("📊 Polymarket — дневной статус\n"
                "Подтверждённых ончейном позиций: 0.\n"
                "<i>Журнал содержит алерты, но реальных (ончейн) входов "
                "не зафиксировано — показывать P&L не по чему.</i>")

    total_unreal = 0.0
    total_stake = 0.0
    in_profit = in_loss = 0
    detail_lines: List[str] = []
    priced = 0
    skipped_garbage = 0

    for r in rows:
        cid = r.get("condition_id", "")
        entry = mtm.entry_no_price(r)
        stake = mtm.position_stake(r)
        if entry is None or entry <= 0:
            continue
        current = price_fn(cid)
        if current is None or current <= 0:
            continue                       # цена недоступна — пропускаем тихо
        if not is_plausible_price(entry, current):
            skipped_garbage += 1           # мусорная цена API — не считаем
            continue
        priced += 1
        pnl = mtm.position_pnl(entry, current, stake)
        total_unreal += pnl["unrealised"]
        total_stake += stake
        if pnl["unrealised"] >= 0:
            in_profit += 1
        else:
            in_loss += 1

        moved = abs(pnl["ret_pct"]) >= MOVE_THRESHOLD_PCT
        hd = r.get("horizon_days")
        near = hd is not None and 0 <= hd <= NEAR_RESOLUTION_DAYS
        if moved or near:
            q = smart_truncate(r.get("question") or "", 44)
            hint = position_action_hint(entry, current,
                                        r.get("ai_yes_estimate"), hd)
            marker = "🟢" if pnl["unrealised"] >= 0 else "🔴"
            line = (f"{marker} {q}\n"
                    f"  {pnl['ret_pct']:+.0f}% (${pnl['unrealised']:+.0f})")
            if hint:
                line += f"\n  → {hint}"
            detail_lines.append((abs(pnl["ret_pct"]), line))

    pnl_pct = (total_unreal / total_stake * 100.0) if total_stake > 0 else 0.0
    pnl_emoji = "🟢" if total_unreal >= 0 else "🔴"
    coverage = "" if priced == n else f" ({priced}/{n} оценено)"
    header = (f"📊 Polymarket — дневной статус\n"
              f"{pnl_emoji} P&L ${total_unreal:+.0f} от ${total_stake:.0f} "
              f"({pnl_pct:+.0f}%)\n"
              f"Позиций: {n}{coverage} · в плюсе {in_profit} / в минусе {in_loss}")
    if skipped_garbage:
        header += f"\n⚠️ {skipped_garbage} с подозрительной ценой API — пропущены"

    parts = [header]
    has_hint = any("→" in line for _, line in detail_lines)
    if detail_lines:
        parts.append("\nДвигались / близко к резолву:")
        # сортировка по величине движения — важное выше
        for _, line in sorted(detail_lines, key=lambda x: x[0], reverse=True):
            parts.append(line)
    else:
        parts.append("\nЗаметных движений нет — позиции зреют.")
    # дисклеймер про небинарность — только когда есть подсказка действия
    if has_hint:
        parts.append("\n<i>Позиции не бинарны: NO можно продать (зафиксировать) "
                     "или докупить при движении цены, не дожидаясь резолва.</i>")
    return "\n".join(parts)


def main() -> None:
    import json
    from pathlib import Path
    journal_path = Path("event_journal.jsonl")
    journal = []
    if journal_path.exists():
        for line in journal_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    journal.append(json.loads(line))
                except Exception:
                    continue

    def price_fn(cid: str) -> Optional[float]:
        try:
            return mtm.current_no_price(cid, mtm._default_fetch)
        except Exception:
            return None

    msg = build_daily_status(journal, price_fn)
    print(msg)
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                      "parse_mode": "HTML", "disable_notification": True},
                timeout=10).raise_for_status()
            print("sent")
    except Exception as e:  # noqa: BLE001
        print(f"telegram send failed: {e}")


if __name__ == "__main__":
    main()
