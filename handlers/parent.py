"""Ota-ona nazorati: PIN-kod, kunlik vaqt, uxlash vaqti, bloklash, hisobot, kuponlar."""
import re
import time as _time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards as kb
from db import DB, age_of, hash_pin, now

router = Router()
SESSION_SECONDS = 10 * 60
_sessions: dict[int, float] = {}  # tg_id -> PIN to'g'ri kiritilgan vaqt + 10 daqiqa
_attempts: dict[int, list[float]] = {}


def unlocked(uid: int) -> bool:
    return _sessions.get(uid, 0) > _time.time()


def too_many_attempts(uid: int) -> bool:
    recent = [t for t in _attempts.get(uid, []) if t > _time.time() - 300]
    _attempts[uid] = recent
    return len(recent) >= 5


class Pin(StatesGroup):
    enter = State()
    new = State()
    confirm = State()


class SleepTime(StatesGroup):
    value = State()


PIN_RE = re.compile(r"^\d{4}$")


async def show_panel(target: Message, db: DB, uid: int, edit=False):
    p = await db.get_parent(uid)
    text = ("<b>Ota-ona nazorati</b>\n\n"
            f"Kunlik ko'rish vaqti: {p['daily_limit']} daqiqa (har bir bola uchun)\n"
            "Sozlamalarni pastdagi tugmalar bilan o'zgartiring.")
    if edit:
        await target.edit_text(text, reply_markup=kb.parent_menu(p))
    else:
        await target.answer(text, reply_markup=kb.parent_menu(p))


@router.message(F.text == kb.BTN_PARENT)
async def parent_entry(message: Message, state: FSMContext, db: DB):
    uid = message.from_user.id
    p = await db.ensure_parent(uid, message.from_user.full_name)
    if not p["pin_hash"]:
        await state.set_state(Pin.new)
        await message.answer("Ota-ona bo'limi uchun 4 xonali PIN-kod o'ylab toping va yozing "
                             "(bola bilmasin!):")
        return
    if unlocked(uid):
        await show_panel(message, db, uid)
        return
    await state.set_state(Pin.enter)
    await message.answer("PIN-kodni kiriting:")


@router.message(Pin.enter, F.text)
async def pin_enter(message: Message, state: FSMContext, db: DB):
    uid = message.from_user.id
    try:
        await message.delete()  # PIN chatda qolmasin
    except Exception:
        pass
    if too_many_attempts(uid):
        await state.clear()
        await message.answer("Juda ko'p urinish. 5 daqiqadan keyin qayta urinib ko'ring.")
        return
    p = await db.get_parent(uid)
    if hash_pin(message.text.strip()) != p["pin_hash"]:
        _attempts.setdefault(uid, []).append(_time.time())
        await message.answer("PIN noto'g'ri. Qaytadan kiriting:")
        return
    await state.clear()
    _sessions[uid] = _time.time() + SESSION_SECONDS
    await show_panel(message, db, uid)


