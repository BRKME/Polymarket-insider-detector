# -*- coding: utf-8 -*-
"""exit_dedup.py — дедупликация exit-сигналов mark_to_market.

Баг 15.07: run() слал один и тот же сигнал каждый 2ч-крон, пока позиция
открыта (18:27 и 20:19 — идентичные «РЕЖЬ»). Правило: по одной позиции
повторный алерт только если (а) действие ЭСКАЛИРОВАЛО (другой action) или
(б) прошло ≥ RENOTIFY_HOURS — суточное напоминание, если оператор не
отреагировал. Состояние в exit_seen.json (коммитится ботом, как *_seen.json).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SEEN_PATH = Path("exit_seen.json")
RENOTIFY_HOURS = 24


def load_seen(path: Path = SEEN_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_seen(seen: dict, path: Path = SEEN_PATH) -> None:
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=1))


def should_notify(seen: dict, condition_id: str, action: str,
                  now: datetime) -> bool:
    """True, если сигнал надо отправить. Обновляет seen на отправку.

    Смена action (CUT -> TAKE_PARTIAL -> CLOSE_FULL и обратно) — новая
    информация, шлём сразу. Тот же action — молчим RENOTIFY_HOURS.
    """
    prev = seen.get(condition_id) or {}
    prev_action: Optional[str] = prev.get("action")
    if prev_action == action:
        try:
            last = datetime.fromisoformat(prev.get("ts", ""))
            if now - last < timedelta(hours=RENOTIFY_HOURS):
                return False
        except ValueError:
            pass  # битый ts — считаем, что не слали
    seen[condition_id] = {"action": action, "ts": now.isoformat()}
    return True
