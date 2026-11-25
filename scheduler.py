"""Har daqiqada tekshiradi: haftalik hisobot (yakshanba 19:00) va tug'ilgan kun tabrigi (09:00)."""
import asyncio
import logging

from aiogram import Bot

import config
from db import DB, age_of, now


async def weekly_reports(bot: Bot, db: DB):
    n = now()
    if n.weekday() != config.REPORT_WEEKDAY or n.hour < config.REPORT_HOUR:
        return
    week = n.strftime("%G-W%V")
    for p in await db.all("SELECT * FROM parents WHERE report_on=1"):
        if await db.one("SELECT 1 FROM report_sent WHERE parent_id=? AND week=?", p["tg_id"], week):
            continue
        parts = []
        for c in await db.children(p["tg_id"]):
            s = await db.week_stats(c["id"], n)
            h, m = divmod(s["minutes"], 60)
            t = f"{h} soat {m} daqiqa" if h else f"{m} daqiqa"
            line = (f"<b>{c['name']}</b>: {t} ko'rdi, {s['count']} ta kontent, {s['games']} ta o'yin, "
                    f"+{s['stars']} yulduz (jami {c['stars']}).")
            if s["top"]:
                line += f"\nEng ko'p ko'rgani: {s['top']}"
            parts.append(line)
        await db.run("INSERT OR IGNORE INTO report_sent VALUES (?,?)", p["tg_id"], week)
        if not parts:
            continue
        try:
            await bot.send_message(p["tg_id"], "<b>Haftalik hisobot · Kiddy TV</b>\n\n" + "\n\n".join(parts) +
                                   "\n\nO'chirish: Ota-ona nazorati → Haftalik hisobot.")
        except Exception as e:
            logging.warning("Hisobot yuborilmadi %s: %s", p["tg_id"], e)
        await asyncio.sleep(0.05)


async def birthdays(bot: Bot, db: DB):
    n = now()
    if n.hour < config.BIRTHDAY_HOUR:
        return
    md = n.strftime("%m-%d")
    for c in await db.all("SELECT * FROM children WHERE substr(birth_date,6,5)=?", md):
        if await db.one("SELECT 1 FROM birthday_sent WHERE child_id=? AND year=?", c["id"], n.year):
            continue
        await db.run("INSERT OR IGNORE INTO birthday_sent VALUES (?,?)", c["id"], n.year)
        pct = int(await db.setting("birthday_percent"))
        days = await db.setting("coupon_days")
        code = await db.make_coupon(c["parent_id"], c["id"], pct, 0, "birthday")
        age = age_of(c["birth_date"], n.date())
        try:
            await bot.send_message(
                c["parent_id"],
                f"<b>Tug'ilgan kuning muborak, {c['name']}!</b>\n\nBugun {age} yoshga to'lding! "
                f"Kiddy Toys'dan senga sovg'a kuponi:\n\n<code>{code}</code> — {pct}% chegirma, "
                f"{days} kun amal qiladi. Do'konda kassirga ko'rsating.")
        except Exception as e:
            logging.warning("Tabrik yuborilmadi %s: %s", c["parent_id"], e)


async def run_scheduler(bot: Bot, db: DB):
    while True:
        try:
            await weekly_reports(bot, db)
            await birthdays(bot, db)
        except Exception:
            logging.exception("Scheduler xatosi")
        await asyncio.sleep(60)