@router.message(Pin.new, F.text)
async def pin_new(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    pin = message.text.strip()
    if not PIN_RE.match(pin):
        await message.answer("PIN 4 ta raqamdan iborat bo'lsin. Qaytadan yozing:")
        return
    await state.update_data(pin=pin)
    await state.set_state(Pin.confirm)
    await message.answer("PIN-kodni yana bir marta yozing:")


@router.message(Pin.confirm, F.text)
async def pin_confirm(message: Message, state: FSMContext, db: DB):
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    if message.text.strip() != data.get("pin"):
        await state.set_state(Pin.new)
        await message.answer("PIN-kodlar mos kelmadi. Yangi PIN-kodni qaytadan yozing:")
        return
    await state.clear()
    await db.set_parent(message.from_user.id, pin_hash=hash_pin(data["pin"]))
    _sessions[message.from_user.id] = _time.time() + SESSION_SECONDS
    await message.answer("PIN-kod saqlandi.")
    await show_panel(message, db, message.from_user.id)


@router.message(SleepTime.value, F.text)
async def sleep_value(message: Message, state: FSMContext, db: DB):
    m = re.match(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*([01]?\d|2[0-3]):([0-5]\d)\s*$", message.text)
    if not m:
        await message.answer("Shunday yozing: <b>21:00-07:00</b>")
        return
    a = f"{int(m[1]):02d}:{m[2]}"
    b = f"{int(m[3]):02d}:{m[4]}"
    await state.clear()
    await db.set_parent(message.from_user.id, sleep_from=a, sleep_to=b, sleep_on=1)
    await message.answer(f"Uxlash vaqti: {a}–{b}.")
    await show_panel(message, db, message.from_user.id)


@router.callback_query(F.data.startswith("pm:") | F.data.startswith("unblock:") | F.data.startswith("delkid:"))
async def panel_action(cb: CallbackQuery, state: FSMContext, db: DB):
    uid = cb.from_user.id
    if not unlocked(uid):
        await cb.answer("Sessiya tugadi. «Ota-ona nazorati» tugmasini bosib PIN kiriting.", show_alert=True)
        return
    _sessions[uid] = _time.time() + SESSION_SECONDS  # faol bo'lsa uzaytiramiz
    p = await db.get_parent(uid)
    parts = cb.data.split(":")
    note = None
    if parts[0] == "unblock":
        await db.toggle_block(uid, int(parts[1]))
        note, parts = "Ochildi.", ["pm", "blocked"]
    if parts[0] == "delkid":
        await db.delete_child(uid, int(parts[1]))
        note, parts = "O'chirildi.", ["pm", "kids"]

    act = parts[1]
    if act == "limit":
        new = max(15, min(240, p["daily_limit"] + int(parts[2])))
        await db.set_parent(uid, daily_limit=new)
        await show_panel(cb.message, db, uid, edit=True)
    elif act == "sleep":
        await db.set_parent(uid, sleep_on=0 if p["sleep_on"] else 1)
        await show_panel(cb.message, db, uid, edit=True)
    elif act == "report":
        await db.set_parent(uid, report_on=0 if p["report_on"] else 1)
        await show_panel(cb.message, db, uid, edit=True)
    elif act == "sleeptime":
        await state.set_state(SleepTime.value)
        await cb.message.answer("Uxlash vaqtini yozing, masalan: <b>21:00-07:00</b>")
    elif act == "pin":
        await state.set_state(Pin.new)
        await cb.message.answer("Yangi 4 xonali PIN-kodni yozing:")
    elif act == "kids":
        kids = await db.children(uid)
        b = InlineKeyboardBuilder()
        lines = []
        for c in kids:
            lines.append(f"• {c['name']} — {age_of(c['birth_date'], now().date())} yosh, {c['stars']} yulduz")
            b.button(text=f"O'chirish: {c['name']}", callback_data=f"delkid:{c['id']}")
        b.button(text="« Orqaga", callback_data="pm:back")
        b.adjust(1)
        await cb.message.edit_text("<b>Bolalar</b>\n" + ("\n".join(lines) or "Hali yo'q") +
                                   "\n\nYangi bola qo'shish: «Bolani almashtirish» → «+ Bola qo'shish».",
                                   reply_markup=b.as_markup())
    elif act == "blocked":
        items = await db.blocked_list(uid)
        b = InlineKeyboardBuilder()
        for it in items:
            b.button(text=f"Ochish: {it['title']}", callback_data=f"unblock:{it['id']}")
        b.button(text="« Orqaga", callback_data="pm:back")
        b.adjust(1)
        text = ("<b>Yopilgan kontent</b>\n" + (f"{len(items)} ta. Ochish uchun bosing." if items else
                "Hech narsa yopilmagan. Kontent tagidagi «Ota-ona: yopib qo'yish» tugmasi bilan yopiladi."))
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    elif act == "coupons":
        cs = await db.parent_coupons(uid)
        lines = [f"<code>{c['code']}</code> — {c['percent']}% · {c['expires_at'][:10]} gacha" for c in cs]
        b = InlineKeyboardBuilder()
        b.button(text="« Orqaga", callback_data="pm:back")
        await cb.message.edit_text("<b>Faol kuponlar</b>\n" + ("\n".join(lines) or "Hozircha yo'q."),
                                   reply_markup=b.as_markup())
    elif act == "today":
        lines = []
        for c in await db.children(uid):
            used = await db.minutes_today(c["id"])
            lines.append(f"• {c['name']}: bugun {used} / {p['daily_limit']} daqiqa")
        b = InlineKeyboardBuilder()
        b.button(text="« Orqaga", callback_data="pm:back")
        await cb.message.edit_text("<b>Bugun</b>\n" + ("\n".join(lines) or "Bolalar yo'q."),
                                   reply_markup=b.as_markup())
    elif act == "back":
        await show_panel(cb.message, db, uid, edit=True)
    elif act == "exit":
        _sessions.pop(uid, None)
        await cb.message.edit_text("Ota-ona bo'limi yopildi.")
    await cb.answer(note)
