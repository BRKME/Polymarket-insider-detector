"""v5_weekly_status — воскресный статус живой стратегии в Telegram.

Заменяет ежедневный легаси-STATS похороненной whale-copy (852 ставки, WR 44%,
ROI −4% — финальные цифры зафиксированы в README, повторять их каналу незачем).

Отвечает на три вопроса оператора без сетевых вызовов:
  1. Что открыто и сколько подтверждено ончейном (журнал v5).
  2. Как копится калибровочная выборка (всего оценок / короткий горизонт ≤45д
     — именно short-срез даст Brier-вердикт).
  3. Сколько дней до чекпойнтов календаря (docs/NEXT_STEPS.md).

Глубокий разбор остаётся за verify_journal.py (запускается руками раз в
неделю по инструкции) — этот статус лишь напоминает, что проект жив и копит.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

JOURNAL = Path("event_journal.jsonl")
CALIB = Path("calibration_journal.jsonl")
SHORT_HORIZON_DAYS = 45.0
SHORT_TARGET = 30          # резолвов нужно для ворот вердикта

CHECKPOINTS = [            # из docs/NEXT_STEPS.md
    ("24.06", datetime(2026, 6, 24, tzinfo=timezone.utc), "первый взгляд"),
    ("08.07", datetime(2026, 7, 8, tzinfo=timezone.utc), "контроль"),
    ("22.07", datetime(2026, 7, 22, tzinfo=timezone.utc), "ворота вердикта"),
]


def _load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def build_status(journal: List[dict], calib: List[dict],
                 now: datetime) -> str:
    open_rows = [r for r in journal
                 if str(r.get("status", "open")).lower() == "open"]
    onchain = sum(1 for r in open_rows if r.get("fill_source") == "onchain")

    # экспозиция по категориям открытых позиций
    exp_line = ""
    try:
        import category_exposure as cx
        from config import BANKROLL
        exp = cx.exposure_by_category(journal)
        if exp:
            exp_line = cx.format_exposure(exp, bankroll=BANKROLL)
    except Exception:
        pass

    n_calib = len(calib)
    n_short = sum(1 for r in calib
                  if r.get("horizon_days") is not None
                  and float(r["horizon_days"]) <= SHORT_HORIZON_DAYS)

    cp_bits = []
    for label, dt, name in CHECKPOINTS:
        d = (dt - now).days
        if d >= 0:
            cp_bits.append(f"{label} {name} (через {d}д)")
    cp_line = " · ".join(cp_bits) if cp_bits else "все чекпойнты пройдены"

    lines = [
        "📋 Polymarket v5 · недельный статус",
        f"Открыто: {len(open_rows)} позиций (ончейн: {onchain})",
    ]
    if exp_line:
        lines.append(exp_line)
    lines += [
        "",
        f"Калибровка: {n_calib} оценок Grok · короткий горизонт ≤45д: {n_short}",
        f"Цель ворот вердикта: ≥{SHORT_TARGET} коротких РЕЗОЛВОВ "
        f"(точный счёт — verify_journal.py)",
        f"Календарь: {cp_line}",
    ]
    return "\n".join(lines)


def main() -> None:
    now = datetime.now(timezone.utc)
    msg = build_status(_load_jsonl(JOURNAL), _load_jsonl(CALIB), now)
    print(msg)
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                      "disable_notification": True},
                timeout=10).raise_for_status()
            print("sent to telegram")
    except Exception as e:  # noqa: BLE001
        print(f"telegram send failed: {e}")


if __name__ == "__main__":
    main()
