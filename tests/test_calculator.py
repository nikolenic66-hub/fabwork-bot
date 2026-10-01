from decimal import Decimal
from calculator import calculator, PricingError, measurement_fee_for_cart
from models import CalculationConfig
from pricing.price_list import (
    calculate_installation,
    get_balcony_block_parts,
    get_balcony_glazing_package,
    get_door_price,
    get_ebb_price,
    get_sill_price,
    get_window_price,
    validate_size,
    service_adjust,
    service_glass32,
    service_glass_replace,
    service_measure,
    service_mosquito_measure,
    service_seal,
    SERVICE_PRICES,
)


def base(**kw):
    d = dict(
        construction_type="window", profile="58", width_mm=900, height_mm=1400,
        sash_count=1, glass="24", opening="turn", extras={"sash_configuration": "turn"},
    )
    d.update(kw)
    return CalculationConfig(**d)


def test_window_price():
    e = calculator.calculate(base(glass="32", opening="tilt_turn", extras={"sash_configuration": "tilt_turn"}))
    assert e.subtotal == Decimal("11960.00")


def test_installation_exactly_once():
    e = calculator.calculate(base(glass="32", opening="tilt_turn", extras={"sash_configuration": "tilt_turn"}))
    assert e.installation == money_17(e.subtotal)
    assert e.total == e.subtotal + e.installation


def money_17(s):
    return calculate_installation(s)


def test_sill_is_per_meter():
    assert get_sill_price("pvc", 300, 1200) == Decimal("1440.00")


def test_ebb_is_per_meter():
    assert get_ebb_price(150, 1200) == Decimal("780.00")


def test_i_coating():
    e = calculator.calculate(base(glass="32_i", opening="tilt_turn", extras={"sash_configuration": "tilt_turn"}))
    assert e.subtotal == Decimal("13960.00")


def test_door():
    p = get_door_price("single", "T", "frame", "single", "push", "32")
    assert p == Decimal("23800.00")  # 22000+1800


def test_balcony_block_58_near_29k():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony", profile="58", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=600, window_height_mm=1400,
        window_configuration="tilt_turn",
        sill_type="pvc", sill_depth_mm=300, sill_length_mm=600,
        sill2_type="pvc", sill2_depth_mm=300, sill2_length_mm=700,
    ))
    # materials should land total near 29000
    assert Decimal("28000") <= e.total <= Decimal("30000")
    names = [i.name for i in e.items]
    assert sum(1 for n in names if "Подоконник" in n) == 2


def test_balcony_block_70_near_40k():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony", profile="70", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=600, window_height_mm=1400,
        window_configuration="tilt_turn",
        sill_type="pvc", sill_depth_mm=300, sill_length_mm=600,
        sill2_type="pvc", sill2_depth_mm=300, sill2_length_mm=700,
    ))
    assert Decimal("33000") <= e.total <= Decimal("35000")


def test_balcony_door_modes_apply_1000_before_17_percent_discount():
    common = dict(
        construction_type="balcony", profile="58", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=800, window_height_mm=1400,
        window_configuration="tilt_turn",
        sill_type="pvc", sill_depth_mm=300, sill_length_mm=800,
        sill2_type="pvc", sill2_depth_mm=300, sill2_length_mm=700,
    )
    turn = calculator.calculate(CalculationConfig(**common, door_opening_mode="turn"))
    tilt = calculator.calculate(CalculationConfig(**common, door_opening_mode="tilt_turn"))
    assert tilt.total - turn.total == Decimal("971.10")
    assert any(i.name == "Скидка 17%" for i in tilt.items)


def test_frame_slab_58():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony_glazing", profile="58", scheme_key="frame_slab",
        width_mm=3000, height_mm=1300,
    ))
    assert e.subtotal == Decimal("80000.00")


def test_frame_58():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony_glazing", profile="58", scheme_key="frame",
    ))
    assert e.subtotal == Decimal("80000.00")


def test_frame_slab_58_uses_frame_range_until_separate_price_is_set():
    from pricing.price_list import get_balcony_glazing_package
    low, high = get_balcony_glazing_package("frame_slab", "58")
    assert (low, high) == (Decimal("75000.00"), Decimal("85000.00"))


def test_validate_sash():
    assert validate_size(1200, 1400, "window", 1, "tilt_turn") is not None
    assert validate_size(900, 1400, "window", 1, "tilt_turn") is None


def test_triple_window_g_po_g():
    e = calculator.calculate(base(
        width_mm=1800, height_mm=1400, sash_count=3,
        opening="fixed_tilt_turn_fixed",
        extras={"sash_configuration": "fixed_tilt_turn_fixed"},
        glass="32",
    ))
    assert e.subtotal == Decimal("23120.00")
    assert e.total == Decimal("27050.40")


def test_triple_window_po_g_po():
    e = calculator.calculate(base(
        width_mm=2100, height_mm=1400, sash_count=3,
        opening="tilt_turn_fixed_tilt_turn",
        extras={"sash_configuration": "tilt_turn_fixed_tilt_turn"},
        glass="32",
    ))
    assert e.subtotal == Decimal("26840.00")


