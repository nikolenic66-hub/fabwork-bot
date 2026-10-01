from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import logging
import os
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from pricing.price_list import (
    SERVICE_PRICES,
    money,
    service_adjust,
    service_glass_replace,
    service_install_visit,
    service_measure,
    service_mosquito_measure,
    service_seal,
)
from states import ServiceStates
from storage.db import Database

router = Router(name="services")
log = logging.getLogger(__name__)


def kb(rows: list[tuple[str, str]], cols: int = 2):
    b = InlineKeyboardBuilder()
    for text, data in rows:
        b.button(text=text, callback_data=data)
    b.adjust(cols)
    return b.as_markup()


def fmt(v: Decimal | str) -> str:
    if isinstance(v, str):
        try:
            v = Decimal(v)
        except Exception:
            return v
    return f"{v:,.2f}".replace(",", "\u00a0") + " ₽"


def nav():
    return [("⬅️ Назад", "svc:menu"), ("🏠 Меню", "nav:home")]




async def _render_service(target, state: FSMContext, text: str, markup=None):
    """Render one service screen without hiding Telegram edit errors."""
    data = await state.get_data()
    msg = target.message if isinstance(target, CallbackQuery) else target
    mid = data.get("service_message_id")
    chat_id = data.get("service_chat_id")
    if mid and chat_id:
        try:
            await msg.bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(mid),
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            log.warning("Service message edit rejected: %s", exc)
        except Exception:
            log.exception("Unexpected service message edit failure")

    if isinstance(target, CallbackQuery):
        try:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
            await state.update_data(service_message_id=msg.message_id, service_chat_id=msg.chat.id)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await state.update_data(service_message_id=msg.message_id, service_chat_id=msg.chat.id)
                return
            log.warning("Initial service callback edit rejected: %s", exc)
        except Exception:
            log.exception("Unexpected initial service callback edit failure")

    sent = await msg.answer(text, parse_mode="HTML", reply_markup=markup)
    await state.update_data(service_message_id=sent.message_id, service_chat_id=sent.chat.id)


def menu_text() -> str:
    return (
        "🔧 <b>Сервис и ремонт</b>\n\n"
        "📏 Замер окон, дверей и балконных блоков — <b>бесплатно</b>\n"
        f"🦟 Замер москитных сеток — <b>{fmt(SERVICE_PRICES['special_measure'])}</b>\n"
        f"🛠 Монтаж стеклопакета — <b>{fmt(SERVICE_PRICES['install_visit'])}</b>\n"
        f"🔲 Замена стеклопакета: 24 мм — <b>{fmt(SERVICE_PRICES['glass24_replace'])}</b> / м²; 32 мм — <b>{fmt(SERVICE_PRICES['glass32_replace'])}</b> / м²\n"
        f"📏 Замер стеклопакета — <b>{fmt(SERVICE_PRICES['special_measure'])}</b>\n"
        f"⚙️ Регулировка: выезд <b>{fmt(SERVICE_PRICES['adjust_visit'])}</b>\n"
        f"    окно <b>{fmt(SERVICE_PRICES['adjust_window'])}</b> · дверь <b>{fmt(SERVICE_PRICES['adjust_door'])}</b>\n"
        f"🧵 Уплотнитель: выезд <b>{fmt(SERVICE_PRICES['seal_visit'])}</b>\n"
        f"    + <b>{fmt(SERVICE_PRICES['seal_meter'])}</b> / п.м.\n\n"
        "<i>Цена ориентировочная. Итог после осмотра.</i>"
    )


@router.callback_query(F.data == "svc:menu")
async def svc_menu(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ServiceStates.MENU)
    await state.update_data(svc_title=None, svc_total=None, svc_items=None)
    await _render_service(
        q,
        state,
        menu_text(),
        kb([
            ("📏 Бесплатный замер", "svc:measure"),
            ("🦟 Замер москитных сеток — 500 ₽", "svc:mosquito_measure"),
            ("🛠 Монтаж стеклопакета 1000 ₽", "svc:install"),
            ("🔲 Замена стеклопакета", "svc:glass"),
            ("⚙️ Регулировка", "svc:adjust"),
            ("🧵 Уплотнитель", "svc:seal"),
            ("🏠 Меню", "nav:home"),
        ]),
    )


