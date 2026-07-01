"""YES-стратегия: ставим YES, где рыночная цена YES в зоне 50-70% И Grok
согласен по направлению (тоже склонён к YES). Разворот прежней логики: плывём
ПО рынку, а не против. Опора на калиброванную зону, где Grok надёжен."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yes_strategy import yes_gate, yes_edge, YES_MIN, YES_MAX


def test_gate_accepts_mid_zone():
    assert yes_gate(0.60) is True      # 60% — в зоне
    assert yes_gate(0.50) is True      # граница включительно
    assert yes_gate(0.70) is True


def test_gate_rejects_outside():
    assert yes_gate(0.45) is False     # ниже — монетка/андердог
    assert yes_gate(0.85) is False     # выше — дорогой фаворит, ed"ge нет
    assert yes_gate(0.90) is False


def test_edge_when_grok_agrees():
    # рынок YES 0.60, Grok YES 0.72 -> согласие + Grok выше -> edge положительный
    e = yes_edge(market_yes=0.60, grok_yes=0.72)
    assert e is not None and e > 0


def test_no_edge_when_grok_disagrees():
    # Grok склонён к NO (0.30) — направление не совпало -> нет сигнала
    assert yes_edge(market_yes=0.60, grok_yes=0.30) is None


def test_agreement_by_direction_enough():
    # Grok чуть ниже рынка, но всё ещё YES-склонён (>0.5) -> согласие есть
    e = yes_edge(market_yes=0.65, grok_yes=0.55)
    assert e is not None            # согласия по направлению достаточно


def test_grok_must_be_yes_leaning():
    # Grok ровно 0.5 — не склонён ни туда ни сюда -> нет согласия
    assert yes_edge(market_yes=0.60, grok_yes=0.50) is None
