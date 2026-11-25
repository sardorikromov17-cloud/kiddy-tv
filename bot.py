"""Kiddy TV Telegram boti — ishga tushirish: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import config
from db import DB
from handlers import admin, parent, user
from scheduler import run_scheduler


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit(".env faylida BOT_TOKEN yo'q. README.md ni o'qing.")
    db = DB()
    await db.connect()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), db=db)
    dp.include_routers(admin.router, parent.router, user.router)
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Bosh menyu")])
    except Exception as e:  # menyu muhim emas, bot ishlayversin
        logging.warning("Menyu buyruqlari o'rnatilmadi: %s", e)
    task = asyncio.create_task(run_scheduler(bot, db))
    logging.info("Kiddy TV bot ishga tushdi")
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
