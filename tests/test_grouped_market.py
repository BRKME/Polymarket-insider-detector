"""Детектор групповых/связанных рынков по тексту вопроса. Japan 'Round of 32'
проскочил как бинарный, хотя это рынок-лестница стадий (группа/1/16/1/8/...).
Такие должны помечаться suspicious, чтобы в алерте было 'читай правила'."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_scanner import looks_grouped


def test_round_of_n_flagged():
    assert looks_grouped("Will Japan be eliminated in the Round of 32 of the World Cup?")
    assert looks_grouped("Will Brazil be eliminated in the Round of 16?")


def test_stage_of_elimination_flagged():
    assert looks_grouped("World Cup: Japan Stage of Elimination")


def test_winner_of_flagged():
    assert looks_grouped("Winner of the 2026 World Cup?")
    assert looks_grouped("Who will win the Champions League?")


def test_plain_binary_not_flagged():
    assert not looks_grouped("Will Starmer cease to be PM by December 31?")
    assert not looks_grouped("US x Iran peace deal by August?")


def test_quarterfinal_semifinal():
    assert looks_grouped("Will France reach the quarterfinal?")
    assert looks_grouped("Will Argentina make the semifinals?")
