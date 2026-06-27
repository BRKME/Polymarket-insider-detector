"""Детектор '50-50 при недостижении' — структурно мёртвый edge.

Биткоин-кейс: 'resolve 50-50 if neither occurs by July 31'. GTA выходит в
ноябре, биткоин $1M невозможен — оба за горизонтом резолва → ничья по правилам.
Цена 50¢ корректна, edge нет. Такие рынки гейтим ДО Grok."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_scanner import has_split_resolution


def test_fifty_fifty_clause_detected():
    rules = ("This market will resolve Yes if X before Y. Otherwise No. "
             "If neither occurs by July 31, 2026, this market will resolve 50-50.")
    assert has_split_resolution(rules)


def test_tie_wording_variants():
    assert has_split_resolution("resolves 50/50 if neither happens by the date")
    assert has_split_resolution("will resolve to a tie if neither occurs")
    assert has_split_resolution("resolves 50-50 if both fail to occur")


def test_plain_binary_no_split():
    rules = ("This market resolves Yes if Starmer ceases to be PM by Dec 31. "
             "Otherwise No.")
    assert not has_split_resolution(rules)


def test_empty_rules():
    assert not has_split_resolution("")
    assert not has_split_resolution(None)
