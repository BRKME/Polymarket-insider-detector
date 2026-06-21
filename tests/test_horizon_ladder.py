"""Лестница сроков одного тезиса: 'Starmer by June' и 'by December' — не дубли,
а разные ставки. Дедуп оставляем (не платим за оба поиска), но представителя
выбираем по edge × краткосрочность: предпочесть срок, где и переоценка хорошая,
и окно узкое (NO надёжнее). Для held длинного — предупреждение про риск окна.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_scanner import _horizon_score, scan


def test_short_horizon_scores_higher_at_equal_edge():
    # равный edge, но короче срок -> выше score (NO надёжнее в узком окне)
    short = _horizon_score(edge=0.30, hours_to_resolve=9 * 24)
    long = _horizon_score(edge=0.30, hours_to_resolve=200 * 24)
    assert short > long


def test_big_edge_can_beat_slightly_longer():
    # значительно больший edge перевешивает чуть более длинный срок
    a = _horizon_score(edge=0.60, hours_to_resolve=40 * 24)
    b = _horizon_score(edge=0.15, hours_to_resolve=20 * 24)
    assert a > b


def test_scan_picks_short_horizon_representative():
    from datetime import datetime, timezone, timedelta
    def mk(q, days, no_price):
        end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        yes = round(1 - no_price, 2)
        return {"question": q, "conditionId": "c" + str(days),
                "outcomes": '["Yes","No"]',
                "outcomePrices": f'["{yes}","{no_price}"]',
                "liquidity": 50000, "endDate": end, "events": [{"slug": "s"}]}
    calls = []
    def ai_fn(q, *a):
        calls.append(q)
        return {"prob": 0.28, "conf": "medium", "why": "x"}
    markets = [
        mk("Starmer out by December 31, 2026", 190, 0.30),
        mk("Starmer out by June 30, 2026", 9, 0.12),   # короткий, дешёвый NO
    ]
    res = scan(markets, ai_fn)
    # один тезис -> один AI-вызов (дедуп сохранён)
    assert len(calls) == 1
    # представитель — короткий срок
    assert "June" in calls[0]


def test_long_window_warning_in_alert():
    from datetime import datetime, timezone, timedelta
    import scan_events as se
    end = (datetime.now(timezone.utc) + timedelta(days=190)).isoformat()
    c = se.es.Candidate(
        question="Starmer out by December 31, 2026", no_price=0.30,
        market_yes_price=0.70, ai_yes_estimate=0.28, ai_conf="medium",
        edge=0.42, reasoning="parliament backs him", liquidity=50000,
        end_date=end, suspicious=False, condition_id="0xL")
    msg = se._format_alert(c)
    assert "Длинное окно" in msg
    assert "более короткий срок" in msg


def test_short_window_no_warning():
    from datetime import datetime, timezone, timedelta
    import scan_events as se
    end = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
    c = se.es.Candidate(
        question="Starmer out by June 30, 2026", no_price=0.12,
        market_yes_price=0.88, ai_yes_estimate=0.28, ai_conf="medium",
        edge=0.60, reasoning="parliament backs him", liquidity=86000,
        end_date=end, suspicious=False, condition_id="0xS")
    msg = se._format_alert(c)
    assert "Длинное окно" not in msg
