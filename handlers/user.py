"""Bolalar va ota-onalar uchun asosiy bo'limlar."""
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

import config
import keyboards as kb
from db import DB, age_of, now, parse_birth

router = Router()
LOGO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "logo.png")


class AddChild(StatesGroup):
    name = State()
    birth = State()


class Contest(StatesGroup):
    photo = State()


WELCOME = ("Assalomu alaykum! <b>Kiddy TV</b>ga xush kelibsiz.\n\n"
           "Bu yerda bolalar uchun bepul va reklamasiz multfilm, kino, video, ertak va o'yinlar bor. "
           "Har bir video ota-onalar tomonidan tekshirilgan.")


_logo_file_id = None


async def send_welcome(message: Message):
    """Logo bilan salomlashish; internet sekin bo'lsa ham matn albatta boradi."""
    global _logo_file_id
    if os.path.exists(LOGO):
        try:
            m = await message.answer_photo(_logo_file_id or FSInputFile(LOGO), caption=WELCOME,
                                           request_timeout=25)
            if m.photo:
                _logo_file_id = m.photo[-1].file_id  # keyingi safar qayta yuklamaymiz
            return
        except Exception:
            pass
    await message.answer(WELCOME)


async def offer_app(message: Message, db: DB) -> bool:
    """Mini App manzili bo'lsa — ochish tugmasini yuboradi."""
    url = await db.setting("webapp_url")
    if not url:
        return False
    await message.answer("Multfilm, kino, ertak va o'yinlar — hammasi ilovada. Pastdagi tugmani bosing:",
                         reply_markup=kb.webapp_kb(url))
    return True


@router.message(Command("app"))
async def app_cmd(message: Message, db: DB):
    await db.ensure_parent(message.from_user.id, message.from_user.full_name)
    if not await offer_app(message, db):
        await message.answer("Ilova hozircha ishga tushmagan. Biroz keyin urinib ko'ring.")


async def ask_child_name(message: Message, state: FSMContext, first=False):
    await state.set_state(AddChild.name)
    text = "Keling, tanishamiz! Bolangizning ismi nima?" if first else "Yangi bolaning ismini yozing:"
    await message.answer(text)


async def settle_and_notify(bot, db: DB, parent_id: int):
    """Taklif bilan kelgan oila birinchi bolasini qo'shganda — ikkala tomonga yulduz va xabar."""
    r = await db.settle_referral(parent_id)
    if not r:
        return None
    try:
        if r["bonus"]:
            await bot.send_message(r["ref"], f"🎉 Siz taklif qilgan do'stingiz Kiddy TV'ga qo'shildi!\n"
                                             f"{r['ref_child']}ga +{r['bonus']} yulduz sovg'a.")
    except Exception:
        pass
    return r


async def invite_text(bot, db: DB, tg_id: int):
    me = await bot.me()
    link = f"https://t.me/{me.username}?start={db.ref_code(tg_id)}"
    st = await db.ref_stats(tg_id)
    bonus, new_bonus = await db.setting("ref_bonus"), await db.setting("ref_new_bonus")
    return link, (f"👫 <b>Do'stlaringizni Kiddy TV'ga taklif qiling!</b>\n\n"
                  f"Har bir do'stingiz qo'shilib, bolasini ro'yxatdan o'tkazsa — farzandingizga <b>+{bonus} yulduz</b>, "
                  f"do'stingizning bolasiga <b>+{new_bonus} yulduz</b>.\n\n"
                  f"Sizning havolangiz:\n{link}\n\nTaklif qilganlar: {st['joined']} ta")


@router.message(Command("dokon"))
async def store_cmd(message: Message, db: DB):
    i = await db.store_info()
    lines = [f"🏬 <b>{i['name']}</b>"]
    if i["address"]:
        lines.append(f"📍 {i['address']}")
    if i["hours"]:
        lines.append(f"🕘 {i['hours']}")
    if i["phone"]:
        lines.append(f"📞 {i['phone']}")
    if i["map"]:
        lines.append(f"🗺 Xarita: {i['map']}")
    lines.append("\nDo'kondagi QR kodni skanerlang — har hafta yulduz sovg'a!")
    await message.answer("\n".join(lines), disable_web_page_preview=True)


@router.message(Command("taklif"))
async def invite_cmd(message: Message, db: DB, bot: Bot):
    await db.ensure_parent(message.from_user.id, message.from_user.full_name)
    link, text = await invite_text(bot, db, message.from_user.id)
    await message.answer(text, disable_web_page_preview=True)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db: DB, command: CommandObject = None):
    await state.clear()
    args = (command.args or "") if command else ""
    if args.startswith("qr_"):  # do'kondagi QR kod skanerlandi
        await db.ensure_parent(message.from_user.id, message.from_user.full_name)
        child = await db.active_child(message.from_user.id)
        if not child:
            await message.answer("Kiddy Toys'ga xush kelibsiz! Yulduz olish uchun avval farzandingizni qo'shing.")
            await ask_child_name(message, state, first=True)
            return
        stars, text = await db.checkin(message.from_user.id, child["id"], args)
        child = await db.child(child["id"])
        await message.answer(("⭐ " if stars else "") + text + (f"\nJami: {child['stars']} yulduz." if stars else ""))
        await offer_app(message, db)
        return
    if args.startswith("r"):
        await db.register_referral(message.from_user.id, message.from_user.full_name, args)
    await db.ensure_parent(message.from_user.id, message.from_user.full_name)
    await send_welcome(message)
    if await offer_app(message, db):
        return
    if not await db.children(message.from_user.id):
        await ask_child_name(message, state, first=True)
    else:
        child = await db.active_child(message.from_user.id)
        await message.answer(f"Salom, {child['name']}! Bugun nima ko'ramiz?", reply_markup=kb.main_menu())


