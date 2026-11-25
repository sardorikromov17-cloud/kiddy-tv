"""Bot va admin panelni birga ishga tushirish: python run.py
Panel: http://localhost:8080 (PANEL_PORT bilan o'zgartiriladi)."""
import asyncio
import logging
import os

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import config
from admin_panel.app import create_app
from miniapp.api import create_miniapp
from tunnel import run_tunnel
from db import DB
from handlers import admin, parent, user
from scheduler import run_scheduler


async def poll_forever(dp, bot):
    """Bot uzilib qolsa (internet, Telegram cheklovi) panelni to'xtatmay qayta ulanadi."""
    delay = 30
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning("Bot ulana olmadi (%s). %s soniyadan keyin qayta urinadi.", str(e).splitlines()[0], delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 600)  # Telegram cheklovi bo'lsa so'rovlarni kamaytiramiz


def combined_app(panel, mini):
    """Serverda bitta port: /api/* va /app -> Mini App, qolgani -> admin panel."""
    async def app(scope, receive, send):
        path = scope.get("path", "") if scope["type"] in ("http", "websocket") else ""
        target = mini if (path.startswith("/api/") or path == "/app" or path == "/app/") else panel
        if scope["type"] == "lifespan":
            # ikkala ilovaning lifespan'i ham kerak emas (startup hodisalari yo'q)
            msg = await receive()
            await send({"type": "lifespan.startup.complete"})
            await receive()
            await send({"type": "lifespan.shutdown.complete"})
            return
        await target(scope, receive, send)
    return app


async def bootstrap(db):
    """Bulutda birinchi ishga tushishda: admin hisob va kontentni yuklash."""
    import gzip, json
    u, pw = os.getenv("ADMIN_USER", "").strip(), os.getenv("ADMIN_PASS", "").strip()
    staff_seed = os.getenv("STAFF_SEED", "").strip()  # kompyuterdagi xodimlar (parol xeshlari bilan)
    if staff_seed and await db.staff_count() == 0:
        from db import iso, now
        for r in json.loads(staff_seed):
            await db.run("INSERT INTO staff (username, full_name, pw_hash, role, created_at) VALUES (?,?,?,?,?)",
                         r["username"], r.get("full_name", ""), r["pw_hash"], r.get("role", "kassir"), iso(now()))
        logging.info("Xodimlar ko'chirildi: %s ta", len(json.loads(staff_seed)))
    if u and pw and await db.staff_count() == 0:
        await db.add_staff(u, pw, "admin", "Admin")
        logging.info("Birinchi admin yaratildi: %s", u)
    seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data", "content.json.gz")
    if os.path.exists(seed) and (await db.one("SELECT COUNT(*) c FROM content"))["c"] == 0:
        with gzip.open(seed, "rt", encoding="utf-8") as f:
            data = json.load(f)
        cols = ["kind", "title", "source_type", "source", "file_type", "age_min", "age_max", "minutes",
                "active", "created_at", "series", "episode"]
        for r in data["content"]:
            await db.run(f"INSERT INTO content ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         *[r.get(c) for c in cols])
        for k, v in data.get("settings", {}).items():
            await db.set_setting(k, v)
        logging.info("Kontent yuklandi: %s ta", len(data["content"]))


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("kiddy_tv.log", encoding="utf-8")])
    db = DB()
    await db.connect()
    try:
        n = await db.import_quiz_drafts(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data",
                                                     "quiz_drafts.json"))
        if n:
            logging.info("Savollar qoralamasi yuklandi: %s ta (panelda tasdiqlash kerak)", n)
    except Exception as e:
        logging.warning("Savollar qoralamasi yuklanmadi: %s", e)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) if config.BOT_TOKEN else None

    cloud_port = os.getenv("PORT")  # Railway/Render kabi serverlar portni shu orqali beradi
    if cloud_port:
        await bootstrap(db)
        await db.import_quiz_drafts(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data",
                                                 "quiz_drafts.json"))
        dom = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("PUBLIC_DOMAIN", "")
        if dom and not os.getenv("WEBAPP_URL"):
            os.environ["WEBAPP_URL"] = f"https://{dom}/app"
        app = combined_app(create_app(db, bot), create_miniapp(db, bot, config.BOT_TOKEN) if bot else create_app(db, bot))
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=int(cloud_port), log_level="warning",
                                               proxy_headers=True, forwarded_allow_ips="*"))
        tasks = [asyncio.create_task(server.serve())]
        if bot:
            tasks.append(asyncio.create_task(run_tunnel(bot, db, 0)))  # WEBAPP_URL -> menyu tugmasi
        logging.info("Server rejimi: port %s, Mini App: %s", cloud_port, os.getenv("WEBAPP_URL", "-"))
    host = os.getenv("PANEL_HOST", "127.0.0.1")
    port = int(os.getenv("PANEL_PORT", "8080"))
    if not cloud_port:
        server = uvicorn.Server(uvicorn.Config(create_app(db, bot), host=host, port=port, log_level="warning"))
        tasks = [asyncio.create_task(server.serve())]
    if config.BOT_TOKEN and not cloud_port:
        mport = int(os.getenv("MINIAPP_PORT", "8081"))
        mserver = uvicorn.Server(uvicorn.Config(create_miniapp(db, bot, config.BOT_TOKEN), host="127.0.0.1",
                                                port=mport, log_level="warning"))
        tasks.append(asyncio.create_task(mserver.serve()))
        tasks.append(asyncio.create_task(run_tunnel(bot, db, mport)))
    if not cloud_port:
        logging.info("Admin panel: http://%s:%s", "localhost" if host in ("127.0.0.1", "0.0.0.0") else host, port)

    if bot:
        dp = Dispatcher(storage=MemoryStorage(), db=db)
        dp.include_routers(admin.router, parent.router, user.router)
        try:
            await bot.set_my_commands([BotCommand(command="start", description="Bosh menyu"),
                                       BotCommand(command="app", description="Kiddy TV ilovasini ochish"),
                                       BotCommand(command="taklif", description="Do'stni taklif qilish — yulduz olish")])
        except Exception as e:  # menyu muhim emas, bot ishlayversin
            logging.warning("Menyu buyruqlari o'rnatilmadi: %s", e)
        tasks.append(asyncio.create_task(poll_forever(dp, bot)))
        tasks.append(asyncio.create_task(run_scheduler(bot, db)))
        logging.info("Kiddy TV bot ishga tushdi")
    else:
        logging.warning(".env da BOT_TOKEN yo'q — faqat panel ishlayapti")
    try:
        await tasks[0]  # panel ishlab turguncha
    finally:
        for t in tasks:
            t.cancel()
        await db.close()
        if bot:
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
