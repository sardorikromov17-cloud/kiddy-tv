"""Admin (do'kon xodimi) buyruqlari: kontent qo'shish, kupon tekshirish, statistika, xabar yuborish."""
import asyncio
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import keyboards as kb
from db import DB

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

YT_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/\S+$")
URL_RE = re.compile(r"^https?://\S+$")

HELP = ("<b>Admin buyruqlari</b>\n"
        "/add — yangi kontent qo'shish\n"
        "/list multfilm|kino|video|ertak|oyin — ro'yxat (ID bilan)\n"
        "/del ID — kontentni o'chirish\n"
        "/kupon KOD — kuponni tekshirish va ishlatish (kassada)\n"
        "/stat — statistika\n"
        "/xabar MATN — barcha ota-onalarga xabar\n"
        "/bekor — joriy amalni bekor qilish")

LIST_ALIASES = {"multfilm": "cartoon", "kino": "film", "video": "video", "ertak": "audio", "oyin": "game",
                "o'yin": "game"}


class Add(StatesGroup):
    source = State()
    title = State()
    ages = State()
    minutes = State()


@router.message(Command("admin"))
async def admin_help(message: Message):
    await message.answer(HELP)


@router.message(Command("bekor"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=kb.main_menu())


@router.message(Command("add"))
async def add_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Qaysi bo'limga qo'shamiz?", reply_markup=kb.admin_kinds())


@router.callback_query(F.data.startswith("ak:"))
async def add_kind(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[1]
    await state.update_data(kind=kind)
    await state.set_state(Add.source)
    hint = ("O'yin havolasini yuboring (saytdagi o'yin sahifasi)." if kind == "game" else
            "YouTube havolasini yoki faylni (video / audio) shu yerga yuboring.\n"
            "Muhim: faqat ruxsat etilgan, mualliflik huquqi bo'yicha muammosiz kontent qo'ying.")
    await cb.message.answer(f"{config.KINDS[kind]}. {hint}")
    await cb.answer()


@router.message(Add.source)
async def add_source(message: Message, state: FSMContext):
    data = await state.get_data()
    src = None
    if message.video:
        src = ("file", message.video.file_id, "video", message.video.duration)
    elif message.audio:
        src = ("file", message.audio.file_id, "audio", message.audio.duration)
    elif message.voice:
        src = ("file", message.voice.file_id, "audio", message.voice.duration)
    elif message.document:
        src = ("file", message.document.file_id, "document", None)
    elif message.text and YT_RE.match(message.text.strip()):
        src = ("youtube", message.text.strip(), None, None)
    elif message.text and URL_RE.match(message.text.strip()) and data["kind"] == "game":
        src = ("link", message.text.strip(), None, None)
    if not src:
        await message.answer("Tushunmadim. YouTube havolasi yoki video/audio fayl yuboring. /bekor")
        return
    st, source, ft, dur = src
    await state.update_data(source_type=st, source=source, file_type=ft,
                            auto_minutes=max(1, round(dur / 60)) if dur else None)
    await state.set_state(Add.title)
    await message.answer("Nomini yozing (masalan: Zumrad va Qimmat):")


@router.message(Add.title, F.text)
async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:80])
    await state.set_state(Add.ages)
    await message.answer("Qaysi yoshlar uchun? Masalan: <b>3-8</b>")


@router.message(Add.ages, F.text)
async def add_ages(message: Message, state: FSMContext, db: DB):
    m = re.match(r"^\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*$", message.text)
    if not m or int(m[1]) > int(m[2]) or int(m[2]) > 14:
        await message.answer("Shunday yozing: <b>3-8</b> (0 dan 14 gacha)")
        return
    await state.update_data(age_min=int(m[1]), age_max=int(m[2]))
    data = await state.get_data()
    if data.get("auto_minutes"):
        await save(message, state, db, data["auto_minutes"])
        return
    await state.set_state(Add.minutes)
    await message.answer("Davomiyligi necha daqiqa? (o'yin uchun taxminiy, masalan 10)")


@router.message(Add.minutes, F.text)
async def add_minutes(message: Message, state: FSMContext, db: DB):
    if not message.text.strip().isdigit() or not (1 <= int(message.text) <= 300):
        await message.answer("1 dan 300 gacha son yozing.")
        return
    await save(message, state, db, int(message.text))


async def save(message: Message, state: FSMContext, db: DB, minutes: int):
    d = await state.get_data()
    await state.clear()
    cid = await db.add_content(d["kind"], d["title"], d["source_type"], d["source"], d.get("file_type"),
                               d["age_min"], d["age_max"], minutes)
    await message.answer(f"Saqlandi! ID {cid}: <b>{d['title']}</b> · {config.KINDS[d['kind']]} · "
                         f"{d['age_min']}–{d['age_max']} yosh · {minutes} daq\n\nYana qo'shish: /add")


@router.message(Command("list"))
async def list_cmd(message: Message, command: CommandObject, db: DB):
    kind = LIST_ALIASES.get((command.args or "").strip().lower())
    if not kind:
        await message.answer("Masalan: /list multfilm (multfilm, kino, video, ertak, oyin)")
        return
    rows = await db.all("SELECT * FROM content WHERE kind=? AND active=1 ORDER BY id DESC LIMIT 50", kind)
    lines = [f"{r['id']}. {r['title']} ({r['age_min']}–{r['age_max']} yosh, {r['minutes']} daq)" for r in rows]
    await message.answer(f"<b>{config.KINDS[kind]}</b>\n" + ("\n".join(lines) or "Bo'sh"))


@router.message(Command("del"))
async def del_cmd(message: Message, command: CommandObject, db: DB):
    if not (command.args or "").strip().isdigit():
        await message.answer("Masalan: /del 12")
        return
    item = await db.get_content(int(command.args))
    if not item:
        await message.answer("Topilmadi.")
        return
    await db.deactivate_content(item["id"])
    await message.answer(f"O'chirildi: {item['title']}")


@router.message(Command("kupon"))
async def coupon_cmd(message: Message, command: CommandObject, db: DB):
    if not command.args:
        await message.answer("Masalan: /kupon KIDDY-AB12CD")
        return
    status, c = await db.use_coupon(command.args, f"bot:{message.from_user.full_name}")
    texts = {
        "not_found": "Bunday kupon yo'q.",
        "used": f"Bu kupon allaqachon ishlatilgan ({c['used_at'] if c else ''}).",
        "expired": "Kupon muddati o'tgan.",
        "ok": f"Kupon to'g'ri! Chegirma: <b>{c['percent']}%</b>. Endi u ishlatilgan deb belgilandi.",
    }
    await message.answer(texts[status])


@router.message(Command("stat"))
async def stat_cmd(message: Message, db: DB):
    s = await db.stats_overview()
    await message.answer(f"<b>Statistika</b>\nOta-onalar: {s['parents']}\nBolalar: {s['children']}\n"
                         f"Kontent: {s['content']}\nBugun ko'rishlar: {s['views_today']}\n"
                         f"Ishlatilgan kuponlar: {s['coupons_used']}")


@router.message(Command("xabar"))
async def broadcast(message: Message, command: CommandObject, bot: Bot, db: DB):
    if not command.args:
        await message.answer("Masalan: /xabar Bugun yangi multfilm qo'shildi!")
        return
    sent = 0
    for row in await db.all("SELECT tg_id FROM parents"):
        try:
            await bot.send_message(row["tg_id"], command.args)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)  # Telegram limitlariga tushmaslik uchun
    await message.answer(f"Yuborildi: {sent} ta.")
