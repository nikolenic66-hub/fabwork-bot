from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from html import escape

from flask import Flask, jsonify
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.navigation import MAIN_MENU_TEXT, main_menu
from handlers.manager import manager_chat_ids
from states import ManagerStates
from storage.db import Database

from handlers.calculation import router as calculation_router
from handlers.services import router as services_router

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fabrika_okon")

app = Flask(__name__)


@app.get("/")
def root():
    return "OK", 200


@app.get("/health")
def health():
    return jsonify(status="ok")


def run_health():
    app.run(
        host=os.getenv("HEALTH_HOST", "0.0.0.0"),
        port=int(os.getenv("HEALTH_PORT", "8080")),
        use_reloader=False,
    )


router = Router(name="main")


def menu():
    return main_menu()


def manager_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _show_main_menu_after_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    # Нельзя одновременно передать ReplyKeyboardRemove и inline-клавиатуру
    # в одном сообщении. Раньше мы сначала отправляли Remove, а затем
    # пытались добавить inline-клавиатуру отдельным редактированием; Telegram
    # мог отклонить такой edit, и пользователь получал меню без кнопок.
    # Поэтому главное меню всегда отправляем сразу с общей inline-клавиатурой.
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(
        MAIN_MENU_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu(user_id in manager_chat_ids()),
    )



@router.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "🏭 <b>Фабрика Окон</b>\n"
        "<i>Рассчитайте примерную стоимость окна, двери или балконного блока за несколько шагов.</i>\n\n"
        "Сначала выберите конструкцию и размер — затем бот покажет ориентировочную цену.\n\n"
        "⚠️ <b>Цена ориентировочная.</b> Точная стоимость определяется после замера.",
        reply_markup=main_menu(bool(m.from_user and m.from_user.id in manager_chat_ids())),
    )


@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def help_cmd(event: Message | CallbackQuery):
    text = (
        "ℹ️ <b>Как пользоваться</b>\n\n"
        "1. Выберите тип конструкции\n"
        "2. В конструкторе меняйте любые параметры\n"
        "3. Сумма обновляется на экране (≈)\n"
        "4. «Рассчитать» или «В корзину» для нескольких окон\n"
        "5. Заявка: имя, телефон, адрес, фото проёма\n\n"
        "Монтаж 17% уже в итоге. Точную смету даст замерщик.\n"
        "/cancel — отмена."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu(bool(event.from_user and event.from_user.id in manager_chat_ids())))
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=main_menu(bool(event.from_user and event.from_user.id in manager_chat_ids())))


@router.message(F.text.in_({"❌ Отмена", "Отмена", "❌", "cancel"}))
async def reply_cancel(m: Message, state: FSMContext):
    """Cancel any active form and return to the single main-menu message."""
    await _show_main_menu_after_reply(m, state)


@router.message(F.text.in_({"🏠 Меню", "Меню", "home", "в меню"}))
async def reply_menu(m: Message, state: FSMContext):
    """Return from any text-input step to the single main-menu message."""
    await _show_main_menu_after_reply(m, state)


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    # Сбрасываем текущий шаг, но не удаляем сохранённый «Мой расчёт».
    await state.clear()
    await m.answer("Текущий шаг отменён. Сохранённые расчёты останутся в «Мой расчёт».", reply_markup=main_menu(bool(m.from_user and m.from_user.id in manager_chat_ids())))


@router.callback_query(F.data == "manager")
async def manager_cb(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ManagerStates.NAME)
    await state.update_data(manager_source="main_menu")
    await q.message.edit_text(
        "💬 <b>Заявка менеджеру</b>\n\nКак вас зовут?",
        parse_mode="HTML",
        reply_markup=None,
    )
    await q.message.answer(
        "Введите имя.",
        reply_markup=manager_reply_keyboard(),
    )


