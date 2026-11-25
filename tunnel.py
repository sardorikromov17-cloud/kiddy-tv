"""Mini App uchun HTTPS manzil: Cloudflare bepul tunneli (cloudflared).
Manzil har ishga tushganda o'zgaradi — bot menyu tugmasi avtomatik yangilanadi."""
import asyncio
import logging
import os
import re
import shutil
import sys

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo

from db import DB

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
HERE = os.path.dirname(os.path.abspath(__file__))


def find_cloudflared() -> str | None:
    for name in ("cloudflared.exe", "cloudflared"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            return p
    return shutil.which("cloudflared")


async def publish_url(bot: Bot | None, db: DB, url: str):
    await db.set_setting("webapp_url", url)
    logging.info("Mini App manzili: %s", url)
    if not bot:
        return
    for attempt in range(10):
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Kiddy TV", web_app=WebAppInfo(url=url)))
            logging.info("Bot menyu tugmasi yangilandi")
            return
        except Exception as e:
            logging.warning("Menyu tugmasi o'rnatilmadi (%s), qayta urinamiz", e)
            await asyncio.sleep(min(60, 5 * (attempt + 1)))


async def run_tunnel(bot: Bot | None, db: DB, port: int):
    fixed = os.getenv("WEBAPP_URL", "").strip()
    if fixed:  # o'z domeningiz bo'lsa (masalan server), tunnel kerak emas
        await publish_url(bot, db, fixed.rstrip("/"))
        return
    exe = find_cloudflared()
    if not exe:
        logging.warning("cloudflared topilmadi — Mini App internetga chiqmaydi. ishga_tushir.bat uni yuklab oladi.")
        return
    while True:
        logging.info("Cloudflare tunnel ishga tushmoqda...")
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # oyna ochilmasin
        proc = await asyncio.create_subprocess_exec(
            exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kw)
        published = False
        try:
            async for raw in proc.stdout:
                line = raw.decode(errors="ignore")
                if not published and (m := URL_RE.search(line)):
                    published = True
                    asyncio.create_task(publish_url(bot, db, m.group(0)))
            await proc.wait()
        except asyncio.CancelledError:
            proc.terminate()
            raise
        logging.warning("Tunnel to'xtadi, 15 soniyadan keyin qayta ochiladi")
        await asyncio.sleep(15)
