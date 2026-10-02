from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN_MENU_TEXT = (
    "🏠 <b>Главное меню</b>\n\n"
    "Рассчитайте ориентировочную стоимость, а если цена подходит — закажите замер."
)

MAIN_MENU_BUTTONS: tuple[tuple[str, str], ...] = (
    ("🧮 Рассчитать стоимость", "calc:start"),
    ("📏 Заказать замер", "calc:measure"),
    ("🛒 Мой расчёт", "calc:cart_menu"),
    ("📋 Мои заявки", "nav:history"),
    ("💬 Связаться с менеджером", "manager"),
    ("🔧 Сервис и ремонт", "svc:menu"),
    ("ℹ️ Как это работает", "help"),
)


def main_menu(is_manager: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = list(MAIN_MENU_BUTTONS)
    if is_manager:
        buttons.append(("📋 Заявки менеджера", "mgr:menu"))
    for text, callback_data in buttons:
        builder.button(text=text, callback_data=callback_data)
    builder.adjust(2)
    return builder.as_markup()
