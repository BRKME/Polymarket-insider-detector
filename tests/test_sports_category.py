# -*- coding: utf-8 -*-
"""Баг 15.07: рынки World Cup классифицировались как 'other' — категорийный
кап по спорту не мог сработать, три коррелированные ставки на один матч
прошли без предупреждения. Чиним: категория sports, приоритетнее остальных
(иначе 'Russia eliminated in the World Cup' утёк бы в geopolitics), плюс
классификация по event_slug (fifwc-, epl-, ...) — надёжнее ключевых слов.
"""
import category_exposure as cx


def test_world_cup_question_is_sports():
    assert cx.classify("Will Spain be eliminated in the Semifinals "
                       "of the World Cup?") == "sports"


def test_halftime_question_is_sports():
    assert cx.classify("France leading at halftime?") == "sports"


def test_fifwc_slug_wins_even_with_blank_question():
    assert cx.classify("", slug="fifwc-par-fra-2026-07-04-halftime-result") \
        == "sports"


def test_epl_slug_is_sports():
    assert cx.classify("Will Arsenal FC win on 2026-05-02?",
                       slug="epl-ars-ful-2026-05-02") == "sports"


def test_esports_msi_is_sports():
    assert cx.classify("Will a team from LCK (South Korea) win MSI 2026?") \
        == "sports"


def test_sports_beats_country_keyword():
    # 'world cup' должен победить 'russia' из geopolitics
    assert cx.classify("Will Russia be eliminated in the Round of 16 "
                       "of the World Cup?") == "sports"


def test_geopolitics_untouched():
    assert cx.classify("Will Russia capture Kostyantynivka by "
                       "December 31, 2026?") == "geopolitics"


def test_macro_untouched():
    assert cx.classify("Fed rate hike in 2026?") == "macro"


def test_exposure_uses_slug_from_journal_row():
    rows = [{"question": "France leading at halftime?",
             "event_slug": "fifwc-par-fra-2026-07-04-halftime-result",
             "status": "open", "stake_actual": 15.0}]
    exp = cx.exposure_by_category(rows)
    assert exp.get("sports") == 15.0


def test_stored_other_category_is_reclassified():
    """В журнале уже записано category='other' (до фикса) — не верим ему."""
    rows = [{"question": "France leading at halftime?",
             "event_slug": "fifwc-par-fra-2026-07-04-halftime-result",
             "category": "other", "status": "open", "stake_actual": 15.0}]
    exp = cx.exposure_by_category(rows)
    assert exp.get("sports") == 15.0


def test_stored_real_category_is_trusted():
    rows = [{"question": "Some vague market", "category": "crypto",
             "status": "open", "stake_actual": 10.0}]
    exp = cx.exposure_by_category(rows)
    assert exp.get("crypto") == 10.0


def test_candidate_rows_without_fill_do_not_count_as_exposure():
    """~50 «open»-строк журнала — кандидаты сканера без ончейн-филла.
    С банком $200 фолбэк на середину диапазона ($42.5/строку) ставил ВСЕ
    категории над капом и спамил бы предупреждением каждые 2ч. Деньги в
    риске = только подтверждённые ставки (stake_actual от fill_matcher)."""
    rows = [
        {"question": "France leading at halftime?",
         "event_slug": "fifwc-par-fra-2026-07-04", "status": "open",
         "stake_actual": 15.0},
        {"question": "Candidate without fill", "status": "open"},
        {"question": "Another candidate", "status": "open",
         "stake_actual": None},
    ]
    exp = cx.exposure_by_category(rows)
    assert exp == {"sports": 15.0}
