from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from decimal import Decimal
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from calculator import calculator, PricingError, measurement_fee_for_cart, split_html_message
from models import CalculationConfig
from pricing.price_list import (
    BALCONY_GLAZING_TYPES,
    DOOR_FITTINGS,
    DOOR_LOCK,
    DOOR_SASH,
    DOOR_THRESHOLD,
    GLAZING,
    NONSTANDARD_SCHEMES,
    PROFILES,
    WINDOW_CONFIGS,
    WINDOW_SCHEMES,
    validate_size,
    get_window_price,
    get_balcony_glazing_package,
    GLASS_PRICE_PER_M2,
    get_door_price,
    BALCONY_DOOR_MOSQUITO_NET,
)
from states import CalculationStates
from storage.db import Database

router = Router(name="calculation")

WINDOW_SIZE_PRESETS = {
    1: [(600, 1200), (700, 1200), (800, 1200), (900, 1200), (900, 1400), (1000, 1400)],
    2: [(1000, 1200), (1200, 1200), (1200, 1400), (1300, 1400), (1400, 1400), (1500, 1400)],
    3: [(1800, 1200), (1800, 1400), (2000, 1400), (2100, 1400), (2400, 1400)],
}
DOOR_SIZE_PRESETS = [(700, 2000), (700, 2100), (800, 2100), (900, 2100)]
BALCONY_PRESETS = [
    (700, 2100, 800, 1300),
    (700, 2100, 800, 1400),
    (700, 2100, 900, 1400),
    (800, 2100, 800, 1400),
    (800, 2100, 900, 1400),
    (900, 2100, 900, 1400),
]
STATUS_LABELS = {"new": "🆕 Новая", "measurer": "📏 Замер", "quote": "📋 КП", "done": "✅ Закрыта"}
MAX_CART_ITEMS = 10

FRIENDLY_GLASS = {
    "24": "СП 24 мм",
    "32": "СП 32 мм",
    "24_i": "СП 24 мм + i (2 стороны, +2 000 ₽)",
    "32_i": "СП 32 мм + i (2 стороны, +2 000 ₽)",
}
FRIENDLY_DOOR_UI = {"single": "Одностворчатая дверь", "double": "Двустворчатая дверь"}
FRIENDLY_SASH_UI = {"T": "Стандартная дверь", "Z": "Усиленная дверь"}
FRIENDLY_THRESHOLD_UI = {"alu_low": "Низкий порог", "frame": "Стандартный порог"}
FRIENDLY_LOCK_UI = {"single": "Обычный замок", "multi": "Многозапорный замок"}
FRIENDLY_FITTINGS_UI = {"push": "Ручка", "handles_closer": "Ручка и доводчик"}

WINDOW_CONFIG_FRIENDLY = {
    "fixed": ("1 створка — глухое", "Не открывается"),
    "turn": ("1 створка — открывается", "Открывается в сторону"),
    "tilt_turn": ("1 створка — ПО", "Открывается в сторону и откидывается сверху"),
    "fixed_fixed": ("2 створки — Г | Г", "Обе части не открываются"),
    "fixed_turn": ("2 створки — Г | П", "Первая глухая, вторая открывается"),
    "fixed_tilt_turn": ("2 створки — Г | ПО", "Первая глухая, вторая открывается и откидывается"),
    "tilt_turn_fixed": ("2 створки — ПО | Г", "Первая открывается и откидывается, вторая глухая"),
    "turn_turn": ("2 створки — П | П", "Обе части открываются"),
    "fixed_fixed_fixed": ("3 створки — Г | Г | Г", "Все три части не открываются"),
    "fixed_tilt_turn_fixed": ("3 створки — Г | ПО | Г", "Средняя часть открывается и откидывается"),
    "tilt_turn_fixed_tilt_turn": ("3 створки — ПО | Г | ПО", "Обе крайние части открываются и откидываются"),
}


def db() -> Database:
    return Database(os.getenv("DATABASE_PATH", "/data/bot.db"))


def kb(rows: list[tuple[str, str]], cols: int = 1):
    b = InlineKeyboardBuilder()
    for text, data in rows:
        b.button(text=text, callback_data=data)
    b.adjust(cols)
    return b.as_markup()


def fmt_money(v: Decimal | str | int | float) -> str:
    try:
        d = Decimal(str(v))
    except Exception:
        return f"{v} ₽"
    s = f"{d:,.2f}".replace(",", "\u00a0")
    if s.endswith(",00"):
        s = s[:-3]
    return s + " ₽"


