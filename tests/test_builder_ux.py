from pathlib import Path

SRC = Path(__file__).parents[1] / "handlers" / "calculation.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_builder_has_single_message_renderer():
    assert "async def _edit_builder_message" in TEXT
    assert "builder_message_id" in TEXT
    assert "bot.edit_message_text" in TEXT


def test_window_flow_is_sash_then_opening_in_same_message():
    assert 'b:window:sashes:1' in TEXT
    assert 'b:window:sashes:2' in TEXT
    assert 'b:window:sashes:3' in TEXT
    assert 'b:window:config:' in TEXT
    assert 'await _show_window_configs(q, state, sash_count)' in TEXT


def test_back_returns_from_window_scheme_to_sashes_and_from_sashes_to_parent():
    assert 'screen == "window_configs"' in TEXT
    assert 'screen == "window_sashes"' in TEXT
    assert 'data.get("window_sashes_back") == "construction"' in TEXT
    assert 'return await show_construction(q, state)' in TEXT


def test_constructor_screens_do_not_send_new_messages():
    start = TEXT.index("# Редактирование параметров — компактные экраны")
    end = TEXT.index('@router.callback_query(F.data == "b:cart_checkout")', start)
    block = TEXT[start:end]
    assert "q.message.answer" not in block
    assert "_edit_builder_screen" in block


def test_service_dynamic_screens_use_single_message_renderer():
    service_src = (Path(__file__).parents[1] / "handlers" / "services.py").read_text(encoding="utf-8")
    assert "async def _render_service" in service_src
    assert "await _render_service(" in service_src
    for fn in ("async def _glass_screen", "async def _adj_screen"):
        block = service_src.split(fn, 1)[1].split("\n\n@router", 1)[0]
        assert "q.message.answer(" not in block


def test_glass_menu_filters_unpriced_combinations():
    service_src = (Path(__file__).parents[1] / "handlers" / "calculation.py").read_text(encoding="utf-8")
    assert "def _available_glasses" in service_src
    assert "get_window_price" in service_src
    assert "get_door_price" in service_src
