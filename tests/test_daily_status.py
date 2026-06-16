"""Тесты daily_status.py — дневной информационный статус Polymarket.

Ключевая идея (оператор): позиции НЕ бинарны — NO/YES торгуются непрерывно,
их можно продать (зафиксировать) или докупить при движении цены, не дожидаясь
резолва. Статус показывает живую P&L-картину с мягкими подсказками действий.

Формат: короткая шапка (позиций / суммарный нереал. P&L / в плюсе-минусе) +
детали ТОЛЬКО по двигавшимся заметно или близким к резолву. Подсказки —
наблюдения к решению оператора, не приказы.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_status import (
    position_action_hint, build_daily_status, MOVE_THRESHOLD_PCT,
)


class TestActionHint:
    def test_strong_profit_suggests_take(self):
        # NO вырос с 0.38 до 0.62 = +63% — можно фиксировать
        hint = position_action_hint(entry=0.38, current=0.62, ai_yes=0.18,
                                    horizon_days=200)
        assert hint is not None
        assert "фикс" in hint.lower() or "продать" in hint.lower()

    def test_drawdown_thesis_intact_suggests_add(self):
        # NO упал 0.50→0.30, но AI всё ещё считает YES маловероятным (тезис цел)
        hint = position_action_hint(entry=0.50, current=0.30, ai_yes=0.15,
                                    horizon_days=200)
        assert hint is not None
        assert "докуп" in hint.lower() or "усред" in hint.lower()

    def test_thesis_inverted_suggests_cut(self):
        # цена против нас И AI пересмотрел в сторону YES — тезис сломан
        hint = position_action_hint(entry=0.50, current=0.30, ai_yes=0.75,
                                    horizon_days=200)
        assert hint is not None
        assert "режь" in hint.lower() or "выход" in hint.lower() or "cut" in hint.lower()

    def test_near_resolution_flagged(self):
        hint = position_action_hint(entry=0.50, current=0.55, ai_yes=0.30,
                                    horizon_days=3)
        assert hint is not None
        assert "резолв" in hint.lower() or "скоро" in hint.lower()

    def test_quiet_position_no_hint(self):
        # почти не двигалась, далеко до резолва — подсказки нет
        hint = position_action_hint(entry=0.50, current=0.51, ai_yes=0.30,
                                    horizon_days=200)
        assert hint is None


class TestBuildStatus:
    def _rows(self):
        return [
            {"condition_id": "0x1", "question": "SpaceX $2T?", "status": "open",
             "entry_price_actual": 0.38, "no_price": 0.38, "stake_actual": 70,
             "ai_yes_estimate": 0.18, "horizon_days": 200},
            {"condition_id": "0x2", "question": "Iran deal?", "status": "open",
             "no_price": 0.44, "stake_actual": 50,
             "ai_yes_estimate": 0.25, "horizon_days": 49},
            {"condition_id": "0x3", "question": "Closed one", "status": "closed"},
        ]

    def _prices(self):
        return {"0x1": 0.62, "0x2": 0.46}    # 0x1 сильно вырос, 0x2 почти стоит

    def test_header_counts_open_only(self):
        msg = build_daily_status(self._rows(), price_fn=lambda c: self._prices().get(c), confirmed_only=False)
        assert "2" in msg                      # 2 открытых (closed не считается)

    def test_header_has_total_pnl(self):
        msg = build_daily_status(self._rows(), price_fn=lambda c: self._prices().get(c), confirmed_only=False)
        assert "P&L" in msg or "P/L" in msg or "итог" in msg.lower()

    def test_only_moved_positions_detailed(self):
        msg = build_daily_status(self._rows(), price_fn=lambda c: self._prices().get(c), confirmed_only=False)
        # 0x1 двигался сильно — показан; 0x2 почти стоит — не в деталях
        assert "SpaceX" in msg
        assert "Iran" not in msg

    def test_non_binary_note_present(self):
        msg = build_daily_status(self._rows(), price_fn=lambda c: self._prices().get(c), confirmed_only=False)
        # напоминание, что позиции можно продать/докупить
        assert "продать" in msg.lower() or "докуп" in msg.lower() or "не бинар" in msg.lower()

    def test_no_open_positions_graceful(self):
        msg = build_daily_status([{"condition_id": "0x3", "status": "closed"}],
                                 price_fn=lambda c: None)
        assert "0" in msg

    def test_price_fetch_fail_skips_position(self):
        # цена недоступна — позиция не роняет статус
        msg = build_daily_status(self._rows(), price_fn=lambda c: None, confirmed_only=False)
        assert msg  # не падает


class TestOnlyRealPositions:
    """Баг 15.06: статус показал −$114 при банке $120, считая P&L по 11 алертам,
    включая НЕ купленные. Журнал = лог алертов, не портфель. Считать P&L можно
    ТОЛЬКО по ончейн-подтверждённым позициям (fill_source=onchain + entry)."""

    def _mixed(self):
        return [
            # реальная позиция — ончейн-филл
            {"condition_id": "0xA", "question": "Real one", "status": "open",
             "fill_source": "onchain", "entry_price_actual": 0.40,
             "stake_actual": 40, "ai_yes_estimate": 0.18, "horizon_days": 100},
            # алерт без входа — НЕ должен считаться в P&L
            {"condition_id": "0xB", "question": "Just an alert", "status": "open",
             "no_price": 0.43, "ai_yes_estimate": 0.12, "horizon_days": 100},
        ]

    def test_pnl_only_from_onchain(self):
        msg = build_daily_status(self._mixed(),
                                 price_fn=lambda c: {"0xA": 0.50, "0xB": 0.01}.get(c),
                                 confirmed_only=True)
        # в портфеле 1 реальная позиция, не 2
        assert "Открыто: 1" in msg or "позиц" in msg.lower()
        # алерт 0xB (−98%) не попал в детали
        assert "Just an alert" not in msg

    def test_garbage_price_rejected(self):
        # цена 1¢ против входа 40¢ — мусор API, не котировка
        from daily_status import is_plausible_price
        assert is_plausible_price(entry=0.43, current=0.01) is False
        assert is_plausible_price(entry=0.40, current=0.50) is True
        assert is_plausible_price(entry=0.40, current=0.05) is False


class TestUIFormatting:
    """UI-доработки: умная обрезка по словам, 🟢/🔴 индикаторы, шапка с P&L
    впереди и базой. Формат, не логика P&L."""

    def test_smart_truncate_word_boundary(self):
        from daily_status import smart_truncate
        s = "US x Iran permanent peace deal by August 31, 2026"
        out = smart_truncate(s, 30)
        assert len(out) <= 31           # +символ многоточия
        assert "…" in out
        assert not out.replace("…", "").endswith(" ")  # не висит пробел
        # не рвёт посреди слова — последнее слово целое
        assert out.replace("…", "").strip().split()[-1] in s.split()

    def test_short_string_not_truncated(self):
        from daily_status import smart_truncate
        assert smart_truncate("Maduro", 30) == "Maduro"

    def test_profit_loss_markers(self):
        rows = [
            {"condition_id": "0xW", "question": "Winner", "status": "open",
             "fill_source": "onchain", "entry_price_actual": 0.40,
             "stake_actual": 40, "ai_yes_estimate": 0.18, "horizon_days": 100},
            {"condition_id": "0xL", "question": "Loser", "status": "open",
             "fill_source": "onchain", "entry_price_actual": 0.50,
             "stake_actual": 40, "ai_yes_estimate": 0.30, "horizon_days": 100},
        ]
        msg = build_daily_status(rows,
                                 price_fn=lambda c: {"0xW": 0.52, "0xL": 0.40}.get(c))
        assert "🟢" in msg              # прибыльная
        assert "🔴" in msg              # убыточная

    def test_header_pnl_first_with_base(self):
        rows = [{"condition_id": "0xW", "question": "W", "status": "open",
                 "fill_source": "onchain", "entry_price_actual": 0.40,
                 "stake_actual": 100, "ai_yes_estimate": 0.18, "horizon_days": 100}]
        msg = build_daily_status(rows, price_fn=lambda c: 0.50)
        # P&L с базой и процентом: +$X от $Y (+Z%)
        assert "от $" in msg
        assert "%" in msg
        # P&L раньше счётчика позиций в тексте
        assert msg.index("P&L") < msg.index("озиц")