@router.message(ManagerStates.NAME)
async def manager_name(m: Message, state: FSMContext):
    if m.text and m.text.strip() in {"❌ Отмена", "Отмена", "❌", "cancel", "🏠 Меню", "Меню", "home", "в меню"}:
        return await _show_main_menu_after_reply(m, state)
    name = (m.text or "").strip()
    if len(name) < 2:
        return await m.answer("Введите имя.", reply_markup=manager_reply_keyboard())
    await state.update_data(customer_name=name)
    await state.set_state(ManagerStates.PHONE)
    await m.answer("Телефон — кнопкой или текстом:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)], [KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    ))


async def _finish_manager_lead(m: Message, state: FSMContext, phone: str):
    data = await state.get_data()
    user_id = m.from_user.id if m.from_user else 0
    name = data.get("customer_name", "")
    username = getattr(m.from_user, "username", None) if m.from_user else None
    profile = f"tg://user?id={user_id}" if user_id else ""
    payload = {
        "type": "manager_contact",
        "source": data.get("manager_source", "main_menu"),
        "telegram_username": username or "",
        "telegram_profile": profile,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "|" + name + "|" + phone
    dedupe = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    database = Database(os.getenv("DATABASE_PATH", "/data/bot.db"))
    try:
        request_id, created = database.save_request_atomic(
            user_id, name, phone, json.dumps(payload, ensure_ascii=False), "0.00",
            status="new", dedupe_key=dedupe,
        )
    except Exception:
        log.exception("Failed to save manager contact request")
        await m.answer(
            "⚠️ Не удалось сохранить заявку. Попробуйте ещё раз позже.",
            reply_markup=manager_reply_keyboard(),
        )
        return

    manager_ids = manager_chat_ids()
    if created:
        if not manager_ids:
            log.error("No manager chat IDs are configured")
            await state.clear()
            await m.answer(
                f"⚠️ Заявка №{request_id} сохранена, но уведомление менеджеру временно не доставлено.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        username_text = f"@{username}" if username else "не указан"
        safe_name = escape(name)
        safe_phone = escape(phone)
        manager_text = (
            f"💬 <b>ЗАЯВКА МЕНЕДЖЕРУ №{request_id}</b>\n\n"
            f"Источник: <b>Кнопка «Связаться с менеджером»</b>\n"
            f"👤 <b>{safe_name}</b>\n"
            f"Телефон: <b>{safe_phone}</b>\n"
            f"Telegram: {escape(username_text)}\n"
            f"Профиль: <a href=\"{profile}\">Открыть профиль</a>"
        )
        failed = False
        for manager_id in manager_ids:
            try:
                await m.bot.send_message(
                    manager_id,
                    manager_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardBuilder().button(
                        text="👁 Открыть заявку", callback_data=f"mgr:view:{request_id}"
                    ).as_markup(),
                )
                await m.bot.send_message(
                    manager_id,
                    "📋 Управление заявками:",
                    reply_markup=InlineKeyboardBuilder().button(
                        text="📋 Заявки менеджера", callback_data="mgr:menu"
                    ).as_markup(),
                )
            except Exception:
                failed = True
                log.exception("Failed to notify manager %s about request %s", manager_id, request_id)
        if failed:
            await m.answer(
                "⚠️ Заявка сохранена, но уведомление менеджеру временно не доставлено. "
                "Менеджер сможет увидеть её в списке заявок.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

    await state.clear()
    await m.answer(
        "Спасибо! <b>Менеджер свяжется с вами</b> в рабочее время.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await m.answer("Что дальше?", reply_markup=main_menu(bool(m.from_user and m.from_user.id in manager_chat_ids())))


@router.message(ManagerStates.PHONE, F.contact)
async def manager_phone_contact(m: Message, state: FSMContext):
    await _finish_manager_lead(m, state, m.contact.phone_number)


@router.message(ManagerStates.PHONE)
async def manager_phone_text(m: Message, state: FSMContext):
    if m.text and m.text.strip() in {"❌ Отмена", "Отмена", "❌", "cancel", "🏠 Меню", "Меню", "home", "в меню"}:
        return await _show_main_menu_after_reply(m, state)
    digits = "".join(ch for ch in (m.text or "") if ch.isdigit())
    if len(digits) < 10:
        return await m.answer("Нужен номер из 10+ цифр.", reply_markup=manager_reply_keyboard())
    await _finish_manager_lead(m, state, (m.text or "").strip())


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан")
    proxy = os.getenv("BOT_PROXY")
    if proxy:
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(proxy=proxy)
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
    else:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.include_router(calculation_router)
    dp.include_router(services_router)
    threading.Thread(target=run_health, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
