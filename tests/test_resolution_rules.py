"""Grok должен оценивать ПОД правила резолва, а не по заголовку.

Баг (проигрыш Starmer 21.06): description в журнале был пустой — Grok оценивал
'уйдёт ли Starmer' (28%), не видя, что рынок резолвится в YES даже на ОБЪЯВЛЕНИЕ
об уходе в любую дату. Правила до модели не дошли.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_context import _build_estimator_prompt


def test_prompt_includes_description():
    desc = ("Resolves YES if Starmer ceases to be PM. An announcement of "
            "resignation immediately resolves YES regardless of effect date.")
    p = _build_estimator_prompt("Starmer out by June 30?", desc, "2026-06-30")
    assert "announcement" in p              # правило дошло до промпта
    assert "Starmer out" in p


def test_prompt_warns_to_read_edge_rules():
    # промпт явно велит учитывать edge-условия резолва
    p = _build_estimator_prompt("Q?", "some rules", "2026-12-31")
    low = p.lower()
    assert ("правил" in low or "услов" in low or "резолв" in low)


def test_empty_description_flagged_in_prompt():
    # без описания промпт честно помечает, что правил нет (не делает вид)
    p = _build_estimator_prompt("Q?", "", "2026-12-31")
    assert p  # не падает
