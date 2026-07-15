# -*- coding: utf-8 -*-
"""Резолюция event_journal (задача 15.07).

До фикса: 55 строк вечно 'open' (включая матчи 4 июля), резолюция журнала
не персистилась нигде — еженедельный отчёт перевыкачивал ВСЕ строки заново,
калибровка Grok пополнялась только раз в неделю ценой O(rows) запросов.

Резолвер: строки со статусом open/re_alert и прошедшим end_date прогоняются
через gamma-каскад resolution_tracker, исход пишется в строку (status,
actual_yes) и в дисковый кэш resolutions.json (один запрос на cid навсегда).
Калибровочная таблица пополняется из calibration_journal по кэшу.
"""
import json
from datetime import datetime, timedelta, timezone

import journal_resolver as jr

NOW = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)
PAST = (NOW - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
FUTURE = (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_market(winner):  # payload как из gamma
    prices = ["1", "0"] if winner == "Yes" else ["0", "1"]
    return {"closed": True, "outcomes": '["Yes", "No"]',
            "outcomePrices": json.dumps(prices)}


def _row(cid, end=PAST, status="open", ai=0.4):
    return {"condition_id": cid, "question": f"Q {cid}", "end_date": end,
            "status": status, "ai_yes_estimate": ai,
            "market_yes_price": 0.5}


# ── резолюция строк журнала ─────────────────────────────────────────────────

def test_resolves_past_open_rows(tmp_path):
    cache = jr.ResolutionCache(tmp_path / "res.json")
    fetch = lambda cid: _mk_market("No")
    rows = [_row("0xa"), _row("0xb", end=FUTURE), _row("0xc", status="closed")]
    updated, stats = jr.resolve_journal(rows, now=NOW, cache=cache, fetch=fetch)
    assert updated[0]["status"] == "resolved"
    assert updated[0]["actual_yes"] == 0.0
    assert updated[0]["resolution"]["outcome"] == "No"
    assert updated[1]["status"] == "open"        # end_date в будущем — не трогаем
    assert updated[2]["status"] == "closed"      # чужой статус — не трогаем
    assert stats == {"resolved": 1, "yes": 0, "no": 1, "pending": 0}


def test_yes_outcome_sets_actual_one(tmp_path):
    cache = jr.ResolutionCache(tmp_path / "res.json")
    updated, _ = jr.resolve_journal([_row("0xa")], now=NOW, cache=cache,
                                    fetch=lambda cid: _mk_market("Yes"))
    assert updated[0]["actual_yes"] == 1.0


def test_unresolved_stays_open_and_counts_pending(tmp_path):
    cache = jr.ResolutionCache(tmp_path / "res.json")
    updated, stats = jr.resolve_journal([_row("0xa")], now=NOW, cache=cache,
                                        fetch=lambda cid: None)
    assert updated[0]["status"] == "open"
    assert "actual_yes" not in updated[0]
    assert stats["pending"] == 1


def test_grace_period_before_resolving():
    """Сразу после end_date рынок ещё может не зарезолвиться — ждём грейс."""
    just_ended = (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert jr.ready_to_resolve(_row("0xa", end=just_ended), NOW) is False
    assert jr.ready_to_resolve(_row("0xa", end=PAST), NOW) is True


def test_re_alert_status_also_resolved(tmp_path):
    cache = jr.ResolutionCache(tmp_path / "res.json")
    updated, _ = jr.resolve_journal([_row("0xa", status="re_alert")],
                                    now=NOW, cache=cache,
                                    fetch=lambda cid: _mk_market("No"))
    assert updated[0]["status"] == "resolved"


# ── кэш: один запрос на cid навсегда ────────────────────────────────────────

def test_cache_prevents_refetch(tmp_path):
    path = tmp_path / "res.json"
    calls = []
    def fetch(cid):
        calls.append(cid)
        return _mk_market("No")
    c1 = jr.ResolutionCache(path)
    assert c1.get_outcome("0xa", fetch) == "No"
    assert c1.get_outcome("0xa", fetch) == "No"    # из памяти
    c1.save()
    c2 = jr.ResolutionCache(path)                   # из файла
    assert c2.get_outcome("0xa", fetch) == "No"
    assert calls == ["0xa"]


def test_cache_does_not_store_unresolved(tmp_path):
    path = tmp_path / "res.json"
    calls = []
    def fetch(cid):
        calls.append(cid)
        return None
    c = jr.ResolutionCache(path)
    assert c.get_outcome("0xa", fetch) is None
    assert c.get_outcome("0xa", fetch) is None     # None не кэшируем — ретрай
    assert calls == ["0xa", "0xa"]


# ── пополнение калибровки из кэша ───────────────────────────────────────────

def test_calibration_pairs_from_cache(tmp_path):
    cache = jr.ResolutionCache(tmp_path / "res.json")
    cache.put("0xa", "No")
    cache.put("0xb", "Yes")
    calib_rows = [
        {"condition_id": "0xa", "market_yes_price": 0.5, "ai_yes_estimate": 0.3},
        {"condition_id": "0xb", "market_yes_price": 0.6, "ai_yes_estimate": 0.7},
        {"condition_id": "0xc", "market_yes_price": 0.5, "ai_yes_estimate": 0.4},
        {"condition_id": "0xa", "market_yes_price": 0.5, "ai_yes_estimate": None},
    ]
    pairs = jr.calibration_pairs(calib_rows, cache)
    assert (0.5, 0.3, 0.0) in pairs
    assert (0.6, 0.7, 1.0) in pairs
    assert len(pairs) == 2      # без резолва и без ai-оценки — мимо


# ── предохранитель: дневной пересбор не должен усаживать боевую таблицу ─────

def test_never_shrink_calibration_table():
    """Еженедельный отчёт строит таблицу живым перевыкачиванием (n=38);
    дневной пересбор из свежего (полу)пустого кэша не имеет права
    перезаписать её меньшей выборкой — тот же инцидент, что уже был
    с тестовым артефактом (см. докстринг save_table)."""
    old = {"0.2-0.4": {"actual": 0.3, "n": 20}, "0.4-0.6": {"actual": 0.5, "n": 18}}
    small = {"0.2-0.4": {"actual": 0.0, "n": 2}}
    bigger = {"0.2-0.4": {"actual": 0.25, "n": 30}, "0.4-0.6": {"actual": 0.5, "n": 18}}
    assert jr.should_save_table(small, old) is False
    assert jr.should_save_table(bigger, old) is True
    assert jr.should_save_table(small, {}) is True      # таблицы ещё нет