@router.message(AddChild.name, F.text)
async def child_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not (1 <= len(name) <= 40):
        await message.answer("Ism 1–40 harf bo'lsin. Qaytadan yozing:")
        return
    await state.update_data(name=name)
    await state.set_state(AddChild.birth)
    await message.answer(f"{name} qachon tug'ilgan? Sanani shunday yozing: <b>25.03.2020</b>\n"
                         "(yoshiga mos multfilmlarni tanlash va tug'ilgan kunda tabriklash uchun)")


@router.message(AddChild.birth, F.text)
async def child_birth(message: Message, state: FSMContext, db: DB, bot: Bot):
    birth = parse_birth(message.text)
    if not birth:
        await message.answer("Sanani tushunmadim. Masalan: <b>25.03.2020</b>")
        return
    data = await state.get_data()
    await state.clear()
    await db.ensure_parent(message.from_user.id, message.from_user.full_name)
    await db.add_child(message.from_user.id, data["name"], birth)
    age = age_of(birth, now().date())
    await message.answer(f"Ajoyib! {data['name']} — {age} yosh. Endi unga mos kontentni ko'rsataman.",
                         reply_markup=kb.main_menu())
    r = await settle_and_notify(bot, db, message.from_user.id)
    if r and r["new_bonus"]:
        await message.answer(f"🎁 Do'stingiz taklifi bilan kelganingiz uchun {r['new_name']}ga +{r['new_bonus']} yulduz!")


async def need_child(message: Message, state: FSMContext, db: DB):
    child = await db.active_child(message.from_user.id)
    if not child:
        await db.ensure_parent(message.from_user.id, message.from_user.full_name)
        await ask_child_name(message, state, first=True)
    return child


# ---------- kontent bo'limlari ----------
async def show_list(target: Message, db: DB, parent_id: int, kind: str, offset: int, edit=False):
    child = await db.active_child(parent_id)
    age = age_of(child["birth_date"], now().date())
    items, more = await db.list_content(kind, age=age, parent_id=parent_id, offset=offset)
    title = config.KINDS[kind]
    if not items and offset == 0:
        text = f"{title}: hozircha {child['name']} yoshiga mos kontent yo'q. Tez orada qo'shamiz!"
        markup = None
    else:
        text = f"<b>{title}</b> · {child['name']} uchun ({age} yosh)"
        markup = kb.content_list(items, kind, offset, more)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(F.text.in_(kb.KIND_BY_TEXT.keys()))
async def kind_menu(message: Message, state: FSMContext, db: DB):
    if not await need_child(message, state, db):
        return
    await show_list(message, db, message.from_user.id, kb.KIND_BY_TEXT[message.text], 0)


@router.callback_query(F.data.startswith("page:"))
async def page(cb: CallbackQuery, db: DB):
    _, kind, offset = cb.data.split(":")
    await show_list(cb.message, db, cb.from_user.id, kind, int(offset), edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("open:"))
async def open_content(cb: CallbackQuery, bot: Bot, db: DB):
    item = await db.get_content(int(cb.data.split(":")[1]))
    parent = await db.ensure_parent(cb.from_user.id, cb.from_user.full_name)
    child = await db.active_child(cb.from_user.id)
    if not item or not item["active"] or not child:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    ok, reason = await db.check_access(parent, child, item)
    if not ok:
        await cb.answer(reason, show_alert=True)
        return
    await db.start_view(child["id"], item)  # yulduz faqat Mini App'da yarmi ko'rilganda beriladi
    caption = f"<b>{item['title']}</b>\n{config.KINDS[item['kind']]} · {item['minutes']} daqiqa"
    chat = cb.message.chat.id
    if item["source_type"] == "file":
        markup = kb.open_item(item, None)
        send = {"video": bot.send_video, "audio": bot.send_audio}.get(item["file_type"], bot.send_document)
        await send(chat, item["source"], caption=caption, reply_markup=markup, protect_content=True)
    else:
        await bot.send_message(chat, caption, reply_markup=kb.open_item(item, item["source"]))
    await bot.send_message(chat, "⭐ Yulduzlar Kiddy TV ilovasida videoning yarmini ko'rganda beriladi. "
                                 "Ilovani ochish: /app")
    await cb.answer()


