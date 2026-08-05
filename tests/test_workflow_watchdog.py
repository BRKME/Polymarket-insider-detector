"""Сторож воркфлоу: следит за самими прогонами и кричит при красных.

Дефект, который он закрывает (найден 05.08.2026): daily_status падал 5 прогонов
подряд, узнали случайно — режим отказа был неотличим от «нет сигналов», потому
что вся обратная связь идёт через тот же Telegram, который и ломается.
Сторож молчит, когда всё зелено, иначе сам станет шумом."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_watchdog import find_failures, build_report


def _run(name, concl, when="2026-08-05T08:00:00Z"):
    return {"name": name, "conclusion": concl, "created_at": when,
            "html_url": "https://github.com/x/y/actions/runs/1"}


def test_finds_failed_runs():
    runs = [_run("Daily Status", "failure"), _run("Tests", "success")]
    fails = find_failures(runs)
    assert len(fails) == 1
    assert fails[0]["name"] == "Daily Status"


def test_ignores_success_and_skipped():
    runs = [_run("A", "success"), _run("B", "skipped"), _run("C", None)]
    assert find_failures(runs) == []


def test_groups_repeated_failures():
    # один воркфлоу упал трижды — в отчёте одна строка со счётчиком
    runs = [_run("Daily Status", "failure"), _run("Daily Status", "failure"),
            _run("Daily Status", "failure")]
    rep = build_report(find_failures(runs))
    assert rep is not None
    assert rep.count("Daily Status") == 1
    assert "3" in rep


def test_silent_when_all_green():
    assert build_report([]) is None          # молчим, если чинить нечего


def test_report_names_the_workflow():
    rep = build_report(find_failures([_run("Event Scanner", "failure")]))
    assert "Event Scanner" in rep
