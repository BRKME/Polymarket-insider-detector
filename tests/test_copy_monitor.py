"""Копи-монитор: свежие спортивные входы доверенных китов → копи-алерт.
Только BUY, только спорт, только свежий вход (цена ≤3¢ от китовой), только
новые (не дублировать уже виденное)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copy_monitor import copy_signal, is_fresh_sport_buy


def _act(side="BUY", price=0.60, title="England vs France", type_="TRADE",
         outcome="Yes"):
    return {"side": side, "price": price, "title": title, "type": type_,
            "outcome": outcome, "conditionId": "0xabc", "size": 500}


def test_fresh_sport_buy_accepted():
    assert is_fresh_sport_buy(_act(), current_price=0.62) is True   # 2¢ — свежо


def test_sell_ignored():
    assert is_fresh_sport_buy(_act(side="SELL"), current_price=0.60) is False


def test_nonsport_ignored():
    a = _act(title="Will Fed cut rates?")
    assert is_fresh_sport_buy(a, current_price=0.60) is False


def test_stale_entry_ignored():
    # цена убежала на 6¢ от входа кита — копировать поздно
    assert is_fresh_sport_buy(_act(price=0.60), current_price=0.66) is False


def test_copy_signal_builds_alert():
    sig = copy_signal(whale_name="easymoney9", whale_eff=0.49,
                      act=_act(price=0.60), current_price=0.61)
    assert sig is not None
    assert "easymoney9" in sig
    assert "England" in sig


def test_copy_signal_none_when_stale():
    sig = copy_signal(whale_name="x", whale_eff=0.3,
                      act=_act(price=0.60), current_price=0.70)
    assert sig is None


# ── V2: outcome-фильтр (кит мог купить NO — это НЕ YES-сигнал) ──

def test_no_outcome_buy_rejected():
    """Кит купил NO-токен: BUY проходит, но копировать как YES нельзя."""
    a = _act(); a["outcome"] = "No"
    assert is_fresh_sport_buy(a, current_price=0.60) is False


def test_yes_outcome_buy_accepted():
    a = _act(); a["outcome"] = "Yes"
    assert is_fresh_sport_buy(a, current_price=0.61) is True


def test_missing_outcome_fail_closed():
    """Нет поля outcome — направление неизвестно, для ставочного сигнала это отказ."""
    a = _act()
    a.pop("outcome", None)
    assert is_fresh_sport_buy(a, current_price=0.60) is False


def test_outcome_case_insensitive():
    a = _act(); a["outcome"] = "YES"
    assert is_fresh_sport_buy(a, current_price=0.60) is True


# ── V2: окно свежести по времени сделки ──

def test_recent_activity_within_age_window():
    from copy_monitor import act_is_recent
    now = 1_800_000_000
    assert act_is_recent({"timestamp": now - 3600}, now_ts=now) is True      # 1ч


def test_old_activity_rejected():
    from copy_monitor import act_is_recent, MAX_ACT_AGE_H
    now = 1_800_000_000
    old = now - (MAX_ACT_AGE_H * 3600 + 60)
    assert act_is_recent({"timestamp": old}, now_ts=now) is False


def test_missing_timestamp_fail_closed():
    from copy_monitor import act_is_recent
    assert act_is_recent({}, now_ts=1_800_000_000) is False


# ── V2: live-цена обязательна, фабрикация запрещена ──

def test_run_skips_act_when_live_price_unavailable():
    """price_fn вернула None — сигнал НЕ строится (никаких cur=entry)."""
    import copy_monitor as cmn
    sent = []
    acts = [{**_act(), "outcome": "Yes", "timestamp": 1_800_000_000}]
    n = cmn.process_whale_acts(
        whale_name="w", whale_eff=0.5, acts=acts,
        price_fn=lambda cid: None,          # live-цена недоступна
        send_fn=lambda msg: sent.append(msg),
        seen=set(), new_seen=set(), now_ts=1_800_000_100)
    assert n == 0 and sent == []


def test_run_alerts_with_real_live_price():
    import copy_monitor as cmn
    sent = []
    acts = [{**_act(price=0.60), "outcome": "Yes", "timestamp": 1_800_000_000}]
    n = cmn.process_whale_acts(
        whale_name="w", whale_eff=0.5, acts=acts,
        price_fn=lambda cid: 0.62,          # реальная цена, сдвиг 2¢ — свежо
        send_fn=lambda msg: sent.append(msg),
        seen=set(), new_seen=set(), now_ts=1_800_000_100)
    assert n == 1 and "62¢" in sent[0]


def test_run_rejects_when_price_ran_away():
    """Живая цена убежала на 8¢ — раньше это пролезало из-за cur=entry."""
    import copy_monitor as cmn
    sent = []
    acts = [{**_act(price=0.60), "outcome": "Yes", "timestamp": 1_800_000_000}]
    n = cmn.process_whale_acts(
        whale_name="w", whale_eff=0.5, acts=acts,
        price_fn=lambda cid: 0.68,
        send_fn=lambda msg: sent.append(msg),
        seen=set(), new_seen=set(), now_ts=1_800_000_100)
    assert n == 0 and sent == []
