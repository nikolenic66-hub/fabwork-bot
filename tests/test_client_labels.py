from pathlib import Path

SRC = Path(__file__).parents[1] / "handlers" / "calculation.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_client_window_labels_are_human_readable():
    block = TEXT.split("WINDOW_CONFIG_FRIENDLY =", 1)[1].split("\n}\n", 1)[0]
    assert '"1 створка —' in block
    assert '"2 створки —' in block
    assert '"3 створки — Г | ПО | Г"' in block
    assert '"3 створки — ПО | Г | ПО"' in block
    assert "Средняя часть открывается и откидывается" in block
    assert "Обе крайние части открываются и откидываются" in block


def test_estimate_uses_client_friendly_cta():
    assert '📏 <b>Хотите узнать точную стоимость?</b>' in TEXT
    assert "Закажите замер" in TEXT
    assert "Монтаж 17%" in TEXT
    assert "Обычный замер — бесплатно" in TEXT
    assert "500 ₽ только для замера москитных сеток и стеклопакетов" in TEXT
    assert 'Замер: <b>500 ₽</b>' not in TEXT


def test_service_measurement_labels_are_correct():
    service_text = Path(__file__).parents[1].joinpath("handlers", "services.py").read_text(encoding="utf-8")
    assert "Бесплатный замер" in service_text
    assert "Замер москитных сеток — 500 ₽" in service_text
    assert "Замер — 500 ₽" in TEXT
    assert "Замер — 500 ₽" not in service_text


def test_builder_has_working_back_and_balcony_custom_size():
    assert '@router.callback_query(F.data == "b:back")' in TEXT
    assert 'F.data == "b:bal:custom"' in TEXT
    assert 'CalculationStates.EDIT_BAL_DOOR_W' in TEXT
    assert 'CalculationStates.EDIT_BAL_WIN_H' in TEXT
    assert '800, 900' not in TEXT  # custom size is entered by the customer, not hard-coded


def test_balcony_door_ui_has_opening_modes_and_fixed_mosquito_net():
    text = Path(__file__).parents[1].joinpath("handlers/calculation.py").read_text(encoding="utf-8")
    assert '"Поворотная дверь", "b:set:baldoor:turn"' in text
    assert '"Поворотно-откидная дверь", "b:set:baldoor:tilt_turn"' in text
    assert 'b:set:baldoor:mos' not in text.split('if screen == "door":', 1)[1].split('if screen == "bal_size":', 1)[0]
    assert 'Дверная москитная сетка — 5 000 ₽' not in text


def test_balcony_door_screen_contains_only_opening_modes_and_mosquito():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    assert '("Поворотная дверь", "b:set:baldoor:turn")' in text
    assert '("Поворотно-откидная дверь", "b:set:baldoor:tilt_turn")' in text
    assert '+1 000 ₽' not in text.split('if screen == "door":', 1)[1].split('if screen == "bal_size":', 1)[0]
    assert 'rows.append(("Одностворчатая дверь", "b:set:dtype:single"))' not in text
    assert 'rows.append(("Стандартная дверь", "b:set:dsash:T"))' not in text


def test_balcony_extras_has_separate_sill_sides():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    assert 'Подоконник со стороны балкона' in text
    assert 'Подоконник со стороны квартиры' in text
    assert 'b:set:sillside:balcony' in text
    assert 'b:set:sillside:apartment' in text
    assert 'b:set:silltype:{side}:pvc' in text
    assert 'b:set:silltype:{side}:danke' in text
    assert 'b:set:sdepth:{side}:300' in text


def test_balcony_door_and_door_mosquito_return_to_builder():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    block = text.split('async def set_balcony_door_option', 1)[1].split('@router.callback_query', 1)[0]
    assert 'await show_builder(q, state, reset_history=True)' in block
    assert 'await _render_screen(q, state, "door", push=False)' not in block
    assert 'await _render_screen(q, state, "extras", push=False)' not in block


def test_balcony_extras_label_door_mosquito_separately():
    text = open("handlers/calculation.py", encoding="utf-8").read()
    extras = text.split('if screen == "extras":', 1)[1].split('if screen == "silltype":', 1)[0]
    assert 'Дверная москитная сетка:' in extras
