"""Дедуп тезисов ДО AI: не платить за оценку date-вариантов одного тезиса.

Раньше scan() оценивал ВСЕ варианты ('Iran deal by Aug', '...by Oct', '...by
Dec'), потом схлопывал в один — платя за 3, оставляя 1. Теперь схлопываем по
тезису ДО вызова AI: оценивается один представитель (с лучшей структурной
привлекательностью — NO ближе к центру полосы), остальные не идут в LLM.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_scanner import scan


def _market(q, no_price, liq=10000, days_left=30):
    from datetime import datetime, timezone, timedelta
    end = (datetime.now(timezone.utc) + timedelta(days=days_left)).isoformat()
    yes = round(1 - no_price, 2)
    return {"question": q, "conditionId": "c_" + q[:10],
            "outcomes": '["Yes","No"]', "outcomePrices": f'["{yes}","{no_price}"]',
            "liquidity": liq, "endDate": end, "events": [{"slug": "s"}]}


def test_thesis_variants_evaluated_once():
    calls = []
    def ai_fn(q, *a):
        calls.append(q)
        return {"prob": 0.10, "conf": "high", "why": "x"}
    markets = [
        _market("US x Iran peace deal by August 31, 2026", 0.40),
        _market("US x Iran peace deal by October 31, 2026", 0.45),
        _market("US x Iran peace deal by December 31, 2026", 0.50),
    ]
    scan(markets, ai_fn)
    # AI вызван ОДИН раз на тезис, не три
    assert len(calls) == 1


def test_distinct_theses_each_evaluated():
    calls = []
    def ai_fn(q, *a):
        calls.append(q)
        return {"prob": 0.10, "conf": "high", "why": "x"}
    markets = [
        _market("US x Iran peace deal by August 31, 2026", 0.40),
        _market("Will Maduro remain leader by December 31, 2026", 0.40),
    ]
    scan(markets, ai_fn)
    assert len(calls) == 2      # разные тезисы — оба оцениваются