@router.callback_query(F.data.startswith("block:"))
async def block_item(cb: CallbackQuery, db: DB):
    cid = int(cb.data.split(":")[1])
    if await db.one("SELECT 1 FROM blocked WHERE parent_id=? AND content_id=?", cb.from_user.id, cid):
        await cb.answer("Allaqachon yopilgan. Ochish: Ota-ona nazorati → Yopilgan kontent.", show_alert=True)
        return
    await db.toggle_block(cb.from_user.id, cid)
    await cb.answer("Yopildi. Endi bu kontent ro'yxatda ko'rinmaydi.", show_alert=True)


@router.callback_query(F.data.startswith("like:"))
async def like_item(cb: CallbackQuery, db: DB):
    child = await db.active_child(cb.from_user.id)
    if not child:
        await cb.answer()
        return
    liked = await db.toggle_like(child["id"], int(cb.data.split(":")[1]))
    await cb.answer("Yoqdi! Rahmat." if liked else "Olib tashlandi.")


# ---------- bolani almashtirish ----------
@router.message(F.text == kb.BTN_CHILD)
async def switch_child(message: Message, state: FSMContext, db: DB):
    await db.ensure_parent(message.from_user.id, message.from_user.full_name)
    kids = await db.children(message.from_user.id)
    if not kids:
        await ask_child_name(message, state, first=True)
        return
    active = await db.active_child(message.from_user.id)
    await message.answer("Kim tomosha qiladi?", reply_markup=kb.children_kb(kids, active["id"]))


@router.callback_query(F.data.startswith("child:"))
async def pick_child(cb: CallbackQuery, state: FSMContext, db: DB):
    val = cb.data.split(":")[1]
    if val == "add":
        await ask_child_name(cb.message, state)
        await cb.answer()
        return
    c = await db.child(int(val))
    if not c or c["parent_id"] != cb.from_user.id:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await db.set_parent(cb.from_user.id, active_child=c["id"])
    kids = await db.children(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=kb.children_kb(kids, c["id"]))
    await cb.answer(f"Salom, {c['name']}!")


# ---------- yulduzlar va chegirma ----------
@router.message(F.text == kb.BTN_STARS)
async def stars(message: Message, state: FSMContext, db: DB):
    child = await need_child(message, state, db)
    if not child:
        return
    await message.answer(
        f"{child['name']}: <b>{child['stars']} yulduz</b>.\n\n"
        "Multfilm ko'rib, ertak tinglab va o'yin o'ynab yulduz yig'. "
        "Yulduzlarni Kiddy Toys do'konida chegirmaga almashtirish mumkin:",
        reply_markup=kb.rewards_kb(child["stars"], await db.tiers()))


@router.callback_query(F.data.startswith("redeem:"))
async def redeem(cb: CallbackQuery, db: DB):
    _, pct, cost = cb.data.split(":")
    pct, cost = int(pct), int(cost)
    if (pct, cost) not in await db.tiers():
        await cb.answer("Bu taklif endi mavjud emas.", show_alert=True)
        return
    child = await db.active_child(cb.from_user.id)
    code = await db.redeem_stars(cb.from_user.id, child["id"], pct, cost) if child else None
    if not code:
        await cb.answer(f"Yulduz yetmaydi: {cost} ta kerak.", show_alert=True)
        return
    await cb.message.answer(
        f"Tabriklaymiz! {child['name']} {cost} yulduzni almashtirdi.\n\n"
        f"Kupon: <code>{code}</code>\nChegirma: <b>{pct}%</b> · {await db.setting('coupon_days')} kun amal qiladi.\n\n"
        "Kiddy Toys do'konida kassirga shu kodni ko'rsating.")
    await cb.answer()


# ---------- ijod tanlovi ----------
@router.message(F.text == kb.BTN_CONTEST)
async def contest(message: Message, state: FSMContext, db: DB):
    if not await need_child(message, state, db):
        return
    await state.set_state(Contest.photo)
    title = await db.setting("contest_title")
    await message.answer(f"<b>Ijod tanlovi: \"{title}\"</b>\nChizgan rasmingizni rasm (foto) qilib yuboring. "
                         "G'oliblarga Kiddy Toys'dan sovg'a!\n\nBekor qilish: /start")


@router.message(Contest.photo, F.photo)
async def contest_photo(message: Message, state: FSMContext, bot: Bot, db: DB):
    child = await db.active_child(message.from_user.id)
    file_id = message.photo[-1].file_id
    await db.run("INSERT INTO contest (parent_id, child_id, file_id, created_at) VALUES (?,?,?,?)",
                 message.from_user.id, child["id"], file_id, now().strftime("%Y-%m-%d %H:%M:%S"))
    await state.clear()
    await message.answer("Rasm qabul qilindi! Natijalarni shu bot orqali e'lon qilamiz.",
                         reply_markup=kb.main_menu())
    age = age_of(child["birth_date"], now().date())
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_photo(admin, file_id, caption=f"Tanlov: {child['name']}, {age} yosh "
                                                        f"(ota-ona id: {message.from_user.id})")
        except Exception:
            pass


@router.message(Contest.photo)
async def contest_wrong(message: Message):
    await message.answer("Iltimos, rasm (foto) yuboring yoki /start bosing.")