def reply_nav_keyboard(with_contact: bool = False) -> ReplyKeyboardMarkup:
    rows = []
    if with_contact:
        rows.append([KeyboardButton(text="📱 Отправить номер", request_contact=True)])
    rows.append([KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def reply_cancel_only() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _is_cancel_text(text: str | None) -> bool:
    return bool(text and text.strip().lower() in {"❌ отмена", "отмена", "❌", "cancel"})


def _is_menu_text(text: str | None) -> bool:
    return bool(text and text.strip().lower() in {"🏠 меню", "меню", "home", "в меню"})


def _is_back_text(text: str | None) -> bool:
    return bool(text and text.strip().lower() in {"⬅️ назад", "назад", "back"})


async def _persist(state: FSMContext, user_id: int) -> None:
    data = await state.get_data()
    payload = dict(data)
    # FSM-only transient values не нужны после перезапуска.
    payload.pop("_tmp_w", None)
    db().save_draft(user_id, json.dumps(payload, ensure_ascii=False))


async def _restore(state: FSMContext, user_id: int) -> dict:
    data = await state.get_data()
    if data.get("construction_type") or data.get("cart") is not None:
        return data
    raw = db().load_draft(user_id)
    if not raw:
        return data
    try:
        saved = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return data
    if isinstance(saved, dict):
        await state.update_data(**saved)
        data = await state.get_data()
    return data


async def _clear_active(state: FSMContext, user_id: int, keep_cart: bool = True) -> None:
    data = await state.get_data()
    cart = list(data.get("cart") or []) if keep_cart else []
    await state.clear()
    await state.update_data(cart=cart, current_in_cart=False)
    await _persist(state, user_id)


async def _goto_home(target, state: FSMContext):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    saved_cart = []
    if user_id:
        raw = db().load_draft(user_id)
        if raw:
            try:
                payload = json.loads(raw)
                saved_cart = list(payload.get("cart") or []) if isinstance(payload, dict) else []
            except (TypeError, json.JSONDecodeError):
                saved_cart = []
    await state.clear()
    if user_id and saved_cart:
        await state.update_data(cart=saved_cart)
        await _persist(state, user_id)
    elif user_id:
        db().clear_draft(user_id)
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        await msg.edit_text(
            "🏠 <b>Главное меню</b>\n\n"
            "Рассчитайте ориентировочную стоимость, а если цена подходит — закажите замер.",
            parse_mode="HTML",
            reply_markup=kb([
                ("🧮 Рассчитать стоимость", "calc:start"),
                ("📏 Заказать замер", "calc:measure"),
                ("🛒 Мой расчёт", "calc:cart_menu"),
                ("📋 Мои заявки", "nav:history"),
                ("🔧 Сервис", "svc:menu"),
                ("ℹ️ Как это работает", "nav:help"),
            ], cols=2),
        )
    except Exception:
        await msg.answer("🏠 <b>Главное меню</b>", parse_mode="HTML", reply_markup=kb([
            ("🧮 Рассчитать стоимость", "calc:start"), ("📏 Заказать замер", "calc:measure"),
            ("🛒 Мой расчёт", "calc:cart_menu"), ("📋 Мои заявки", "nav:history"),
        ], cols=2))


async def _edit_or_answer(target, text: str, markup, state: FSMContext, user_id: int, screen: str, push: bool = False):
    data = await state.get_data()
    history = list(data.get("builder_history") or [])
    current = data.get("builder_screen")
    if push and current and current != screen:
        history.append(current)
    await state.update_data(builder_screen=screen, builder_history=history)
    await _persist(state, user_id)

    msg = target.message if isinstance(target, CallbackQuery) else target
    if data.get("builder_message_id"):
        try:
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=int(data["builder_message_id"]),
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
            return
        except Exception:
            pass
    sent = await msg.answer(text, parse_mode="HTML", reply_markup=markup)
    await state.update_data(builder_message_id=sent.message_id, builder_chat_id=sent.chat.id)
    await _persist(state, user_id)


async def _edit_builder_message(target, text: str, markup, state: FSMContext, user_id: int, screen: str, push: bool = False):
    """Единый рендерер конструктора: редактирует одно Telegram-сообщение."""
    return await _edit_or_answer(target, text, markup, state, user_id, screen, push)


async def _edit_builder_screen(target, state: FSMContext, text: str, rows: list[tuple[str, str]], cols: int = 1, screen: str | None = None):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    data = await _restore(state, user_id)
    current = screen or data.get("builder_screen") or "builder"
    return await _edit_builder_message(target, text, kb(rows, cols), state, user_id, current, push=True)


async def _builder_back(q: CallbackQuery, state: FSMContext):
    user_id = q.from_user.id if q.from_user else 0
    await _restore(state, user_id)
    data = await state.get_data()
    history = list(data.get("builder_history") or [])
    if data.get("builder_screen") == "window_sashes" and data.get("window_sashes_back") == "construction":
        await state.update_data(builder_history=[], builder_screen="construction")
        return await show_construction(q, state)
    if history:
        screen = history.pop()
        await state.update_data(builder_history=history)
        await _render_screen(q, state, screen, push=False)
    else:
        await show_builder(q, state, reset_history=True)


def _cfg(data: dict) -> CalculationConfig:
    fields = set(CalculationConfig.__dataclass_fields__)
    kwargs = {k: v for k, v in data.items() if k in fields}
    extras = dict(data.get("extras") or {})
    if data.get("sash_configuration"):
        extras["sash_configuration"] = data["sash_configuration"]
    kwargs["extras"] = extras
    return CalculationConfig(**kwargs)


def _product_fields(data: dict) -> dict:
    skip = {
        "cart", "estimate", "customer_name", "phone", "address", "photo_file_id",
        "builder_message_id", "builder_chat_id", "builder_screen", "builder_history",
    }
    out = {k: v for k, v in data.items() if k not in skip and not k.startswith("_")}
    if data.get("sash_configuration"):
        out["sash_configuration"] = data["sash_configuration"]
    return out


def _live_total(data: dict) -> str:
    try:
        return f"≈ {fmt_money(calculator.calculate(_cfg(data)).total)}"
    except Exception:
        return "≈ —"




def _available_glasses(data: dict) -> list[tuple[str, str]]:
    """Показывает только те варианты СП, для которых реально есть цена."""
    ct = data.get("construction_type")
    result = []
    for key, label in GLAZING.items():
        try:
            if ct == "window":
                cfg = data.get("sash_configuration") or data.get("opening") or "tilt_turn"
                get_window_price(data.get("sash_count") or 1, cfg, data.get("profile") or "58", key, data.get("width_mm") or 900, data.get("height_mm") or 1400)
            elif ct == "door":
                get_door_price(
                    data.get("door_type") or data.get("opening") or "single",
                    data.get("door_sash") or "T",
                    data.get("door_threshold") or "frame",
                    data.get("door_lock") or "single",
                    data.get("door_fittings") or "push",
                    key,
                )
            elif ct == "nonstandard":
                cfg = data.get("sash_configuration") or data.get("opening") or "fixed_tilt_turn"
                get_window_price(data.get("sash_count") or 2, cfg, data.get("profile") or "70", key, data.get("width_mm") or 1500, data.get("height_mm") or 1800)
            elif ct in ("balcony", "glass_unit"):
                if key not in {"24", "32", "24_i", "32_i"}:
                    continue
            else:
                continue
        except (KeyError, ValueError):
            continue
        result.append((key, label))
    return result

def _label_glass(g: str | None) -> str:
    return FRIENDLY_GLASS.get(g, GLAZING.get(g, g)) if g else "не выбран"


def _label_sill(data: dict) -> str:
    if not data.get("sill_type"):
        return "нет"
    kind = "ПВХ" if data["sill_type"] == "pvc" else "DANKE"
    return f"{kind} {data.get('sill_depth_mm') or '?'} мм"


def _friendly_config(cfg: str | None) -> tuple[str, str]:
    return WINDOW_CONFIG_FRIENDLY.get(cfg or "", ("Конфигурация окна", "Настройка уточняется"))


def _scheme_text(data: dict) -> str:
    cfg = data.get("sash_configuration") or data.get("opening") or "tilt_turn"
    return WINDOW_SCHEMES.get(cfg, "")


def _profile_label(profile: str | None) -> str:
    return f"{profile or '58'} мм"


def _extras_summary(data: dict) -> str:
    parts = []
    sill = _label_sill(data)
    if sill != "нет":
        parts.append(f"подоконник {sill}")
    if data.get("ebb_width_mm"):
        parts.append(f"отлив {data['ebb_width_mm']} мм")
    if data.get("mosquito"):
        parts.append("москитная сетка")
    if data.get("construction_type") == "balcony" and data.get("door_mosquito"):
        parts.append("дверная москитная сетка 5 000 ₽")
    if data.get("delivery") == "city":
        parts.append("доставка по городу")
    elif data.get("delivery") == "outside":
        parts.append("доставка за город")
    return ", ".join(parts) if parts else "нет"


def _defaults_window() -> dict:
    return {
        "construction_type": "window", "profile": "58", "sash_count": 1,
        "sash_configuration": "tilt_turn", "opening": "tilt_turn",
        "width_mm": 900, "height_mm": 1400, "glass": "32",
        "sill_type": None, "ebb_width_mm": None, "mosquito": False,
        "delivery": None, "opening_direction": None,
    }


def _defaults_door() -> dict:
    return {
        "construction_type": "door", "profile": "70", "width_mm": 900, "height_mm": 2100,
        "door_type": "single", "opening": "single", "door_sash": "T",
        "door_threshold": "frame", "door_lock": "single", "door_fittings": "push",
        "glass": "32", "sill_type": None, "mosquito": False,
        "delivery": None, "opening_direction": "right",
    }


def _defaults_balcony() -> dict:
    return {
        "construction_type": "balcony", "profile": "58", "glass": "32",
        "door_type": "single", "door_sash": "T", "door_threshold": "frame",
        "door_lock": "single", "door_fittings": "push",
        "door_opening_mode": "tilt_turn", "door_mosquito": False,
        "door_width_mm": 700, "door_height_mm": 2100,
        "window_width_mm": 800, "window_height_mm": 1400,
        "width_mm": 800, "height_mm": 1400,
        "window_sash_count": 1, "window_configuration": "tilt_turn",
        "sash_configuration": "tilt_turn", "sill_type": "pvc", "sill_depth_mm": 300,
        "sill_length_mm": 800, "sill2_type": "pvc", "sill2_depth_mm": 300,
        "sill2_length_mm": 700, "mosquito": False, "delivery": None,
    }


def _defaults_glass_unit() -> dict:
    return {
        "construction_type": "glass_unit", "width_mm": 600, "height_mm": 1200,
        "glass": "32", "delivery": None,
    }

def _defaults_nonstandard() -> dict:
    return {
        "construction_type": "nonstandard", "profile": "70",
        "width_mm": 1500, "height_mm": 1800, "glass": "32",
        "sash_count": 2, "sash_configuration": "fixed_tilt_turn",
        "scheme_key": "transom_v", "sill_type": None, "ebb_width_mm": None,
        "mosquito": False, "delivery": None,
    }


def _screen_builder(data: dict) -> tuple[str, list[tuple[str, str]]]:
    ct = data.get("construction_type")
    live = _live_total(data)
    if ct == "window":
        cfg = data.get("sash_configuration") or data.get("opening") or "tilt_turn"
        name, desc = _friendly_config(cfg)
        text = (
            "🧮 <b>Конструктор окна</b>\n\n"
            f"<pre>{_scheme_text(data)}</pre>"
            f"<b>{name}</b>\n{desc}\n\n"
            f"📐 Размер: <b>{data.get('width_mm') or '?'} × {data.get('height_mm') or '?'} мм</b>\n"
            f"🧱 Профиль: <b>{_profile_label(data.get('profile'))}</b>\n"
            f"🔲 Стеклопакет: <b>{_label_glass(data.get('glass'))}</b>\n"
            f"⚙️ Дополнительно: {escape(_extras_summary(data))}\n\n"
            f"💰 <b>{live}</b> <i>ориентировочно</i>"
        )
        rows = [
            ("🪟 Количество/открывание", "b:edit:config"),
            ("📐 Размер", "b:edit:size"),
            ("🧱 Профиль", "b:edit:profile"),
            ("🔲 Стеклопакет", "b:edit:glass"),
            ("⚙️ Дополнительно", "b:edit:extras"),
        ]
        if cfg not in {"fixed", "fixed_fixed", "fixed_fixed_fixed"}:
            rows.append(("↔️ Сторона открывания", "b:edit:dir"))
    elif ct == "door":
        text = (
            "🧮 <b>Конструктор двери</b>\n\n"
            f"📐 Размер: <b>{data.get('width_mm')} × {data.get('height_mm')} мм</b>\n"
            f"🚪 {FRIENDLY_DOOR_UI.get(data.get('door_type'), 'Дверь')} · {FRIENDLY_SASH_UI.get(data.get('door_sash'), 'Стандартная дверь')}\n"
            f"🔲 {_label_glass(data.get('glass'))}\n"
            f"⚙️ Дополнительно: {escape(_extras_summary(data))}\n\n"
            f"💰 <b>{live}</b> <i>ориентировочно</i>"
        )
        rows = [
            ("📐 Размер", "b:edit:size"), ("🚪 Параметры двери", "b:edit:door"),
            ("🔲 Стеклопакет", "b:edit:glass"), ("⚙️ Дополнительно", "b:edit:extras"),
        ]
    elif ct == "balcony":
        text = (
            "🧮 <b>Конструктор балконного блока</b>\n\n"
            f"🪟 Окно: <b>{data.get('window_width_mm')} × {data.get('window_height_mm')} мм</b>\n"
            f"🚪 Дверь: <b>{data.get('door_width_mm')} × {data.get('door_height_mm')} мм</b>\n"
            f"🪟 Открывание окна: <b>{_friendly_config(data.get('window_configuration'))[0]}</b>\n"
            f"🚪 Открывание двери: <b>{'поворотно-откидная' if data.get('door_opening_mode') == 'tilt_turn' else 'поворотная'}</b>\n"
            f"🚪 Дверная москитная сетка: <b>{'да — 5 000 ₽' if data.get('door_mosquito') else 'нет'}</b>\n"
            f"🧱 Профиль: <b>{_profile_label(data.get('profile'))}</b> · 🔲 <b>{_label_glass(data.get('glass'))}</b>\n"
            f"⚙️ Дополнительно: {escape(_extras_summary(data))}\n\n"
            f"💰 <b>{live}</b> <i>ориентировочно</i>"
        )
        rows = [
            ("📐 Размеры блока", "b:edit:bal_size"), ("🪟 Окно в блоке", "b:edit:bal_win"),
            ("🚪 Дверь", "b:edit:door"), ("🧱 Профиль", "b:edit:profile"),
            ("🔲 Стеклопакет", "b:edit:glass"), ("⚙️ Дополнительно", "b:edit:extras"),
        ]
    elif ct == "balcony_glazing":
        kind = data.get("scheme_key") or "frame"
        info = BALCONY_GLAZING_TYPES.get(kind, {})
        try:
            low, high = get_balcony_glazing_package(kind, data.get("profile") or "58")
            range_text = f"{fmt_money(low)} — {fmt_money(high)}"
        except Exception:
            range_text = "уточняется"
        text = (
            "🏢 <b>Балконная рама</b>\n\n"
            f"<b>{info.get('label', kind)}</b>\n<pre>{info.get('scheme', '')}</pre>"
            f"🧱 Профиль: <b>{_profile_label(data.get('profile'))}</b>\n"
            f"💰 <b>{range_text}</b> <i>ориентировочно</i>\n\n"
            "⚠️ Окончательная стоимость определяется после замера и расчёта специалиста."
        )
        rows = [
            ("📐 Тип остекления", "b:edit:glazing_kind"),
            ("🧱 Профиль", "b:edit:profile"), ("⚙️ Дополнительно", "b:edit:extras"),
        ]
    elif ct == "glass_unit":
        text = (
            "🧊 <b>Стеклопакет отдельно</b>\n\n"
            f"📐 Размер: <b>{data.get('width_mm')} × {data.get('height_mm')} мм</b>\n"
            f"🔲 <b>{_label_glass(data.get('glass'))}</b>\n\n"
            f"💰 <b>{live}</b> <i>ориентировочно</i>"
        )
        rows = [("📐 Размер", "b:edit:size"), ("🔲 Стеклопакет", "b:edit:glass")]
    else:
        info = NONSTANDARD_SCHEMES.get(data.get("scheme_key"), {})
        text = (
            "🧩 <b>Другая конструкция</b>\n\n"
            f"<b>{info.get('label', 'Схема не выбрана')}</b>\n<pre>{info.get('scheme', '')}</pre>"
            f"📐 Размер: <b>{data.get('width_mm')} × {data.get('height_mm')} мм</b>\n"
            f"🧱 Профиль: <b>{_profile_label(data.get('profile'))}</b>\n"
            f"🔲 {_label_glass(data.get('glass'))}\n\n"
            f"💰 <b>{live}</b> <i>ориентировочно</i>"
        )
        rows = [
            ("🧩 Схема", "b:edit:scheme"), ("📐 Размер", "b:edit:size"),
            ("🧱 Профиль", "b:edit:profile"), ("🔲 Стеклопакет", "b:edit:glass"),
            ("⚙️ Дополнительно", "b:edit:extras"),
        ]
    return text, rows


async def show_builder(target, state: FSMContext, reset_history: bool = False):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    await _restore(state, user_id)
    data = await state.get_data()
    if not data.get("construction_type"):
        return await show_construction(target.message if isinstance(target, CallbackQuery) else target, state)
    if reset_history:
        await state.update_data(builder_history=[])
    text, rows = _screen_builder(await state.get_data())
    cart = list((await state.get_data()).get("cart") or [])
    rows += [("💰 Посмотреть цену", "b:calc"), ("🛒 Сохранить расчёт", "b:to_cart")]
    if cart:
        rows.append((f"🛒 Мой расчёт ({len(cart)})", "b:cart"))
    rows += [("🔄 Новая конструкция", "calc:start"), ("🏠 Меню", "nav:home")]
    await _edit_or_answer(target, text, kb(rows, cols=2), state, user_id, "builder", push=False)
    await state.set_state(CalculationStates.BUILDER)
    await _persist(state, user_id)


async def _show_window_configs(target, state: FSMContext, sash_count: int):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    data = await _restore(state, user_id)
    options = [(label, f"b:window:config:{key}") for key, label, cnt, cfg in WINDOW_CONFIGS if cnt == sash_count]
    options.append(("⬅️ Назад", "b:back"))
    return await _edit_builder_message(
        target,
        f"🪟 <b>{sash_count} створки</b>\n\nВыберите схему открывания.",
        kb(options, cols=1),
        state,
        user_id,
        "window_configs",
        False,
    )


async def _render_screen(target, state: FSMContext, screen: str, push: bool = True):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    await _restore(state, user_id)
    data = await state.get_data()
    if screen == "builder":
        return await show_builder(target, state, reset_history=False)
    if screen == "window_sashes":
        await state.update_data(window_sashes_back="construction")
        text = "🪟 <b>Выберите количество створок</b>\n\nПосле выбора покажем только подходящие схемы открывания."
        rows = [("1 створка", "b:window:sashes:1"), ("2 створки", "b:window:sashes:2"), ("3 створки", "b:window:sashes:3"), ("⬅️ Назад", "b:back")]
        return await _edit_builder_message(target, text, kb(rows, cols=1), state, user_id, "window_sashes", push)
    if screen == "config":
        return await _render_screen(target, state, "window_sashes", push)
    if screen == "window_configs":
        n = int(data.get("sash_count") or 1)
        return await _show_window_configs(target, state, n)
    if screen == "profile":
        return await _edit_or_answer(target, "🧱 <b>Профиль</b>", kb([("58 мм", "b:set:profile:58"), ("70 мм", "b:set:profile:70"), ("⬅️ Назад", "b:back")], cols=2), state, user_id, "profile", push)
    if screen == "size":
        ct = data.get("construction_type")
        presets = DOOR_SIZE_PRESETS if ct == "door" else WINDOW_SIZE_PRESETS.get(data.get("sash_count") or 1, WINDOW_SIZE_PRESETS[1])
        rows = [(f"{w} × {h} мм", f"b:set:size:{w}x{h}") for w, h in presets]
        rows += [("✏️ Свои размеры", "b:set:size:custom"), ("⬅️ Назад", "b:back")]
        return await _edit_or_answer(target, "📐 <b>Выберите размер Ш × В</b>", kb(rows, cols=2), state, user_id, "size", push)
    if screen == "glass":
        glass_labels = {
            "24": "СП 24 мм",
            "32": "СП 32 мм",
            "24_i": "СП 24 мм + i с двух сторон",
            "32_i": "СП 32 мм + i с двух сторон",
        }
        rows = [(glass_labels[key], f"b:set:glass:{key}") for key, _ in _available_glasses(data) if key in glass_labels]
        rows.append(("⬅️ Назад", "b:back"))
        return await _edit_or_answer(target, "🔲 <b>Стеклопакет</b>", kb(rows, cols=1), state, user_id, "glass", push)
    if screen == "dir":
        return await _edit_or_answer(target, "↔️ <b>Сторона открывания</b>", kb([("⬅️ Левое", "b:set:dir:left"), ("➡️ Правое", "b:set:dir:right"), ("⬅️ Назад", "b:back")], cols=2), state, user_id, "dir", push)
    if screen == "extras":
        ct = data.get("construction_type")
        rows = [
            ("Без подоконника", "b:set:sill:none"), ("ПВХ-подоконник", "b:set:sill:pvc"), ("Подоконник DANKE", "b:set:sill:danke"),
            ("Без москитной сетки", "b:set:mos:0"), ("Москитная сетка", "b:set:mos:1"),
            ("Без доставки", "b:set:del:none"), ("Доставка по городу", "b:set:del:city"), ("Доставка за город", "b:set:del:outside"),
        ]
        if ct not in ("balcony", "balcony_glazing"):
            rows += [("Без отлива", "b:set:ebb:none"), ("Отлив 150 мм", "b:set:ebb:150"), ("Отлив 200 мм", "b:set:ebb:200")]
        rows.append(("⬅️ Назад", "b:back"))
        text = (
            "⚙️ <b>Дополнительно</b>\n\n"
            f"Подоконник: <b>{escape(_label_sill(data))}</b>\n"
            f"Отлив: <b>{data.get('ebb_width_mm') or 'нет'}</b>\n"
            f"Москитная сетка: <b>{'да' if data.get('mosquito') else 'нет'}</b>\n"
            f"Доставка: <b>{data.get('delivery') or 'нет'}</b>\n\n"
            "Монтаж 17% уже включает демонтаж старых конструкций."
        )
        return await _edit_or_answer(target, text, kb(rows, cols=2), state, user_id, "extras", push)
    if screen == "sdepth":
        return await _edit_or_answer(target, "📏 <b>Глубина подоконника</b>", kb([
            ("250 мм", "b:set:sdepth:250"), ("300 мм", "b:set:sdepth:300"),
            ("350 мм", "b:set:sdepth:350"), ("400 мм", "b:set:sdepth:400"), ("⬅️ Назад", "b:back")
        ], cols=2), state, user_id, "sdepth", push)
    if screen == "door":
        ct = data.get("construction_type")
        rows = []
        if ct != "balcony":
            # Для отдельной двери эти параметры имеют отдельные цены.
            rows += [(v, f"b:set:dtype:{k}") for k, v in FRIENDLY_DOOR_UI.items()]
            rows += [(v, f"b:set:dsash:{k}") for k, v in FRIENDLY_SASH_UI.items()]
        else:
            rows += [
                ("Поворотная дверь", "b:set:baldoor:turn"),
                ("Поворотно-откидная дверь (+1 000 ₽)", "b:set:baldoor:tilt_turn"),
                (f"Дверная москитная сетка — {'✅ 5 000 ₽' if data.get('door_mosquito') else '5 000 ₽'}", "b:set:baldoor:mos"),
                ("Без дверной москитной сетки", "b:set:baldoor:nomos"),
            ]
            rows.append(("Одностворчатая дверь", "b:set:dtype:single"))
            rows.append(("Стандартная дверь", "b:set:dsash:T"))
        rows += [(v, f"b:set:dthr:{k}") for k, v in FRIENDLY_THRESHOLD_UI.items()]
        rows += [(v, f"b:set:dlock:{k}") for k, v in FRIENDLY_LOCK_UI.items()]
        rows += [(v, f"b:set:dfit:{k}") for k, v in FRIENDLY_FITTINGS_UI.items()]
        rows.append(("⬅️ Назад", "b:back"))
        return await _edit_or_answer(target, "🚪 <b>Параметры двери</b>", kb(rows, cols=1), state, user_id, "door", push)
    if screen == "bal_size":
        return await _edit_or_answer(target, "📐 <b>Размеры балконного блока</b>\n\nВыберите типовой вариант или введите свои размеры.", kb([
            ("📦 Типовые размеры", "b:bal:preset"), ("✏️ Свои размеры", "b:bal:custom"), ("⬅️ Назад", "b:back")
        ], cols=1), state, user_id, "bal_size", push)
    if screen == "bal_preset":
        rows = [(f"🚪 {dw}×{dh} + 🪟 {ww}×{wh}", f"b:set:balpreset:{dw}x{dh}x{ww}x{wh}") for dw, dh, ww, wh in BALCONY_PRESETS]
        rows.append(("⬅️ Назад", "b:back"))
        return await _edit_or_answer(target, "📦 <b>Типовой балконный блок</b>", kb(rows, cols=1), state, user_id, "bal_preset", push)
    if screen == "bal_win":
        rows = [
            ("Глухое окно", "b:set:balcfg:fixed"),
            ("Открывается + проветривание", "b:set:balcfg:tilt_turn"),
            ("Глухое + ПО (2 створки)", "b:set:balcfg:fixed_tilt_turn"),
            ("⬅️ Назад", "b:back"),
        ]
        return await _edit_or_answer(target, "🪟 <b>Окно в балконном блоке</b>", kb(rows, cols=1), state, user_id, "bal_win", push)
    if screen == "scheme":
        rows = [(info["label"], f"b:set:scheme:{key}") for key, info in NONSTANDARD_SCHEMES.items()]
        rows.append(("⬅️ Назад", "b:back"))
        return await _edit_or_answer(target, "🧩 <b>Схема другой конструкции</b>", kb(rows, cols=1), state, user_id, "scheme", push)
    if screen == "glazing_kind":
        rows = [(info["label"], f"b:set:gkind:{key}") for key, info in BALCONY_GLAZING_TYPES.items()]
        rows.append(("⬅️ Назад", "b:back"))
        return await _edit_or_answer(target, "🏢 <b>Тип остекления</b>", kb(rows, cols=1), state, user_id, "glazing_kind", push)
    if screen == "glazing_size":
        return await _edit_or_answer(target, "📏 <b>Размер остекления</b>\n\nДля предварительного расчёта пакетная цена не меняется от размера. Точные размеры подтверждаются замером.", kb([("⬅️ Назад", "b:back")]), state, user_id, "glazing_size", push)
    if screen == "estimate":
        return await _render_estimate(target, state)
    if screen == "cart":
        return await _render_cart(target, state)
    return await show_builder(target, state)


async def _render_estimate(target, state: FSMContext, details: bool = False):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    data = await _restore(state, user_id)
    try:
        e = calculator.calculate(_cfg(data))
    except PricingError as ex:
        return await _edit_or_answer(target, f"⚠️ {escape(str(ex))}", kb([("⬅️ К конструктору", "b:back")]), state, user_id, "builder", False)
    cfg = _cfg(data)
    await state.update_data(estimate={
        "subtotal": str(e.subtotal), "installation": str(e.installation), "total": str(e.total),
        "items": [(i.name, str(i.price)) for i in e.items], "title": cfg.short_title(),
    })
    await state.set_state(CalculationStates.CONFIRM_ESTIMATE)
    cart = list(data.get("cart") or [])
    rows = [("📏 Заказать замер", "calc:request"), ("🛒 Сохранить расчёт", "b:to_cart")]
    if cart:
        rows.insert(1, (f"🛒 Мой расчёт ({len(cart)})", "b:cart"))
    rows += [("ℹ️ Дополнительно" if not details else "⬅️ Кратко", "b:estimate:details" if not details else "b:estimate:summary"), ("✏️ Изменить", "b:back"), ("🔄 Новый расчёт", "calc:start"), ("🏠 Меню", "nav:home")]

    if details:
        text = [
            "💰 <b>Ориентировочная стоимость</b>", "",
            f"<b>{escape(cfg.short_title())}</b>", "",
        ]
        for item in e.items:
            if data.get("construction_type") == "glass_unit" and item.name == "Монтаж стеклопакета":
                continue
            text.append(f"• {escape(item.name)} — <b>{fmt_money(item.price)}</b>")
        text += [
            "", f"Конструкция и доп. элементы: <b>{fmt_money(e.subtotal)}</b>",
            f"Монтаж 17%: <b>{fmt_money(e.installation)}</b>",
            "<i>Демонтаж уже входит в монтаж 17%.</i>",
            "────────────", f"💰 <b>ИТОГО: {fmt_money(e.total)}</b>",
            "", ("📏 Замер стеклопакета — <b>500 ₽</b>." if data.get("construction_type") == "glass_unit" else "📏 Замер для окон, дверей и балконных блоков — <b>бесплатно</b>."),
        ]
    else:
        extras = _extras_summary(data)
        text = [
            "💰 <b>Ориентировочная стоимость</b>", "",
            f"<b>{escape(cfg.short_title())}</b>",
        ]
        if data.get("construction_type") == "window":
            text.append(f"Стеклопакет: <b>{escape(_label_glass(data.get('glass')))}</b>")
        elif data.get("construction_type") == "balcony":
            text.append(f"Окно: <b>{data.get('window_width_mm')} × {data.get('window_height_mm')} мм</b> · Дверь: <b>{data.get('door_width_mm')} × {data.get('door_height_mm')} мм</b>")
        if data.get("construction_type") == "glass_unit":
            text += [
                f"Дополнительно: <b>{escape(extras)}</b>", "",
                f"Монтаж стеклопакета: <b>{fmt_money(e.installation)}</b>",
                "────────────", f"💰 <b>ИТОГО: {fmt_money(e.total)}</b>",
                "", "📏 <b>Хотите узнать точную стоимость?</b>",
            ]
        else:
            text += [
                f"Дополнительно: <b>{escape(extras)}</b>", "",
                f"Монтаж 17% уже включён",
                "────────────", f"💰 <b>ИТОГО: {fmt_money(e.total)}</b>",
                "", "📏 <b>Хотите узнать точную стоимость?</b>",
            ]
        text += [
            "Закажите замер — бесплатно. После проверки проёма подтвердим размеры и итоговую цену.",
        ]
    await _edit_or_answer(target, "\n".join(text), kb(rows, cols=2), state, user_id, "estimate", False)


async def _render_cart(target, state: FSMContext):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    data = await _restore(state, user_id)
    cart = list(data.get("cart") or [])
    if not cart:
        return await _edit_or_answer(target, "🛒 <b>Мой расчёт</b>\n\nСохранённых конструкций пока нет.", kb([("🧮 Рассчитать стоимость", "calc:start"), ("🏠 Меню", "nav:home")], cols=2), state, user_id, "cart", False)
    grand = sum((Decimal(x.get("total", "0")) for x in cart), Decimal("0"))
    lines = ["🛒 <b>Мой расчёт</b>", "", "До 10 конструкций. Вы можете изменить или удалить любую.", ""]
    rows = []
    for i, item in enumerate(cart, 1):
        lines.append(f"<b>{i}. {escape(item.get('title', 'Изделие'))}</b> — <b>{fmt_money(item.get('total', '0'))}</b>")
        details = _product_manager_details(item)
        if details:
            lines.append(details)
        lines.append("")
        rows.append((f"✏️ Изменить №{i}", f"b:cart:edit:{i-1}"))
        rows.append((f"🗑 Удалить №{i}", f"b:cart:delete:{i-1}"))
    lines += ["────────────", f"💰 <b>Итого: {fmt_money(grand)}</b>", "<i>Монтаж 17% уже включён.</i>"]
    rows += [("📏 Заказать замер", "b:cart_checkout"), ("➕ Добавить конструкцию", "calc:start"), ("🗑 Очистить расчёты", "b:cart_clear"), ("🏠 Меню", "nav:home")]
    await state.set_state(CalculationStates.CART)
    await _edit_or_answer(target, "\n".join(lines), kb(rows, cols=2), state, user_id, "cart", False)


async def show_construction(target, state: FSMContext):
    user_id = target.from_user.id if getattr(target, "from_user", None) else 0
    await state.set_state(CalculationStates.SELECT_CONSTRUCTION)
    await _edit_or_answer(target, "<b>Что хотите рассчитать?</b>\n\nВыберите конструкцию.", kb([
        ("🪟 Окно", "calc:window"), ("🚪 Дверь", "calc:door"),
        ("🧊 Стеклопакет отдельно", "calc:glass_unit"),
        ("🚪 Балконный блок", "calc:balcony"), ("🏢 Балконы и лоджии", "calc:bal_glazing"),
        ("🧩 Другая конструкция", "calc:nonstandard"), ("📏 Сразу заказать замер", "calc:measure"),
        ("🏠 Меню", "nav:home"),
    ], cols=2), state, user_id, "construction", False)


@router.callback_query(F.data == "nav:home")
async def nav_home(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await _goto_home(q, state)


@router.callback_query(F.data == "nav:back")
async def nav_back(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await _builder_back(q, state)


@router.callback_query(F.data == "nav:history")
async def nav_history(q: CallbackQuery, state: FSMContext):
    await q.answer()
    rows = db().history(q.from_user.id if q.from_user else 0, limit=8)
    if not rows:
        return await q.message.edit_text("📋 <b>Мои заявки</b>\n\nПока нет заявок.", parse_mode="HTML", reply_markup=kb([("🧮 Рассчитать", "calc:start"), ("🏠 Меню", "nav:home")], cols=2))
    lines = ["📋 <b>Мои заявки</b>", ""]
    buttons = []
    for rid, total, status, created in rows:
        lines.append(f"{STATUS_LABELS.get(status or 'new', '🆕 Новая')} №{rid} — {fmt_money(total)} — {escape(str(created))}")
        buttons.append((f"📄 Заявка №{rid}", f"history:view:{rid}"))
    buttons += [("🧮 Новый расчёт", "calc:start"), ("🏠 Меню", "nav:home")]
    await q.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(buttons, cols=2))


@router.callback_query(F.data.startswith("history:view:"))
async def history_view(q: CallbackQuery, state: FSMContext):
    await q.answer()
    try:
        rid = int((q.data or "").rsplit(":", 1)[1])
    except (ValueError, TypeError):
        return await q.message.answer("Заявка не найдена.")
    row = db().get_request(rid)
    if not row or row[1] != q.from_user.id:
        return await q.message.answer("Заявка не найдена.")
    _, user_id, name, phone, config_json, total, status, address, created = row
    try:
        payload = json.loads(config_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    cart = payload.get("cart") or []
    lines = [f"📄 <b>Заявка №{rid}</b>", f"Статус: <b>{STATUS_LABELS.get(status or 'new', '🆕 Новая')}</b>", f"Дата: {escape(str(created))}", "", f"👤 {escape(name or '—')}", f"📞 {escape(phone or '—')}", f"📍 {escape(address or 'Адрес не указан')}", "", "🧾 <b>Состав</b>"]
    for i, item in enumerate(cart, 1):
        lines.append(f"\n<b>{i}. {escape(item.get('title', 'Изделие'))}</b> — <b>{fmt_money(item.get('total', '0'))}</b>")
        details = _manager_product_details_for_history(item)
        if details:
            lines.append(details)
    if not cart and payload.get("estimate"):
        est = payload["estimate"]
        lines.append(f"\n<b>{escape(est.get('title', 'Расчёт'))}</b> — <b>{fmt_money(est.get('total', total))}</b>")
    if payload.get("type") == "service":
        lines.append(f"\n🔧 <b>{escape(payload.get('title', 'Сервис'))}</b>")
        for item_name, price in payload.get("items") or []:
            lines.append(f"• {escape(str(item_name))} — <b>{fmt_money(price)}</b>")
    if "measure_fee" in payload:
        try:
            fee = Decimal(str(payload.get("measure_fee") or "0"))
        except Exception:
            fee = Decimal("0")
        fee_label = "бесплатно" if fee == 0 else fmt_money(fee)
        lines.append(f"\n📏 Замер: <b>{fee_label}</b>")
    lines += ["", "────────────", f"💰 <b>ИТОГО: {fmt_money(total)}</b>"]
    await q.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb([("📋 Заявки", "nav:history"), ("🏠 Меню", "nav:home")], cols=2))


@router.callback_query(F.data == "nav:help")
async def nav_help(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await q.message.edit_text(
        "ℹ️ <b>Как это работает</b>\n\n"
        "1. Выбираете конструкцию.\n2. Все параметры меняются в одном сообщении-конструкторе.\n"
        "3. Кнопка «Назад» возвращает на предыдущий экран.\n4. Цена ориентировочная.\n\n"
        "Монтаж 17% уже включает демонтаж старых конструкций. Обычный замер — бесплатно; 500 ₽ только для замера москитных сеток и стеклопакетов.",
        parse_mode="HTML", reply_markup=kb([("🧮 Рассчитать", "calc:start"), ("🏠 Меню", "nav:home")], cols=2),
    )


@router.callback_query(F.data == "calc:start")
async def calc_start(q: CallbackQuery, state: FSMContext):
    await q.answer()
    data = await _restore(state, q.from_user.id)
    cart = list(data.get("cart") or [])
    await state.clear()
    await state.update_data(cart=cart, current_in_cart=False)
    await _persist(state, q.from_user.id)
    await show_construction(q.message, state)


@router.callback_query(F.data == "calc:window")
async def pick_window(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.update_data(**_defaults_window(), builder_history=[])
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "calc:door")
async def pick_door(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.update_data(**_defaults_door(), builder_history=[])
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "calc:balcony")
async def pick_balcony(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.update_data(**_defaults_balcony(), builder_history=[])
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "calc:bal_glazing")
async def pick_bal_glazing(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(CalculationStates.SELECT_CONSTRUCTION)
    text = (
        "🏢 <b>Балконы и лоджии</b>\n\n"
        "Балконные рамы и лоджии — сложные конструкции, поэтому стоимость зависит от размеров, формы, профиля и особенностей объекта.\n\n"
        "💰 <b>Ориентировочная стоимость — от 70 000 до 200 000+ ₽</b>\n\n"
        "Для предварительного точного расчёта рекомендуем:\n\n"
        "📏 <b>Заказать бесплатный замер</b> — специалист выполнит замер на объекте, после чего мы рассчитаем стоимость конструкции.\n\n"
        "💬 Или <b>связаться с менеджером</b> и отправить ему размеры/фото объекта для предварительного расчёта."
    )
    await q.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=kb([
            ("📏 Заказать бесплатный замер", "calc:measure"),
            ("💬 Связаться с менеджером", "manager"),
            ("🏠 Меню", "nav:home"),
        ], cols=2),
    )



@router.callback_query(F.data == "calc:glass_unit")
async def pick_glass_unit(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.update_data(**_defaults_glass_unit(), builder_history=[])
    await show_builder(q, state, reset_history=True)

@router.callback_query(F.data == "calc:nonstandard")
async def pick_nonstandard(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.update_data(**_defaults_nonstandard(), builder_history=[])
    await show_builder(q, state, reset_history=True)


# Редактирование параметров — компактные экраны. Все они используют одно сообщение-конструктор.
# Внутри этого блока не создаём новые сообщения — только редактируем конструктор.
# _edit_builder_screen остаётся единым совместимым именем рендера для всех подэкранов.
@router.callback_query(F.data == "b:back")
async def builder_back(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await _builder_back(q, state)


@router.callback_query(F.data == "b:edit:config")
async def edit_config(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "config")


@router.callback_query(F.data.startswith("b:window:sashes:"))
async def choose_sash_count(q: CallbackQuery, state: FSMContext):
    await q.answer()
    user_id = q.from_user.id
    await _restore(state, user_id)
    sash_count = int(q.data.rsplit(":", 1)[1])
    data = await state.get_data()
    history = list(data.get("builder_history") or [])
    history.append("window_sashes")
    await state.update_data(sash_count=sash_count, builder_history=history)
    await _show_window_configs(q, state, sash_count)


@router.callback_query(F.data.startswith("b:count:"))
async def choose_sash_count_legacy(q: CallbackQuery, state: FSMContext):
    # Старые inline-кнопки не ломают уже отправленные сообщения.
    await q.answer()
    user_id = q.from_user.id
    await _restore(state, user_id)
    sash_count = int(q.data.rsplit(":", 1)[1])
    data = await state.get_data()
    history = list(data.get("builder_history") or [])
    history.append("window_sashes")
    await state.update_data(sash_count=sash_count, builder_history=history)
    await _show_window_configs(q, state, sash_count)


@router.callback_query(F.data.startswith("b:window:config:"))
async def set_config(q: CallbackQuery, state: FSMContext):
    await q.answer(); user_id = q.from_user.id; await _restore(state, user_id)
    key = q.data.rsplit(":", 1)[1]
    found = next(((k, label, n, cfg) for k, label, n, cfg in WINDOW_CONFIGS if k == key), None)
    if not found:
        return await q.answer("Схема не найдена", show_alert=True)
    _, _, n, cfg = found
    await state.update_data(sash_count=n, sash_configuration=cfg, opening=cfg, builder_history=[])
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:cfg:"))
async def set_config_legacy(q: CallbackQuery, state: FSMContext):
    await q.answer()
    user_id = q.from_user.id
    await _restore(state, user_id)
    key = q.data.rsplit(":", 1)[1]
    found = next(((k, label, n, cfg) for k, label, n, cfg in WINDOW_CONFIGS if k == key), None)
    if not found:
        return await q.answer("Схема не найдена", show_alert=True)
    _, _, n, cfg = found
    await state.update_data(sash_count=n, sash_configuration=cfg, opening=cfg, builder_history=[])
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:profile")
async def edit_profile(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "profile")


@router.callback_query(F.data.startswith("b:set:profile:"))
async def set_profile(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(profile=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:size")
async def edit_size(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "size")


@router.callback_query(F.data.startswith("b:set:size:"))
async def set_size(q: CallbackQuery, state: FSMContext):
    await q.answer(); user_id = q.from_user.id; await _restore(state, user_id)
    val = q.data.rsplit(":", 1)[1]
    if val == "custom":
        await state.set_state(CalculationStates.EDIT_SIZE_CUSTOM_W)
        return await _edit_builder_message(q, "📐 <b>Введите ширину в мм</b>\n\nНапример: <code>1200</code>", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, user_id, "size_custom_w", True)
    w, h = map(int, val.split("x"))
    data = await state.get_data()
    err = validate_size(w, h, "door" if data.get("construction_type") == "door" else ("window" if data.get("construction_type") != "glass_unit" else "window"), data.get("sash_count"), data.get("sash_configuration"))
    if err:
        return await q.answer(err, show_alert=True)
    await state.update_data(width_mm=w, height_mm=h)
    await show_builder(q, state, reset_history=True)


async def _read_mm(m: Message, min_value: int = 1, max_value: int = 3000) -> int | None:
    try:
        value = int((m.text or "").strip())
    except ValueError:
        await m.answer("Введите целое число в миллиметрах.")
        return None
    if not min_value <= value <= max_value:
        await m.answer(f"Введите число от {min_value} до {max_value} мм.")
        return None
    return value


async def _edit_builder_from_message(m: Message, state: FSMContext):
    data = await state.get_data()
    mid = data.get("builder_message_id")
    chat_id = data.get("builder_chat_id")
    if mid and chat_id:
        try:
            # Callback message is not available here, so edit via Bot.
            await m.bot.edit_message_text(chat_id=int(chat_id), message_id=int(mid), text="", reply_markup=None)
        except Exception:
            pass
    await show_builder(m, state, reset_history=True)


@router.message(CalculationStates.EDIT_SIZE_CUSTOM_W)
async def custom_w(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 400, 3000)
    if value is None: return
    await state.update_data(_tmp_w=value)
    await state.set_state(CalculationStates.EDIT_SIZE_CUSTOM_H)
    await _edit_builder_message(m, "📐 <b>Введите высоту в мм</b>\n\nНапример: <code>1400</code>", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, m.from_user.id, "size_custom_h", False)
    try: await m.delete()
    except Exception: pass


@router.message(CalculationStates.EDIT_SIZE_CUSTOM_H)
async def custom_h(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 400, 2800)
    if value is None: return
    data = await state.get_data()
    w = int(data.get("_tmp_w") or 0)
    err = validate_size(w, value, "door" if data.get("construction_type") == "door" else "window", data.get("sash_count"), data.get("sash_configuration"))
    if err:
        return await m.answer(f"⚠️ {err}")
    await state.update_data(width_mm=w, height_mm=value, _tmp_w=None)
    await state.set_state(CalculationStates.BUILDER)
    try: await m.delete()
    except Exception: pass
    await show_builder(m, state, reset_history=True)


@router.callback_query(F.data == "b:edit:glass")
async def edit_glass(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "glass")


@router.callback_query(F.data.startswith("b:set:glass:"))
async def set_glass(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(glass=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:dir")
async def edit_dir(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "dir")


@router.callback_query(F.data.startswith("b:set:dir:"))
async def set_dir(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(opening_direction=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:extras")
async def edit_extras(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "extras")


@router.callback_query(F.data.startswith("b:set:sill:"))
async def set_sill(q: CallbackQuery, state: FSMContext):
    await q.answer(); kind = q.data.rsplit(":", 1)[1]
    if kind == "none":
        await state.update_data(sill_type=None, sill_depth_mm=None)
        return await show_builder(q, state, reset_history=True)
    await state.update_data(sill_type=kind)
    await _render_screen(q, state, "sdepth")


@router.callback_query(F.data.startswith("b:set:sdepth:"))
async def set_sdepth(q: CallbackQuery, state: FSMContext):
    await q.answer(); depth = int(q.data.rsplit(":", 1)[1]); data = await state.get_data()
    await state.update_data(sill_depth_mm=depth, sill_length_mm=data.get("window_width_mm") or data.get("width_mm") or 0)
    if data.get("construction_type") == "balcony":
        await state.update_data(sill2_type=data.get("sill_type"), sill2_depth_mm=depth, sill2_length_mm=data.get("door_width_mm") or 700)
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:ebb:"))
async def set_ebb(q: CallbackQuery, state: FSMContext):
    await q.answer(); v = q.data.rsplit(":", 1)[1]; await state.update_data(ebb_width_mm=None if v == "none" else int(v)); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:mos:"))
async def set_mos(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(mosquito=q.data.endswith(":1")); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:del:"))
async def set_del(q: CallbackQuery, state: FSMContext):
    await q.answer(); v = q.data.rsplit(":", 1)[1]; await state.update_data(delivery=None if v == "none" else v); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:door")
async def edit_door(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "door")


@router.callback_query(F.data.startswith("b:set:dtype:"))
async def set_dtype(q: CallbackQuery, state: FSMContext):
    await q.answer(); v = q.data.rsplit(":", 1)[1]; await state.update_data(door_type=v, opening=v); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:dsash:"))
async def set_dsash(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(door_sash=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:dthr:"))
async def set_dthr(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(door_threshold=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:dlock:"))
async def set_dlock(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(door_lock=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:dfit:"))
async def set_dfit(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(door_fittings=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data.startswith("b:set:baldoor:"))
async def set_balcony_door_option(q: CallbackQuery, state: FSMContext):
    await q.answer()
    value = q.data.rsplit(":", 1)[1]
    if value in {"turn", "tilt_turn"}:
        await state.update_data(door_opening_mode=value)
    elif value == "mos":
        await state.update_data(door_mosquito=True)
    elif value == "nomos":
        await state.update_data(door_mosquito=False)
    await _render_screen(q, state, "door", push=False)


@router.callback_query(F.data == "b:edit:bal_size")
async def edit_bal_size(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "bal_size")


@router.callback_query(F.data == "b:bal:preset")
async def bal_preset(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "bal_preset")


@router.callback_query(F.data.startswith("b:set:balpreset:"))
async def set_bal_preset(q: CallbackQuery, state: FSMContext):
    await q.answer(); dw, dh, ww, wh = map(int, q.data.rsplit(":", 1)[1].split("x"))
    await state.update_data(door_width_mm=dw, door_height_mm=dh, window_width_mm=ww, window_height_mm=wh, width_mm=ww, height_mm=wh, sill_length_mm=ww, sill2_length_mm=dw)
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:bal:custom")
async def bal_custom_start(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.set_state(CalculationStates.EDIT_BAL_DOOR_W)
    await _edit_builder_message(q, "🚪 <b>Введите ширину двери в мм</b>\n\nДопустимо 600–1800 мм.", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, q.from_user.id, "bal_custom_door_w", True)


@router.message(CalculationStates.EDIT_BAL_DOOR_W)
async def bal_custom_door_w(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 600, 1800)
    if value is None: return
    await state.update_data(door_width_mm=value)
    await state.set_state(CalculationStates.EDIT_BAL_DOOR_H)
    await _edit_builder_message(m, "🚪 <b>Высота двери в мм</b>\n\nДопустимо 1800–2400 мм.", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, m.from_user.id, "bal_custom_door_h", False)
    try: await m.delete()
    except Exception: pass


@router.message(CalculationStates.EDIT_BAL_DOOR_H)
async def bal_custom_door_h(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 1800, 2400)
    if value is None: return
    await state.update_data(door_height_mm=value)
    await state.set_state(CalculationStates.EDIT_BAL_WIN_W)
    await _edit_builder_message(m, "🪟 <b>Ширина окна в мм</b>\n\nДопустимо 400–3000 мм.", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, m.from_user.id, "bal_custom_win_w", False)
    try: await m.delete()
    except Exception: pass


@router.message(CalculationStates.EDIT_BAL_WIN_W)
async def bal_custom_win_w(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 400, 3000)
    if value is None: return
    await state.update_data(window_width_mm=value, width_mm=value)
    await state.set_state(CalculationStates.EDIT_BAL_WIN_H)
    await _edit_builder_message(m, "🪟 <b>Высота окна в мм</b>\n\nДопустимо 400–2800 мм.", kb([("⬅️ Назад", "b:back"), ("🏠 Меню", "nav:home")], cols=2), state, m.from_user.id, "bal_custom_win_h", False)
    try: await m.delete()
    except Exception: pass


@router.message(CalculationStates.EDIT_BAL_WIN_H)
async def bal_custom_win_h(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    value = await _read_mm(m, 400, 2800)
    if value is None: return
    data = await state.get_data()
    w = int(data.get("window_width_mm") or 0)
    err = validate_size(w, value, "window", data.get("window_sash_count") or 1, data.get("window_configuration"))
    if err:
        return await m.answer(f"⚠️ {err}")
    await state.update_data(window_height_mm=value, height_mm=value, sill_length_mm=w, sill2_length_mm=data.get("door_width_mm") or 700)
    await state.set_state(CalculationStates.BUILDER)
    try: await m.delete()
    except Exception: pass
    await show_builder(m, state, reset_history=True)


@router.callback_query(F.data == "b:edit:bal_win")
async def edit_bal_win(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "bal_win")


@router.callback_query(F.data.startswith("b:set:balcfg:"))
async def set_balcfg(q: CallbackQuery, state: FSMContext):
    await q.answer(); cfg = q.data.rsplit(":", 1)[1]; await state.update_data(window_configuration=cfg, sash_configuration=cfg, window_sash_count=1); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:scheme")
async def edit_scheme(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "scheme")


@router.callback_query(F.data.startswith("b:set:scheme:"))
async def set_scheme(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(scheme_key=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:glazing_kind")
async def edit_glazing_kind(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "glazing_kind")


@router.callback_query(F.data.startswith("b:set:gkind:"))
async def set_gkind(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.update_data(scheme_key=q.data.rsplit(":", 1)[1]); await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:edit:glazing_size")
async def edit_glazing_size(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_screen(q, state, "glazing_size")


@router.callback_query(F.data == "b:estimate:details")
async def estimate_details(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await _render_estimate(q, state, details=True)


@router.callback_query(F.data == "b:estimate:summary")
async def estimate_summary(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await _render_estimate(q, state, details=False)


@router.callback_query(F.data == "b:calc")
async def do_calc(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_estimate(q, state)


@router.callback_query(F.data == "b:to_cart")
async def to_cart(q: CallbackQuery, state: FSMContext):
    await q.answer(); user_id = q.from_user.id; await _restore(state, user_id); data = await state.get_data()
    cart = list(data.get("cart") or [])
    if len(cart) >= MAX_CART_ITEMS:
        return await q.answer("Можно сохранить максимум 10 конструкций", show_alert=True)
    try:
        e = calculator.calculate(_cfg(data))
    except PricingError as ex:
        return await q.answer(str(ex), show_alert=True)
    item = {"product": _product_fields(data), "title": _cfg(data).short_title(), "total": str(e.total), "subtotal": str(e.subtotal), "installation": str(e.installation), "items": [(i.name, str(i.price)) for i in e.items]}
    cart.append(item)
    await state.update_data(cart=cart, current_in_cart=True)
    await _persist(state, user_id)
    await _render_cart(q, state)


@router.callback_query(F.data == "calc:cart_menu")
async def cart_menu(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _restore(state, q.from_user.id); await _render_cart(q, state)


@router.callback_query(F.data == "b:cart")
async def show_cart(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _render_cart(q, state)


@router.callback_query(F.data.startswith("b:cart:delete:"))
async def cart_delete(q: CallbackQuery, state: FSMContext):
    await q.answer("Удалено"); await _restore(state, q.from_user.id)
    idx = int(q.data.rsplit(":", 1)[1]); cart = list((await state.get_data()).get("cart") or [])
    if 0 <= idx < len(cart): cart.pop(idx)
    await state.update_data(cart=cart)
    await _persist(state, q.from_user.id)
    await _render_cart(q, state)


@router.callback_query(F.data.startswith("b:cart:edit:"))
async def cart_edit(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _restore(state, q.from_user.id)
    idx = int(q.data.rsplit(":", 1)[1]); data = await state.get_data(); cart = list(data.get("cart") or [])
    if not 0 <= idx < len(cart): return await _render_cart(q, state)
    product = dict(cart.pop(idx).get("product") or {})
    await state.clear(); await state.update_data(cart=cart, **product, current_in_cart=False, builder_history=[])
    await _persist(state, q.from_user.id)
    await show_builder(q, state, reset_history=True)


@router.callback_query(F.data == "b:cart_clear")
async def cart_clear(q: CallbackQuery, state: FSMContext):
    await q.answer("Очищено"); await state.update_data(cart=[]); await _persist(state, q.from_user.id); await _render_cart(q, state)


async def _ensure_current_in_cart(state: FSMContext) -> list[dict]:
    data = await state.get_data(); cart = list(data.get("cart") or [])
    if not data.get("construction_type") or data.get("current_in_cart"):
        return cart
    try:
        e = calculator.calculate(_cfg(data))
    except PricingError:
        return cart
    if len(cart) >= MAX_CART_ITEMS:
        return cart
    cart.append({"product": _product_fields(data), "title": _cfg(data).short_title(), "total": str(e.total), "subtotal": str(e.subtotal), "installation": str(e.installation), "items": [(i.name, str(i.price)) for i in e.items]})
    await state.update_data(cart=cart, current_in_cart=True)
    return cart


@router.callback_query(F.data == "b:cart_checkout")
async def cart_checkout(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _restore(state, q.from_user.id)
    cart = await _ensure_current_in_cart(state)
    if not cart:
        return await q.answer("Нечего оформлять", show_alert=True)
    await _persist(state, q.from_user.id)
    grand = sum((Decimal(x["total"]) for x in cart), Decimal("0"))
    await state.update_data(estimate={"total": str(grand), "cart": cart})
    await state.set_state(CalculationStates.GET_NAME)
    await q.message.edit_reply_markup(reply_markup=None)
    await q.message.answer("Оформление заявки.\n\nКак вас зовут?", reply_markup=reply_cancel_only())


@router.callback_query(F.data == "calc:request")
async def request(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _restore(state, q.from_user.id)
    cart = await _ensure_current_in_cart(state)
    if cart:
        await _persist(state, q.from_user.id)
    await state.set_state(CalculationStates.GET_NAME)
    try: await q.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await q.message.answer("Оформление заявки.\n\nКак вас зовут?", reply_markup=reply_cancel_only())


@router.message(CalculationStates.GET_NAME)
async def name(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text): return await show_builder(m, state, reset_history=True)
    if not m.text or len(m.text.strip()) < 2: return await m.answer("Введите имя.", reply_markup=reply_cancel_only())
    await state.update_data(customer_name=m.text.strip()); await _persist(state, m.from_user.id)
    await state.set_state(CalculationStates.GET_PHONE)
    await m.answer("Телефон — кнопка или текстом:", reply_markup=reply_nav_keyboard(with_contact=True))


@router.message(CalculationStates.GET_PHONE, F.contact)
async def phone_c(m: Message, state: FSMContext):
    await state.update_data(phone=m.contact.phone_number); await _persist(state, m.from_user.id); await state.set_state(CalculationStates.GET_ADDRESS)
    await m.answer("Адрес объекта или «-»:", reply_markup=reply_cancel_only())


@router.message(CalculationStates.GET_PHONE)
async def phone_t(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text):
        await state.set_state(CalculationStates.GET_NAME); return await m.answer("Как вас зовут?", reply_markup=reply_cancel_only())
    digits = "".join(ch for ch in (m.text or "") if ch.isdigit())
    if len(digits) < 10: return await m.answer("Нужен номер из 10+ цифр.", reply_markup=reply_nav_keyboard(with_contact=True))
    await state.update_data(phone=m.text.strip()); await _persist(state, m.from_user.id); await state.set_state(CalculationStates.GET_ADDRESS)
    await m.answer("Адрес объекта или «-»:", reply_markup=reply_cancel_only())


@router.message(CalculationStates.GET_ADDRESS)
async def address(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text):
        await state.set_state(CalculationStates.GET_PHONE); return await m.answer("Телефон:", reply_markup=reply_nav_keyboard(with_contact=True))
    addr = (m.text or "").strip(); addr = "" if addr == "-" else addr
    await state.update_data(address=addr); await _persist(state, m.from_user.id); await state.set_state(CalculationStates.GET_PHOTO)
    await m.answer("Можете прислать <b>фото проёма</b> или пропустить.", parse_mode="HTML", reply_markup=kb([("⏭ Пропустить", "calc:skip_photo"), ("❌ Отмена", "nav:home")], cols=2))


@router.callback_query(F.data == "calc:skip_photo")
async def skip_photo(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _finish_request(q.message, state, q.from_user.id, q.bot)


@router.message(CalculationStates.GET_PHOTO, F.photo)
async def got_photo(m: Message, state: FSMContext):
    await state.update_data(photo_file_id=m.photo[-1].file_id); await _persist(state, m.from_user.id); await _finish_request(m, state, m.from_user.id, m.bot)


@router.message(CalculationStates.GET_PHOTO)
async def photo_other(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    await m.answer("Пришлите фото или нажмите «Пропустить».", reply_markup=kb([("⏭ Пропустить", "calc:skip_photo"), ("🏠 Меню", "nav:home")], cols=2))


@router.callback_query(F.data == "calc:measure")
async def measure_start(q: CallbackQuery, state: FSMContext):
    await q.answer(); await _restore(state, q.from_user.id)
    # Если есть активный расчёт/корзина, сразу сохраним текущую конструкцию при оформлении.
    await _ensure_current_in_cart(state)
    special = any((x.get("product") or {}).get("construction_type") == "glass_unit" for x in list((await state.get_data()).get("cart") or []))
    title = "📏 <b>Замер — 500 ₽</b>" if special else "📏 <b>Бесплатный замер</b>"
    await state.set_state(CalculationStates.MEASURE_NAME); await _persist(state, q.from_user.id)
    try: await q.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await q.message.answer(title + "\n\nКак вас зовут?", parse_mode="HTML", reply_markup=reply_cancel_only())


@router.message(CalculationStates.MEASURE_NAME)
async def measure_name(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if not m.text or len(m.text.strip()) < 2: return await m.answer("Введите имя.", reply_markup=reply_cancel_only())
    await state.update_data(customer_name=m.text.strip()); await state.set_state(CalculationStates.MEASURE_PHONE); await _persist(state, m.from_user.id)
    await m.answer("Телефон — кнопка или текстом:", reply_markup=reply_nav_keyboard(with_contact=True))


@router.message(CalculationStates.MEASURE_PHONE, F.contact)
async def measure_phone_c(m: Message, state: FSMContext):
    await state.update_data(phone=m.contact.phone_number); await state.set_state(CalculationStates.MEASURE_ADDRESS); await _persist(state, m.from_user.id)
    await m.answer("Адрес объекта:", reply_markup=reply_cancel_only())


@router.message(CalculationStates.MEASURE_PHONE)
async def measure_phone_t(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text):
        await state.set_state(CalculationStates.MEASURE_NAME); return await m.answer("Как вас зовут?", reply_markup=reply_cancel_only())
    digits = "".join(ch for ch in (m.text or "") if ch.isdigit())
    if len(digits) < 10: return await m.answer("Нужен номер из 10+ цифр.", reply_markup=reply_nav_keyboard(with_contact=True))
    await state.update_data(phone=m.text.strip()); await state.set_state(CalculationStates.MEASURE_ADDRESS); await _persist(state, m.from_user.id)
    await m.answer("Адрес объекта:", reply_markup=reply_cancel_only())


@router.message(CalculationStates.MEASURE_ADDRESS)
async def measure_address(m: Message, state: FSMContext):
    if _is_cancel_text(m.text) or _is_menu_text(m.text): return await _goto_home(m, state)
    if _is_back_text(m.text):
        await state.set_state(CalculationStates.MEASURE_PHONE); return await m.answer("Телефон:", reply_markup=reply_nav_keyboard(with_contact=True))
    await state.update_data(address=(m.text or "").strip()); await _finish_measure_request(m, state, m.from_user.id, m.bot)


async def _finish_measure_request(m: Message, state: FSMContext, user_id: int, bot: Bot):
    data = await _restore(state, user_id)
    cart = list(data.get("cart") or [])
    product_total = sum((Decimal(x.get("total", "0")) for x in cart), Decimal("0"))
    # 500 ₽ только для замера стеклопакетов или москитных сеток.
    measure_fee = measurement_fee_for_cart(cart)
    total = product_total + measure_fee
    payload = {"type": "measure", "cart": cart, "estimate": data.get("estimate") or {}, "measure_fee": str(measure_fee)}
    dedupe = _dedupe(payload, data.get("customer_name", ""), data.get("phone", ""), data.get("address", ""))
    duplicate = db().recent_duplicate(user_id, dedupe)
    if duplicate:
        request_id = duplicate
    else:
        request_id = db().save_request(user_id, data.get("customer_name", ""), data.get("phone", ""), json.dumps(payload, ensure_ascii=False), str(total), address=data.get("address", ""), status="measurer", dedupe_key=dedupe)
        await _notify_manager(bot, _manager_measure_text(request_id, data, cart, total, user_id))
        await _notify_manager_controls(bot, request_id)
    db().clear_draft(user_id)
    await state.clear()
    measure_label = fmt_money(measure_fee) if measure_fee else "бесплатно"
    await m.answer(f"✅ <b>Заявка на замер принята</b>\n\n№{request_id}\nЗамер: <b>{measure_label}</b>\nКлиентская сумма расчёта: <b>{fmt_money(total)}</b>\n\nМенеджер свяжется с вами.", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await m.answer("Что дальше?", reply_markup=kb([("🧮 Ещё расчёт", "calc:start"), ("📋 Мои заявки", "nav:history"), ("🏠 Меню", "nav:home")], cols=2))


def _dedupe(payload: dict, name: str, phone: str, address: str) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "|" + name + "|" + phone + "|" + address
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _finish_request(m: Message, state: FSMContext, user_id: int, bot: Bot):
    data = await _restore(state, user_id)
    cart = list(data.get("cart") or [])
    if not cart and data.get("construction_type"):
        cart = await _ensure_current_in_cart(state)
    est = data.get("estimate") or {}
    if not cart and est:
        cart = [{"product": _product_fields(data), "title": est.get("title", "Расчёт"), "total": str(est.get("total", "0")), "items": est.get("items", [])}]
    product_total = sum((Decimal(x.get("total", "0")) for x in cart), Decimal("0"))
    # 500 ₽ только для замера стеклопакетов или москитных сеток.
    measure_fee = measurement_fee_for_cart(cart)
    total = product_total + measure_fee
    payload = {"cart": cart, "estimate": est, "address": data.get("address", ""), "photo_file_id": data.get("photo_file_id"), "measure_fee": str(measure_fee)}
    dedupe = _dedupe(payload, data.get("customer_name", ""), data.get("phone", ""), data.get("address", ""))
    duplicate = db().recent_duplicate(user_id, dedupe)
    if duplicate:
        request_id = duplicate
    else:
        request_id = db().save_request(user_id, data.get("customer_name", ""), data.get("phone", ""), json.dumps(payload, ensure_ascii=False), str(total), address=data.get("address", ""), status="new", dedupe_key=dedupe)
        await _notify_manager(bot, _manager_order_text(request_id, data.get("customer_name", ""), data.get("phone", ""), data.get("address", ""), str(total), cart, user_id, measure_fee))
        await _notify_manager_controls(bot, request_id)
        if data.get("photo_file_id"):
            await _notify_manager(bot, f"📷 Фото проёма к заявке №{request_id}", data.get("photo_file_id"))
    db().clear_draft(user_id)
    await state.clear()
    measure_label = fmt_money(measure_fee) if measure_fee else "бесплатно"
    await m.answer(f"✅ <b>Заявка принята</b>\n\n№{request_id}\nРасчёт: <b>{fmt_money(product_total)}</b>\nЗамер: <b>{measure_label}</b>\nИтого заявки: <b>{fmt_money(total)}</b>\n\nМенеджер свяжется с вами.", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await m.answer("Что дальше?", reply_markup=kb([("🧮 Ещё расчёт", "calc:start"), ("📋 Мои заявки", "nav:history"), ("🏠 Меню", "nav:home")], cols=2))


def _product_manager_details(item: dict) -> str:
    product = item.get("product") or {}
    ct = product.get("construction_type")
    if ct == "window":
        cfg, _ = _friendly_config(product.get("sash_configuration") or product.get("opening"))
        return f"Схема: {escape(cfg)}\nРазмер: {product.get('width_mm', '?')} × {product.get('height_mm', '?')} мм\nПрофиль: {escape(_profile_label(product.get('profile')))}\nСтеклопакет: {escape(_label_glass(product.get('glass')))}"
    if ct == "balcony":
        return f"Окно: {product.get('window_width_mm', '?')} × {product.get('window_height_mm', '?')} мм\nДверь: {product.get('door_width_mm', '?')} × {product.get('door_height_mm', '?')} мм\nПрофиль: {escape(_profile_label(product.get('profile')))}\nСтеклопакет: {escape(_label_glass(product.get('glass')))}"
    if ct == "glass_unit":
        return f"Стеклопакет отдельно: {product.get('width_mm', '?')} × {product.get('height_mm', '?')} мм\nСтеклопакет: {escape(_label_glass(product.get('glass')))}"
    return f"Размер: {product.get('width_mm', '?')} × {product.get('height_mm', '?')} мм\nПрофиль: {escape(_profile_label(product.get('profile')))}\nСтеклопакет: {escape(_label_glass(product.get('glass')))}"


def _manager_product_details_for_history(item: dict) -> str:
    return _product_manager_details(item)


def _manager_order_text(request_id: int, name: str, phone: str, address: str, total: str, cart: list[dict], user_id: int, measure_fee: Decimal) -> str:
    lines = [f"🆕 <b>ЗАЯВКА №{request_id}</b>", "Статус: <b>🆕 Новая</b>", "", f"👤 <b>{escape(name) or '—'}</b>", f"Телефон: {escape(phone) or '—'}", f"Адрес: {escape(address) or '—'}", f"Telegram ID: <code>{user_id}</code>", "", "🧾 <b>Состав заказа</b>"]
    if not cart:
        lines.append("— состав не указан")
    for i, item in enumerate(cart, 1):
        lines.append(f"\n<b>{i}. {escape(item.get('title', 'Изделие'))}</b> — <b>{fmt_money(item.get('total', '0'))}</b>")
        details = _product_manager_details(item)
        if details: lines.append(details)
        for item_name, price in item.get("items", []): lines.append(f"• {escape(str(item_name))}: {fmt_money(price)}")
    measure_label = "бесплатно" if measure_fee == 0 else fmt_money(measure_fee)
    lines += ["", f"📏 Замер: <b>{measure_label}</b>", "────────────", f"💰 <b>ИТОГО: {fmt_money(total)}</b>", "Монтаж 17% уже включает демонтаж старых конструкций."]
    return "\n".join(lines)


def _manager_measure_text(request_id: int, data: dict, cart: list[dict], total: Decimal, user_id: int) -> str:
    return _manager_order_text(request_id, data.get("customer_name", ""), data.get("phone", ""), data.get("address", ""), str(total), cart, user_id, Decimal("0.00"))


async def _notify_manager_controls(bot: Bot, request_id: int) -> None:
    try:
        cid = int(os.getenv("MANAGER_CHAT_ID", "0"))
    except ValueError:
        return
    if not cid:
        return
    try:
        await bot.send_message(cid, "Управление статусом заявки:", reply_markup=_manager_status_keyboard(request_id))
    except Exception:
        pass


async def _send_manager_text(bot: Bot, chat_id: int, text: str, photo_file_id: str | None = None) -> None:
    chunks = split_html_message(text)
    if photo_file_id:
        # Подпись фото держим короткой: основной HTML-текст отправляется отдельно,
        # поэтому длинное имя/адрес не может оборвать HTML-тег в caption.
        await bot.send_photo(chat_id, photo_file_id, caption="📷 Фото к заявке", parse_mode="HTML")
        for chunk in chunks:
            await bot.send_message(chat_id, chunk, parse_mode="HTML")
    else:
        for chunk in chunks:
            await bot.send_message(chat_id, chunk, parse_mode="HTML")


async def _notify_manager(bot: Bot, text: str, photo_file_id: str | None = None) -> None:
    try:
        cid = int(os.getenv("MANAGER_CHAT_ID", "0"))
    except ValueError:
        return
    if not cid:
        return
    try:
        await _send_manager_text(bot, cid, text, photo_file_id)
    except Exception:
        pass


def _manager_status_keyboard(request_id: int):
    return kb([
        ("👁 Открыть заявку", f"mgr:view:{request_id}"),
        ("🆕 Новая", f"mgr:status:{request_id}:new"),
        ("📏 Замер", f"mgr:status:{request_id}:measurer"),
        ("📋 КП", f"mgr:status:{request_id}:quote"),
        ("✅ Закрыта", f"mgr:status:{request_id}:done"),
    ], cols=2)


@router.callback_query(F.data.startswith("mgr:view:"))
async def manager_view(q: CallbackQuery, state: FSMContext):
    try: rid = int((q.data or "").rsplit(":", 1)[1]); cid = int(os.getenv("MANAGER_CHAT_ID", "0"))
    except ValueError: return await q.answer("Некорректная заявка", show_alert=True)
    if not cid or not q.message or q.message.chat.id != cid: return await q.answer("Доступно только менеджеру", show_alert=True)
    row = db().get_request(rid)
    if not row: return await q.answer("Заявка не найдена", show_alert=True)
    _, user_id, name_, phone, config_json, total, status, address_, _ = row
    try: payload = json.loads(config_json or "{}")
    except (TypeError, json.JSONDecodeError): payload = {}
    text = _manager_order_text(rid, name_ or "", phone or "", address_ or "", str(total), payload.get("cart") or [], user_id, Decimal(payload.get("measure_fee", "0")))
    await q.answer("Заявка открыта")
    chunks = split_html_message(text)
    for index, chunk in enumerate(chunks):
        await q.message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=_manager_status_keyboard(rid) if index == len(chunks) - 1 else None,
        )


@router.callback_query(F.data.startswith("mgr:status:"))
async def manager_status(q: CallbackQuery, state: FSMContext):
    parts = (q.data or "").split(":")
    if len(parts) != 4: return await q.answer("Некорректная команда", show_alert=True)
    try: cid = int(os.getenv("MANAGER_CHAT_ID", "0")); rid = int(parts[2])
    except ValueError: return await q.answer("Настройки менеджера не заданы", show_alert=True)
    if not cid or not q.message or q.message.chat.id != cid: return await q.answer("Доступно только менеджеру", show_alert=True)
    status = parts[3]
    if status not in STATUS_LABELS: return await q.answer("Неизвестный статус", show_alert=True)
    if not db().get_request(rid): return await q.answer("Заявка не найдена", show_alert=True)
    db().set_status(rid, status)
    await q.answer(f"Статус: {STATUS_LABELS[status]}")
    try: await q.message.edit_reply_markup(reply_markup=_manager_status_keyboard(rid))
    except Exception: pass