@router.callback_query(F.data == "svc:measure")
async def svc_measure(q: CallbackQuery, state: FSMContext):
    await q.answer()
    total = service_measure()
    await state.update_data(svc_title="Замер окон / дверей / балконного блока", svc_total=str(total), svc_items=[("Выезд замерщика", str(total))])
    await _offer(q, state, "📏 Бесплатный замер", [("Выезд замерщика", total)], total)


@router.callback_query(F.data == "svc:mosquito_measure")
async def svc_mosquito_measure(q: CallbackQuery, state: FSMContext):
    await q.answer()
    total, items = service_mosquito_measure()
    await state.update_data(
        svc_title="Замер москитных сеток",
        svc_total=str(total),
        svc_items=[(n, str(p)) for n, p in items],
    )
    await _offer(q, state, "🦟 Замер москитных сеток", items, total)


@router.callback_query(F.data == "svc:install")
async def svc_install(q: CallbackQuery, state: FSMContext):
    await q.answer()
    total = service_install_visit()
    await state.update_data(svc_title="Монтаж", svc_total=str(total), svc_items=[("Монтаж / выезд", str(total))])
    await _offer(q, state, "🛠 Монтаж", [("Выезд на монтаж", total)], total)


@router.callback_query(F.data == "svc:glass")
async def svc_glass(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ServiceStates.GLASS_WIDTH)
    await state.update_data(
        svc_glass_type="32", svc_glass_qty=1, svc_glass_measure=True,
        svc_glass_install=True, svc_glass_width=None, svc_glass_height=None,
    )
    await _render_service(
        q, state,
        "🔲 <b>Замена стеклопакета</b>\n\n"
        "Укажите ширину стеклопакета в мм (например, <b>600</b>).",
        kb(nav()),
    )


