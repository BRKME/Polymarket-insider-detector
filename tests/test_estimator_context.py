"""
Tests for passing market description + resolution date into the estimator,
so Grok can see resolution rules (the source of linked/grouped-market traps)
instead of guessing from the question title alone.

Run: python -m pytest tests/test_estimator_context.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import event_scanner as es


def _market(question, yes, no, description="", end_date="", liq=50_000,
            hours_out=240, condition_id="0xabc"):
    from datetime import datetime, timezone, timedelta
    end = end_date or (datetime.now(timezone.utc)
                       + timedelta(hours=hours_out)).isoformat()
    return {
        "question": question,
        "description": description,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{yes}", "{no}"]',
        "liquidity": liq,
        "endDate": end,
        "conditionId": condition_id,
    }


class TestEvaluatePassesContext:
    def test_estimator_receives_description_and_date(self):
        seen = {}

        def spy(question, description=None, end_date=None):
            seen["question"] = question
            seen["description"] = description
            seen["end_date"] = end_date
            return {"prob": 0.20, "conf": "high", "why": "x"}

        m = _market("Will X happen?", 0.80, 0.20,
                    description="Resolves YES if X occurs before the deadline.",
                    end_date="2026-12-31T00:00:00Z")
        c = es.evaluate(m, spy)
        assert c is not None
        assert seen["question"] == "Will X happen?"
        assert "Resolves YES" in seen["description"]
        assert seen["end_date"].startswith("2026-12-31")

    def test_legacy_single_arg_estimator_still_works(self):
        # An old-style fn that only accepts (question) must not break.
        def legacy(question):
            return {"prob": 0.20, "conf": "high", "why": "x"}

        m = _market("Will Y happen?", 0.80, 0.20)
        c = es.evaluate(m, legacy)
        assert c is not None
        assert c.ai_yes_estimate == 0.20


class TestEstimatorPromptBuild:
    def test_prompt_includes_description_and_resolution_date(self):
        from ai_context import _build_estimator_prompt
        p = _build_estimator_prompt(
            "Will X happen?",
            description="Resolves YES only if the official source confirms X.",
            end_date="2026-12-31T00:00:00Z",
        )
        assert "Will X happen?" in p
        assert "official source" in p
        assert "2026-12-31" in p

    def test_prompt_without_context_is_still_valid(self):
        from ai_context import _build_estimator_prompt
        p = _build_estimator_prompt("Will X happen?")
        assert "Will X happen?" in p
        # no crash, no None interpolation
        assert "None" not in p