def test_glass_unit_prices_and_i_surcharge():
    plain = calculator.calculate(CalculationConfig(construction_type="glass_unit", width_mm=800, height_mm=1400, glass="24"))
    warm = calculator.calculate(CalculationConfig(construction_type="glass_unit", width_mm=800, height_mm=1400, glass="32"))
    i = calculator.calculate(CalculationConfig(construction_type="glass_unit", width_mm=800, height_mm=1400, glass="32_i"))
    assert plain.total == Decimal("7160.00")
    assert warm.total == Decimal("9400.00")
    assert i.total == Decimal("11400.00")
    assert i.installation == Decimal("1000.00")


def test_i_surcharge_is_exactly_2000_and_not_in_installation_base():
    plain = calculator.calculate(base(glass="32", opening="tilt_turn", extras={"sash_configuration": "tilt_turn"}, width_mm=900, height_mm=1400))
    i = calculator.calculate(base(glass="32_i", opening="tilt_turn", extras={"sash_configuration": "tilt_turn"}, width_mm=900, height_mm=1400))
    assert i.subtotal - plain.subtotal == Decimal("2000.00")
    assert i.installation == plain.installation


def test_balcony_glazing_returns_orientir_range():
    from pricing.price_list import get_balcony_glazing_package
    low, high = get_balcony_glazing_package("frame_slab", "58")
    assert low == Decimal("75000.00")
    assert high == Decimal("85000.00")


def test_service_prices():
    assert service_measure() == Decimal("0.00")
    total, items = service_glass32(1, True, True)
    assert total == Decimal("9000.00")  # 7500+500+1000
    total24, items24 = service_glass_replace("24", 1, True, True)
    assert total24 == Decimal("7000.00")  # 5500+500+1000
    mosquito_total, mosquito_items = service_mosquito_measure()
    assert mosquito_total == Decimal("500.00")
    assert mosquito_items == [("Замер москитных сеток", Decimal("500.00"))]
    total, _ = service_adjust(2, 1)
    assert total == Decimal("2100.00")  # 1000+600+500
    total, _ = service_seal(Decimal("4"))
    assert total == Decimal("2000.00")  # 1000+1000


def test_tilt_turn_fixed_same_as_g_po():
    a = get_window_price(2, "fixed_tilt_turn", "58", "32", 1300, 1400)
    b = get_window_price(2, "tilt_turn_fixed", "58", "32", 1300, 1400)
    assert a == b


def test_balcony_block_accepts_custom_window_800x900():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony", profile="58", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=800, window_height_mm=900,
        window_configuration="tilt_turn",
        sill_type="pvc", sill_depth_mm=300, sill_length_mm=800,
        sill2_type="pvc", sill2_depth_mm=300, sill2_length_mm=700,
    ))
    assert e.total > Decimal("0")
    assert any("800×900" in i.name for i in e.items)


def test_delivery_is_separate_from_installation_base():
    plain = calculator.calculate(base())
    delivered = calculator.calculate(base(delivery="city"))
    assert delivered.subtotal == plain.subtotal + Decimal("2500.00")
    assert delivered.installation == plain.installation
    assert delivered.total == plain.total + Decimal("2500.00")


def test_balcony_no_sill_does_not_charge_sills():
    e = calculator.calculate(CalculationConfig(
        construction_type="balcony", profile="58", glass="32",
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push",
        door_width_mm=700, door_height_mm=2100,
        window_width_mm=800, window_height_mm=900,
        window_configuration="tilt_turn",
        sill_type=None, sill2_type=None,
    ))
    assert not any("Подоконник" in item.name for item in e.items)


def test_nonstandard_size_is_validated():
    try:
        calculator.calculate(CalculationConfig(
            construction_type="nonstandard", profile="70", width_mm=100, height_mm=100,
            glass="32", scheme_key="transom_v", sash_count=2,
            extras={"sash_configuration": "fixed_tilt_turn"},
        ))
    except PricingError:
        return
    raise AssertionError("Недопустимый размер другой конструкции не был отклонён")


def test_door_i_surcharge_is_not_in_installation_base():
    plain = calculator.calculate(CalculationConfig(
        construction_type="door", profile="70", width_mm=900, height_mm=2100,
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push", glass="32",
    ))
    i = calculator.calculate(CalculationConfig(
        construction_type="door", profile="70", width_mm=900, height_mm=2100,
        door_type="single", door_sash="T", door_threshold="frame",
        door_lock="single", door_fittings="push", glass="32_i",
    ))
    assert i.subtotal - plain.subtotal == Decimal("2000.00")
    assert i.installation == plain.installation


def test_measurement_fee_is_only_for_glass_units_or_mosquito_nets():
    assert measurement_fee_for_cart([]) == Decimal("0.00")
    assert measurement_fee_for_cart([{"product": {"construction_type": "window", "mosquito": False}}]) == Decimal("0.00")
    assert measurement_fee_for_cart([{"product": {"construction_type": "window", "mosquito": True}}]) == Decimal("500.00")
    assert measurement_fee_for_cart([{"product": {"construction_type": "glass_unit"}}]) == Decimal("500.00")