@router.message(ServiceStates.GLASS_WIDTH)
async def svc_glass_width(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    try:
        width = int(raw)
        if width <= 0 or width > 5000:
            raise ValueError
    except Exception:
        return await m.answer("Введите ширину в мм, например 600.", reply_markup=kb(nav()))
    await state.update_data(svc_glass_width=width)
    await state.set_state(ServiceStates.GLASS_HEIGHT)
    await m.answer("Теперь укажите высоту стеклопакета в мм (например, <b>1200</b>).", parse_mode="HTML", reply_markup=kb(nav()))
    try:
        await m.delete()
    except Exception:
        pass


@router.message(ServiceStates.GLASS_HEIGHT)
async def svc_glass_height(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    try:
        height = int(raw)
        if height <= 0 or height > 5000:
            raise ValueError
    except Exception:
        return await m.answer("Введите высоту в мм, например 1200.", reply_markup=kb(nav()))
    await state.update_data(svc_glass_height=height)
    await state.set_state(ServiceStates.GLASS_QTY)
    await _glass_screen(m, state)
    try:
        await m.delete()
    except Exception:
        pass


async def _glass_screen(q, state: FSMContext):
    data = await state.get_data()
    glass = data.get("svc_glass_type") or "32"
    qty = int(data.get("svc_glass_qty") or 1)
    wm = bool(data.get("svc_glass_measure"))
    wi = bool(data.get("svc_glass_install"))
    width = int(data.get("svc_glass_width") or 1000)
    height = int(data.get("svc_glass_height") or 1000)
    total, items = service_glass_replace(glass, qty, wm, wi, width, height)
    lines = "\n".join(f"• {n}: <b>{fmt(p)}</b>" for n, p in items)
    await _render_service(
        q,
        state,
        f"🔲 <b>Замена стеклопакета {glass} мм</b>\n\n{lines}\n\n💰 <b>{fmt(total)}</b>",
        kb([
            ("СП 24 мм" + (" ✅" if glass == "24" else ""), "svc:g:type:24"),
            ("СП 32 мм" + (" ✅" if glass == "32" else ""), "svc:g:type:32"),
            ("− шт", "svc:g:-"),
            (f"{qty} шт", "svc:g:qty"),
            ("+ шт", "svc:g:+"),
            ("Замер 500 ₽" + (" ✅" if wm else ""), "svc:g:m"),
            ("Монтаж 1 000 ₽" + (" ✅" if wi else ""), "svc:g:i"),
            ("✅ Заявка", "svc:order"),
            *nav(),
        ]),
    )
    await state.update_data(
        svc_title=f"Замена СП {glass}",
        svc_total=str(total),
        svc_items=[(n, str(p)) for n, p in items],
    )


@router.callback_query(F.data.startswith("svc:g:"))
async def svc_g_toggle(q: CallbackQuery, state: FSMContext):
    await q.answer()
    data = await state.get_data()
    qty = int(data.get("svc_glass_qty") or 1)
    act = q.data.rsplit(":", 1)[1]
    if act in {"24", "32"} and q.data.startswith("svc:g:type:"):
        await state.update_data(svc_glass_type=act)
    elif act == "+":
        qty = min(qty + 1, 20)
    elif act == "-":
        qty = max(qty - 1, 1)
    elif act == "m":
        await state.update_data(svc_glass_measure=not data.get("svc_glass_measure"))
    elif act == "i":
        await state.update_data(svc_glass_install=not data.get("svc_glass_install"))
    await state.update_data(svc_glass_qty=qty)
    await _glass_screen(q, state)


@router.callback_query(F.data == "svc:adjust")
async def svc_adjust(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ServiceStates.ADJUST)
    await state.update_data(svc_w=1, svc_d=0)
    await _adj_screen(q, state)


async def _adj_screen(q: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    w = int(data.get("svc_w") or 0)
    d = int(data.get("svc_d") or 0)
    total, items = service_adjust(w, d)
    lines = "\n".join(f"• {n}: <b>{fmt(p)}</b>" for n, p in items)
    await _render_service(
        q,
        state,
        f"⚙️ <b>Регулировка</b>\n\n{lines}\n\n💰 <b>{fmt(total)}</b>",
        kb([
            ("Окна −", "svc:a:w-"),
            (f"Окон: {w}", "svc:a:w"),
            ("Окна +", "svc:a:w+"),
            ("Двери −", "svc:a:d-"),
            (f"Дверей: {d}", "svc:a:d"),
            ("Двери +", "svc:a:d+"),
            ("✅ Заявка", "svc:order"),
            *nav(),
        ]),
    )
    await state.update_data(
        svc_title="Регулировка",
        svc_total=str(total),
        svc_items=[(n, str(p)) for n, p in items],
    )


@router.callback_query(F.data.startswith("svc:a:"))
async def svc_a_toggle(q: CallbackQuery, state: FSMContext):
    await q.answer()
    data = await state.get_data()
    w = int(data.get("svc_w") or 0)
    d = int(data.get("svc_d") or 0)
    act = q.data.rsplit(":", 1)[1]
    if act == "w+":
        w = min(w + 1, 30)
    elif act == "w-":
        w = max(w - 1, 0)
    elif act == "d+":
        d = min(d + 1, 20)
    elif act == "d-":
        d = max(d - 1, 0)
    await state.update_data(svc_w=w, svc_d=d)
    await _adj_screen(q, state)


@router.callback_query(F.data == "svc:seal")
async def svc_seal(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(ServiceStates.SEAL_METERS)
    await _render_service(
        q,
        state,
        "🧵 <b>Замена уплотнителя</b>\n\n"
        "Напишите длину в погонных метрах (например <code>12</code> или <code>8.5</code>).\n"
        f"Выезд {fmt(SERVICE_PRICES['seal_visit'])} + {fmt(SERVICE_PRICES['seal_meter'])}/п.м.",
        kb(nav()),
    )


@router.message(ServiceStates.SEAL_METERS)
async def svc_seal_m(m: Message, state: FSMContext):
    raw = (m.text or "").replace(",", ".").strip()
    try:
        meters = Decimal(raw)
        if meters <= 0 or meters > 200:
            raise ValueError
    except Exception:
        return await m.answer("Введите число метров, например 10.", reply_markup=kb(nav()))
    total, items = service_seal(meters)
    lines = "\n".join(f"• {n}: <b>{fmt(p)}</b>" for n, p in items)
    await state.update_data(
        svc_title=f"Уплотнитель {meters} п.м.",
        svc_total=str(total),
        svc_items=[(n, str(p)) for n, p in items],
    )
    await _render_service(
        m,
        state,
        f"🧵 <b>Уплотнитель</b>\n\n{lines}\n\n💰 <b>{fmt(total)}</b>",
        kb([("✅ Заявка", "svc:order"), *nav()]),
    )
    try:
        await m.delete()
    except Exception:
        pass


async def _offer(q: CallbackQuery, state: FSMContext, title: str, items: list[tuple[str, Decimal]], total: Decimal):
    lines = "\n".join(f"• {escape(str(n))}: <b>{fmt(p) if p else 'бесплатно'}</b>" for n, p in items)
    total_label = "бесплатно" if total == 0 else fmt(total)
    await _render_service(
        q,
        state,
        f"{title}\n\n{lines}\n\n💰 <b>{total_label}</b>\n"
        "<i>Ориентир. Итог после осмотра.</i>",
        kb([("✅ Оставить заявку", "svc:order"), *nav()]),
    )


@router.callback_query(F.data == "svc:order")
async def svc_order(q: CallbackQuery, state: FSMContext):
    await q.answer()
    data = await state.get_data()
    if not data.get("svc_title") or data.get("svc_total") is None:
        return await q.answer("Сначала выберите услугу", show_alert=True)
    await state.set_state(ServiceStates.NAME)
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.message.answer("Как вас зовут?")


@router.message(ServiceStates.NAME)
async def svc_name(m: Message, state: FSMContext):
    if not m.text or len(m.text.strip()) < 2:
        return await m.answer("Введите имя.")
    await state.update_data(customer_name=m.text.strip())
    await state.set_state(ServiceStates.PHONE)
    await m.answer("Телефон:")


@router.message(ServiceStates.PHONE)
async def svc_phone(m: Message, state: FSMContext):
    phone = ""
    if m.contact:
        phone = m.contact.phone_number
    else:
        digits = "".join(ch for ch in (m.text or "") if ch.isdigit())
        if len(digits) < 10:
            return await m.answer("Нужен номер из 10+ цифр.")
        phone = (m.text or "").strip()
    await state.update_data(phone=phone)
    data = await state.get_data()
    title = data.get("svc_title") or "Сервис"
    total = data.get("svc_total") or "0"
    items = data.get("svc_items") or []
    lines = "\n".join(f"• {n}: {p} ₽" for n, p in items)
    safe_name = escape(str(data.get("customer_name", "")))
    safe_phone = escape(phone)
    text = (
        f"🔧 <b>Заявка на сервис</b>\n"
        f"{escape(str(title))}\n{lines}\n"
        f"Итого: <b>{fmt(total)}</b>\n"
        f"Имя: {safe_name or '—'}\n"
        f"Тел: {safe_phone or '—'}\n"
        f"User: {m.from_user.id if m.from_user else '—'}"
    )
    request_id = None
    created = False
    try:
        db = Database(os.getenv("DATABASE_PATH", "/data/bot.db"))
        payload = {"type": "service", "title": title, "items": items}
        dedupe_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "|" + str(data.get("customer_name", "")) + "|" + phone
        dedupe = hashlib.sha256(dedupe_raw.encode("utf-8")).hexdigest()
        request_id, created = db.save_request_atomic(
            m.from_user.id if m.from_user else 0,
            data.get("customer_name", ""),
            phone,
            json.dumps(payload, ensure_ascii=False),
            str(total),
            status="new",
            dedupe_key=dedupe,
        )
    except Exception:
        log.exception("Failed to save service request")
        await m.answer(
            "⚠️ Не удалось сохранить заявку на сервис. Попробуйте ещё раз позже.",
            reply_markup=kb([("🔧 Сервис", "svc:menu"), ("🏠 Меню", "nav:home")]),
        )
        return

    if request_id:
        text = f"🆕 <b>ЗАЯВКА НА СЕРВИС №{request_id}</b>\n" + text

    manager_ok = True
    if created:
        try:
            cid = int(os.getenv("MANAGER_CHAT_ID", "0"))
            if not cid:
                raise RuntimeError("MANAGER_CHAT_ID is not configured")
            await m.bot.send_message(cid, text, parse_mode="HTML")
        except Exception:
            manager_ok = False
            log.exception("Failed to notify manager about service request %s", request_id)

    await state.clear()
    if not manager_ok:
        await m.answer(
            f"⚠️ Заявка №{request_id} сохранена, но уведомление менеджеру временно не доставлено.",
            reply_markup=kb([("🔧 Сервис", "svc:menu"), ("🏠 Меню", "nav:home")]),
        )
        return
    await m.answer(
        f"✅ Заявка принята.\n{title}\n💰 {fmt(total)}\nМенеджер свяжется с вами.",
        reply_markup=kb([
            ("🔧 Ещё услуга", "svc:menu"),
            ("🏠 Меню", "nav:home"),
        ]),
    )
