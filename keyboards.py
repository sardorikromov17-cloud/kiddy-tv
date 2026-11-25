from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config

BTN_CHILD = "Bolani almashtirish"
BTN_PARENT = "Ota-ona nazorati"
BTN_STARS = "Yulduzlarim"
BTN_CONTEST = "Ijod tanlovi"
BTN_SITE = "Saytda ochish"

# tugma matni -> bo'lim kaliti
KIND_BY_TEXT = {v: k for k, v in config.KINDS.items()}
KIND_BY_TEXT["Islomiy"] = "islamic"  # eski klaviaturalar uchun


def main_menu() -> ReplyKeyboardMarkup:
    k = config.KINDS
    rows = [
        [KeyboardButton(text=k["cartoon"]), KeyboardButton(text=k["film"])],
        [KeyboardButton(text=k["video"]), KeyboardButton(text=k["game"])],
        [KeyboardButton(text=k["audio"]), KeyboardButton(text=k["music"])],
        [KeyboardButton(text=k["islamic"]), KeyboardButton(text=BTN_STARS)],
        [KeyboardButton(text=BTN_CONTEST), KeyboardButton(text=BTN_CHILD)],
        [KeyboardButton(text=BTN_PARENT)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def content_list(items, kind, offset, has_more) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=f"{it['title']} · {it['minutes']} daq", callback_data=f"open:{it['id']}")
    b.adjust(1)
    nav = []
    if offset > 0:
        nav.append(("« Oldingi", f"page:{kind}:{max(0, offset - 6)}"))
    if has_more:
        nav.append(("Keyingi »", f"page:{kind}:{offset + 6}"))
    if nav:
        nb = InlineKeyboardBuilder()
        for t, d in nav:
            nb.button(text=t, callback_data=d)
        b.attach(nb)
    return b.as_markup()


def open_item(item, watch_url: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if watch_url:
        b.button(text="O'ynash" if item["kind"] == "game" else "Ko'rish", url=watch_url)
    b.button(text="Yoqdi", callback_data=f"like:{item['id']}")
    b.button(text="Ota-ona: yopib qo'yish", callback_data=f"block:{item['id']}")
    b.adjust(1)
    return b.as_markup()


def children_kb(kids, active_id) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in kids:
        mark = " ✓" if c["id"] == active_id else ""
        b.button(text=f"{c['name']}{mark}", callback_data=f"child:{c['id']}")
    b.button(text="+ Bola qo'shish", callback_data="child:add")
    b.adjust(2)
    return b.as_markup()


def rewards_kb(stars, tiers) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for pct, cost in tiers:
        label = f"{pct}% chegirma — {cost} yulduz" + ("" if stars >= cost else " (yetmaydi)")
        b.button(text=label, callback_data=f"redeem:{pct}:{cost}")
    b.adjust(1)
    return b.as_markup()


def parent_menu(p) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="−15", callback_data="pm:limit:-15")
    b.button(text=f"Kunlik vaqt: {p['daily_limit']} daq", callback_data="pm:noop")
    b.button(text="+15", callback_data="pm:limit:15")
    sleep = f"Uxlash vaqti: {p['sleep_from']}–{p['sleep_to']}" if p["sleep_on"] else "Uxlash vaqti: o'chiq"
    b.button(text=sleep, callback_data="pm:sleep")
    b.button(text="Vaqtni o'zgartirish", callback_data="pm:sleeptime")
    b.button(text="Haftalik hisobot: " + ("yoqilgan" if p["report_on"] else "o'chiq"), callback_data="pm:report")
    b.button(text="Bolalar", callback_data="pm:kids")
    b.button(text="Yopilgan kontent", callback_data="pm:blocked")
    b.button(text="Kuponlarim", callback_data="pm:coupons")
    b.button(text="Bugungi hisobot", callback_data="pm:today")
    b.button(text="PIN-kodni almashtirish", callback_data="pm:pin")
    b.button(text="Chiqish", callback_data="pm:exit")
    b.adjust(3, 1, 1, 1, 2, 2, 1, 1)
    return b.as_markup()


def admin_kinds() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, name in config.KINDS.items():
        b.button(text=name, callback_data=f"ak:{key}")
    b.adjust(2)
    return b.as_markup()


def webapp_kb(url: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Kiddy TV ni ochish", web_app=WebAppInfo(url=url))
    return b.as_markup()
