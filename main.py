from __future__ import annotations

import asyncio
import logging
import os
import threading

from flask import Flask, jsonify
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from states import ManagerStates

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
    b = InlineKeyboardBuilder()
    b.button(text="🧮 Рассчитать стоимость", callback_data="calc:start")
    b.button(text="📏 Заказать замер", callback_data="calc:measure")
    b.button(text="🛒 Мой расчёт", callback_data="calc:cart_menu")
    b.button(text="📋 Мои заявки", callback_data="nav:history")
    b.button(text="💬 Связаться с менеджером", callback_data="manager")
    b.button(text="🔧 Сервис", callback_data="svc:menu")
    b.button(text="ℹ️ Как это работает", callback_data="help")
    b.adjust(2)
    return b.as_markup()


@router.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "🏭 <b>Фабрика Окон</b>\n"
        "<i>Рассчитайте примерную стоимость окна, двери или балконного блока за несколько шагов.</i>\n\n"
        "Сначала выберите конструкцию и размер — затем бот покажет цену с учётом монтажа 17%.\n\n"
        "⚠️ <b>Цена ориентировочная.</b> Точная стоимость определяется после замера.",
        reply_markup=menu(),
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
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=menu())
    else:
        await event.answer(text, reply_markup=menu())


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    # Сбрасываем текущий шаг, но не удаляем сохранённый «Мой расчёт».
    await state.clear()
    await m.answer("Текущий шаг отменён. Сохранённые расчёты останутся в «Мой расчёт».", reply_markup=menu())


@router.callback_query(F.data == "manager")
async def manager_cb(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ManagerStates.PHONE)
    await state.update_data(manager_message_id=q.message.message_id, manager_chat_id=q.message.chat.id)
    markup = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)],
                  [KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await q.message.edit_text(
        "💬 <b>Оставить заявку менеджеру</b>\n\n"
        "Укажите ваш номер телефона. Менеджер получит ваши имя, номер и ссылку на Telegram-профиль и свяжется с вами.",
        parse_mode="HTML", reply_markup=None,
    )
    await q.message.answer("Номер телефона — кнопкой или текстом:", reply_markup=markup)


async def _finish_manager_lead(m: Message, state: FSMContext, phone: str):
    data = await state.get_data()
    user = m.from_user
    name = " ".join(x for x in [user.first_name, user.last_name] if x).strip() or "Без имени"
    username = f"@{user.username}" if user.username else "не указан"
    profile = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    manager_id = int(os.getenv("MANAGER_CHAT_ID", "0") or 0)
    source = "Кнопка «Связаться с менеджером»"
    text = (
        "💬 <b>Новая заявка менеджеру</b>\n\n"
        f"👤 Имя: <b>{name}</b>\n"
        f"📞 Телефон: <b>{phone}</b>\n"
        f"📍 Источник: <b>{source}</b>\n"
        f"🔗 Telegram: {profile}\n"
        f"👤 Username: {username}"
    )
    if manager_id:
        try:
            await m.bot.send_message(manager_id, text, parse_mode="HTML")
        except Exception as exc:
            log.exception("Не удалось отправить заявку менеджеру: %s", exc)
    await state.clear()
    try:
        mid = int(data.get("manager_message_id"))
        await m.bot.edit_message_text(
            chat_id=m.chat.id, message_id=mid,
            text="💬 <b>Спасибо!</b>\n\nМенеджер получил вашу заявку и свяжется с вами в ближайшее время.",
            parse_mode="HTML", reply_markup=menu(),
        )
    except Exception:
        await m.answer("💬 <b>Спасибо!</b> Менеджер свяжется с вами в ближайшее время.", parse_mode="HTML", reply_markup=menu())
    await m.answer("", reply_markup=ReplyKeyboardRemove())


@router.message(ManagerStates.PHONE, F.contact)
async def manager_phone_contact(m: Message, state: FSMContext):
    await _finish_manager_lead(m, state, m.contact.phone_number)


@router.message(ManagerStates.PHONE)
async def manager_phone_text(m: Message, state: FSMContext):
    if (m.text or "").strip().lower() in {"❌ отмена", "отмена", "cancel"}:
        await state.clear()
        await m.answer("Заявка отменена.", reply_markup=menu())
        await m.answer("", reply_markup=ReplyKeyboardRemove())
        return
    digits = "".join(ch for ch in (m.text or "") if ch.isdigit())
    if len(digits) < 10:
        await m.answer("Нужен номер из 10+ цифр.", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)], [KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True, one_time_keyboard=True,
        ))
        return
    await _finish_manager_lead(m, state, m.text.strip())


@router.callback_query(F.data == "history")
async def history_cb(q: CallbackQuery):
    await q.answer()
    try:
        from storage.db import Database
        db = Database(os.getenv("DATABASE_PATH", "/data/bot.db"))
        rows = db.history(q.from_user.id if q.from_user else 0, limit=8)
    except Exception:
        rows = []
    if not rows:
        await q.message.answer("Пока нет заявок.", reply_markup=menu())
        return
    labels = {"new": "🆕", "measurer": "📏", "quote": "📋", "done": "✅"}
    lines = ["📋 <b>Ваши заявки</b>\n"]
    for rid, total, status, created in rows:
        st = labels.get(status or "new", "🆕")
        lines.append(f"{st} №{rid} — {total} ₽ — {created}")
    await q.message.answer("\n".join(lines), reply_markup=menu())


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
