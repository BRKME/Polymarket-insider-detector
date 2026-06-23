"""Если в рынке нет description — дотянуть его, иначе Grok судит вслепую."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_scanner import ensure_description


def test_uses_existing_description():
    m = {"description": "full rules here", "conditionId": "0x1"}
    assert ensure_description(m, fetch_fn=lambda cid: "SHOULD NOT CALL") == "full rules here"


def test_backfills_when_empty():
    m = {"description": "", "conditionId": "0x1"}
    out = ensure_description(m, fetch_fn=lambda cid: "fetched rules")
    assert out == "fetched rules"


def test_graceful_when_fetch_fails():
    m = {"description": "", "conditionId": "0x1"}
    def boom(cid): raise RuntimeError("api down")
    assert ensure_description(m, fetch_fn=boom) == ""   # не падает, пустая строка


def test_none_description():
    m = {"conditionId": "0x1"}
    assert ensure_description(m, fetch_fn=lambda cid: "r") == "r"
