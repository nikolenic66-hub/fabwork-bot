import json
from decimal import Decimal
from pathlib import Path

from calculator import calculator
from models import CalculationConfig
from storage.db import Database


def test_draft_persists_cart(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    payload = {"cart": [{"title": "Окно 900×1400", "total": "15800.00"}], "construction_type": "window"}
    db.save_draft(7, json.dumps(payload, ensure_ascii=False))
    assert json.loads(db.load_draft(7))["cart"][0]["title"] == "Окно 900×1400"
    db.clear_draft(7)
    assert db.load_draft(7) is None


def test_duplicate_request_is_detected(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    rid = db.save_request(7, "Иван", "+79990000000", "{}", "16300", dedupe_key="abc")
    assert db.recent_duplicate(7, "abc", seconds=900) == rid
    assert db.recent_duplicate(8, "abc", seconds=900) is None


def _balcony(window_w, window_h):
    return calculator.calculate(CalculationConfig(
        construction_type="balcony", profile="58", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=window_w, window_height_mm=window_h,
        window_configuration="tilt_turn",
        sill_type="pvc", sill_depth_mm=300, sill_length_mm=window_w,
        sill2_type="pvc", sill2_depth_mm=300, sill2_length_mm=700,
    ))


def test_custom_balcony_window_size_changes_price_and_label():
    standard = _balcony(600, 1400)
    custom = _balcony(800, 900)
    assert custom.total != standard.total
    assert any("800×900" in item.name for item in custom.items)
    assert any("Соединительный профиль" in item.name for item in custom.items)


def test_no_slopes_or_old_connector_label_in_calculator_source():
    text = Path(__file__).parents[1].joinpath("calculator.py").read_text(encoding="utf-8")
    assert "slopes" not in text.lower()
    assert "лапша" not in text.lower()


def test_regular_measurement_has_no_fee_in_request_flow():
    text = Path(__file__).parents[1].joinpath("handlers/calculation.py").read_text(encoding="utf-8")
    assert 'measure_fee = measurement_fee_for_cart(cart)' in text
    assert 'measure_label = fmt_money(measure_fee) if measure_fee else "бесплатно"' in text


def test_mosquito_measurement_is_500_in_calculation_logic():
    from calculator import measurement_fee_for_cart
    assert measurement_fee_for_cart([{"product": {"construction_type": "window", "mosquito": True}}]) == Decimal("500.00")


def test_special_measurement_fee_is_500():
    from pricing.price_list import service_mosquito_measure, service_glass32
    assert service_mosquito_measure()[0] == Decimal("500.00")
    assert service_glass32(1, True, False)[0] == Decimal("8000.00")


def test_history_marks_free_measurement_as_free():
    text = Path(__file__).parents[1].joinpath("handlers", "calculation.py").read_text(encoding="utf-8")
    assert 'fee_label = "бесплатно" if fee == 0 else fmt_money(fee)' in text


def test_service_requests_have_dedupe_protection_and_escaped_manager_fields():
    text = Path(__file__).parents[1].joinpath("handlers", "services.py").read_text(encoding="utf-8")
    assert "recent_duplicate" in text
    assert 'safe_name = escape' in text
    assert 'safe_phone = escape' in text


def test_manager_message_is_split_under_telegram_limit():
    from calculator import split_html_message
    chunks = split_html_message("\n".join(["<b>строка</b>"] * 900))
    assert len(chunks) > 1
    assert all(len(chunk) <= 4000 for chunk in chunks)


def test_measurement_fee_is_added_to_measure_request_total_in_source():
    text = Path(__file__).parents[1].joinpath("handlers/calculation.py").read_text(encoding="utf-8")
    assert "total = product_total + measure_fee" in text


def test_service_duplicate_is_not_resent_to_manager_in_source():
    text = Path(__file__).parents[1].joinpath("handlers/services.py").read_text(encoding="utf-8")
    assert "is_new_request = False" in text
    assert "if cid and is_new_request:" in text
