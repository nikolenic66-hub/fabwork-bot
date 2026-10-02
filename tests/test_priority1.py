from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path

from calculator import measurement_fee_for_cart, split_html_message
from storage.db import Database


ROOT = Path(__file__).parents[1]


def test_html_splitter_never_breaks_tags():
    text = "<b>" + ("x" * 9000) + "</b>"
    chunks = split_html_message(text)

    assert len(chunks) >= 3
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert all(chunk.count("<b>") == chunk.count("</b>") == 1 for chunk in chunks)
    assert "".join(re.sub(r"</?b>", "", chunk) for chunk in chunks) == "x" * 9000


def test_html_splitter_preserves_nested_formatting():
    text = "<b><i>" + ("abc" * 3000) + "</i></b>"
    chunks = split_html_message(text)

    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert all(chunk.startswith("<b><i>") for chunk in chunks)
    assert all(chunk.endswith("</i></b>") for chunk in chunks)


def test_measurement_fee_only_for_standalone_special_items():
    assert measurement_fee_for_cart([
        {"product": {"construction_type": "window"}}
    ]) == 0
    assert measurement_fee_for_cart([
        {"product": {"construction_type": "balcony", "door_mosquito": True}}
    ]) == 0
    assert measurement_fee_for_cart([
        {"product": {"construction_type": "mosquito_net"}}
    ]) == 500
    assert measurement_fee_for_cart([
        {"product": {"construction_type": "glass_unit"}}
    ]) == 500


def test_request_deduplication_is_atomic_under_concurrency(tmp_path):
    path = str(tmp_path / "race.db")
    Database(path)

    def create_one(_: int):
        db = Database(path)
        return db.save_request_atomic(
            100, "Иван", "+79990000000", "{}", "1000", dedupe_key="same-key"
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(create_one, range(20)))

    assert sum(created for _, created in results) == 1
    assert len({request_id for request_id, _ in results}) == 1


def test_database_has_atomic_unique_dedupe_index(tmp_path):
    db = Database(str(tmp_path / "index.db"))
    with __import__("sqlite3").connect(db.path) as conn:
        indexes = conn.execute("PRAGMA index_list(requests)").fetchall()
    names = {row[1] for row in indexes}
    assert "idx_requests_user_dedupe_unique" in names


def test_single_main_menu_source_contains_all_seven_actions():
    navigation = (ROOT / "handlers" / "navigation.py").read_text(encoding="utf-8")
    assert navigation.count("MAIN_MENU_BUTTONS: tuple") == 1
    for callback in (
        "calc:start", "calc:measure", "calc:cart_menu", "nav:history",
        "manager", "svc:menu", "help",
    ):
        assert callback in navigation


def test_calculation_uses_shared_main_menu_and_handles_not_modified():
    text = (ROOT / "handlers" / "calculation.py").read_text(encoding="utf-8")
    assert "from handlers.navigation import MAIN_MENU_TEXT, main_menu" in text
    assert '"message is not modified"' in text
    assert 'log.exception("Unexpected builder message edit failure")' in text


def test_reply_keyboard_returns_to_full_inline_main_menu():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    start = text.index("async def _show_main_menu_after_reply")
    end = text.index("@router.message(CommandStart())", start)
    block = text[start:end]
    assert "reply_markup=main_menu()" in block
    assert "ReplyKeyboardRemove()" not in block
    assert "sent.edit_reply_markup" not in block
    assert 'await m.answer("Выберите действие:"' not in text


def test_measurement_manager_text_receives_real_fee():
    text = (ROOT / "handlers" / "calculation.py").read_text(encoding="utf-8")
    assert "def _manager_measure_text(request_id: int, data: dict, cart: list[dict], total: Decimal, user_id: int, measure_fee: Decimal)" in text
    assert "_manager_measure_text(request_id, data, cart, total, user_id, measure_fee)" in text


def test_measure_start_uses_same_fee_function_as_final_request():
    text = (ROOT / "handlers" / "calculation.py").read_text(encoding="utf-8")
    start = text.index("async def measure_start")
    end = text.index("async def measure_name", start)
    block = text[start:end]
    assert "measurement_fee_for_cart(cart)" in block


def test_manager_contact_form_has_source_and_telegram_profile():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "ManagerStates.NAME" in text
    assert "ManagerStates.PHONE" in text
    assert '"type": "manager_contact"' in text
    assert '"telegram_profile": profile' in text
    assert "Открыть профиль" in text
    assert "Кнопка «Связаться с менеджером»" in text


def test_db_failure_is_not_reported_as_success():
    calc = (ROOT / "handlers" / "calculation.py").read_text(encoding="utf-8")
    services = (ROOT / "handlers" / "services.py").read_text(encoding="utf-8")
    assert "Не удалось сохранить заявку" in calc
    assert "Не удалось сохранить заявку на сервис" in services
    assert 'log.exception("Failed to save order request")' in calc
    assert 'log.exception("Failed to save service request")' in services


def test_manager_notification_failures_are_logged():
    calc = (ROOT / "handlers" / "calculation.py").read_text(encoding="utf-8")
    services = (ROOT / "handlers" / "services.py").read_text(encoding="utf-8")
    assert "async def _notify_manager" in calc
    assert "return False" in calc
    assert "Failed to notify manager" in calc
    assert "Failed to notify manager about service request" in services


def test_entry_door_has_exactly_six_standard_sizes_and_prices():
    from decimal import Decimal
    from calculator import calculator
    from models import CalculationConfig
    from pricing.price_list import ENTRY_DOOR_PRESETS

    assert tuple(ENTRY_DOOR_PRESETS) == (
        (900, 2100), (1000, 2100), (1100, 2100),
        (1300, 2100), (1400, 2100), (1600, 2100),
    )
    for (width, height), expected in ENTRY_DOOR_PRESETS.items():
        estimate = calculator.calculate(CalculationConfig(
            construction_type="door", profile="70", width_mm=width, height_mm=height,
            door_type="single", opening="single", door_sash="T",
            door_threshold="frame", door_lock="single", door_fittings="push", glass="32",
        ))
        assert estimate.total == expected


def test_entry_door_custom_size_is_not_offered():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    block = text.split('if screen == "size":', 1)[1].split('if screen == "glass":', 1)[0]
    assert 'if ct != "door":' in block


def test_separate_glass_details_use_fixed_installation_label():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    assert 'Монтаж стеклопакета: <b>{fmt_money(e.installation)}</b>' in text
    assert 'Процентный монтаж 17% к отдельному стеклопакету не применяется.' in text


def test_balcony_two_section_window_uses_two_sash_validation():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    assert 'sash_count = 2 if cfg == "fixed_tilt_turn" else 1' in text
