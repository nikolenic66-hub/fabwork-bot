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
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
    b.button(text="🔧 Сервис и ремонт", callback_data="svc:menu")
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
        await event.message.answer(text, reply_markup=menu())
    else:
        await event.answer(text, reply_markup=menu())


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    # Сбрасываем текущий шаг, но не удаляем сохранённый «Мой расчёт».
    await state.clear()
    await m.answer("Текущий шаг отменён. Сохранённые расчёты останутся в «Мой расчёт».", reply_markup=menu())


@router.callback_query(F.data == "manager")
async def manager_cb(q: CallbackQuery):
    await q.answer()
    await q.message.edit_text(
        "💬 <b>Связь с менеджером</b>\n\n"
        "Напишите вопрос, отправьте размеры или фото объекта — менеджер поможет сделать предварительный расчёт и ответит в рабочее время.",
        parse_mode="HTML", reply_markup=menu(),
    )


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
