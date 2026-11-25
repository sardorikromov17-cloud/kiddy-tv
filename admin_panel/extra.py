"""Admin panel: sovg'alar katalogi, kassada sovg'a kodi, banner, video savollari, yangi qism xabari."""
import asyncio
import logging
import os
import re
import tempfile

from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

import config
from db import now

URL_RE = re.compile(r"^https://\S+$")


def register(app, db, bot, page, guard, flash, go):

    async def save_image(file: UploadFile | None, url: str) -> str | None:
        """Rasm: yuklangan fayl Telegram'ga saqlanadi (file_id) yoki https havola."""
        if file is not None and file.filename:
            if not (file.content_type or "").startswith("image/"):
                raise ValueError("Rasm fayl yuklang (jpg, png).")
            if bot is None:
                raise ValueError("Rasm yuklash uchun bot kerak. Rasm havolasini kiriting.")
            storage = int(os.getenv("STORAGE_CHAT_ID") or next(iter(config.ADMIN_IDS), 0))
            data = await file.read()
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Rasm 8 MB dan kichik bo'lsin.")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(data)
            try:
                m = await bot.send_photo(storage, FSInputFile(tmp.name), caption="Kiddy TV rasm")
                return m.photo[-1].file_id
            except Exception as e:
                raise ValueError(f"Rasmni saqlab bo'lmadi: {e}")
            finally:
                os.unlink(tmp.name)
        url = (url or "").strip()
        if url:
            if not URL_RE.match(url):
                raise ValueError("Rasm havolasi https:// bilan boshlansin.")
            return url
        return None

    # ---------- sovg'alar ----------
    @app.get("/gifts", response_class=HTMLResponse)
    async def gifts_page(request: Request, check: str = ""):
        if r := await guard(request, "gifts"):
            return r
        found = None
        if check:
            found = await db.one("SELECT o.*, g.title, ch.name child_name FROM gift_orders o JOIN gifts g ON "
                                 "g.id=o.gift_id LEFT JOIN children ch ON ch.id=o.child_id WHERE o.code=?",
                                 check.strip().upper())
        return await page(request, "gifts.html", "gifts", gifts=await db.gifts_list(only_active=False),
                          orders=await db.gift_orders(limit=60), check=check, found=found,
                          now_s=now().strftime("%Y-%m-%d %H:%M:%S"))

    @app.post("/gifts/add")
    async def gift_add(request: Request, token: str = Form(""), title: str = Form(...), stars: int = Form(...),
                       note: str = Form(""), stock: str = Form(""), image_url: str = Form(""),
                       image: UploadFile | None = File(None)):
        if r := await guard(request, "settings", token):
            return r
        title = title.strip()[:60]
        if not title or not (1 <= stars <= 100000):
            flash(request, "Nomi va yulduz narxini kiriting.", "err")
            return go("/gifts")
        try:
            img = await save_image(image, image_url)
        except ValueError as e:
            flash(request, str(e), "err")
            return go("/gifts")
        st = int(stock) if stock.strip().isdigit() else None
        await db.add_gift(title, stars, note.strip()[:120], img, st)
        flash(request, f"Sovg'a qo'shildi: {title} — {stars} yulduz. Ilovada darhol ko'rinadi.")
        return go("/gifts")

    @app.post("/gifts/{gid}/edit")
    async def gift_edit(request: Request, gid: int, token: str = Form(""), stars: int = Form(...),
                        stock: str = Form(""), active: int = Form(0)):
        if r := await guard(request, "settings", token):
            return r
        st = int(stock) if stock.strip().isdigit() else None
        await db.run("UPDATE gifts SET stars=?, stock=?, active=? WHERE id=?", max(1, stars), st,
                     1 if active else 0, gid)
        flash(request, "Saqlandi.")
        return go("/gifts")

    @app.post("/gifts/issue")
    async def gift_issue(request: Request, token: str = Form(""), code: str = Form(...)):
        if r := await guard(request, "gifts", token):
            return r
        sid = request.session.get("staff_id")
        who = await db.one("SELECT username, full_name FROM staff WHERE id=?", sid) if sid else None
        state, o = await db.issue_gift(code, (who["full_name"] or who["username"]) if who else "kassa")
        msg = {"ok": f"Berildi: {o['title'] if o else ''} ({code.upper()}).",
               "used": "Bu sovg'a allaqachon berilgan.", "expired": "Kod muddati o'tgan.",
               "none": "Bunday kod yo'q."}[state]
        flash(request, msg, "ok" if state == "ok" else "err")
        if state == "ok" and bot and o:
            try:
                await bot.send_message(o["parent_id"], f"🎁 «{o['title']}» sovg'asi topshirildi. Rahmat!")
            except Exception:
                pass
        return go("/gifts")

    # ---------- bannerlar ----------
    @app.get("/banners", response_class=HTMLResponse)
    async def banners_page(request: Request):
        if r := await guard(request, "banners"):
            return r
        return await page(request, "banners.html", "banners", rows=await db.banners(only_active=False))

    @app.post("/banners/add")
    async def banner_add(request: Request, token: str = Form(""), title: str = Form(...), text: str = Form(""),
                         link: str = Form(""), image_url: str = Form(""), image: UploadFile | None = File(None)):
        if r := await guard(request, "banners", token):
            return r
        link = link.strip()
        if link and not URL_RE.match(link):
            flash(request, "Havola https:// bilan boshlansin.", "err")
            return go("/banners")
        try:
            img = await save_image(image, image_url)
        except ValueError as e:
            flash(request, str(e), "err")
            return go("/banners")
        await db.run("INSERT INTO banners (title, text, image, link, created_at) VALUES (?,?,?,?,?)",
                     title.strip()[:60], text.strip()[:140], img, link or None, now().strftime("%Y-%m-%d %H:%M:%S"))
        flash(request, "Banner qo'shildi. Ilova bosh ekranida ko'rinadi.")
        return go("/banners")

    @app.post("/banners/{bid}/toggle")
    async def banner_toggle(request: Request, bid: int, token: str = Form("")):
        if r := await guard(request, "banners", token):
            return r
        await db.run("UPDATE banners SET active=1-active WHERE id=?", bid)
        return go("/banners")

    @app.post("/banners/{bid}/delete")
    async def banner_delete(request: Request, bid: int, token: str = Form("")):
        if r := await guard(request, "banners", token):
            return r
        await db.run("DELETE FROM banners WHERE id=?", bid)
        flash(request, "Banner o'chirildi.")
        return go("/banners")

    # ---------- video savollari ----------
    @app.post("/content/{cid}/quiz")
    async def quiz_add(request: Request, cid: int, token: str = Form(""), q: str = Form(...), a: str = Form(...),
                       b: str = Form(...), c: str = Form(""), correct: str = Form("a"), whole: int = Form(0)):
        if r := await guard(request, "content", token):
            return r
        it = await db.get_content(cid)
        if not it or correct not in ("a", "b", "c") or (correct == "c" and not c.strip()):
            flash(request, "Savol va to'g'ri javobni tekshiring.", "err")
            return go(f"/content/{cid}#quiz")
        series = it["series"] if whole and it["series"] else None
        await db.run("INSERT INTO quiz (content_id, series, q, a, b, c, correct) VALUES (?,?,?,?,?,?,?)",
                     None if series else cid, series, q.strip()[:160], a.strip()[:60], b.strip()[:60],
                     c.strip()[:60] or None, correct)
        flash(request, "Savol qo'shildi.")
        return go(f"/content/{cid}#quiz")

    @app.post("/quiz/{qid}/delete")
    async def quiz_delete(request: Request, qid: int, token: str = Form(""), back: int = Form(0)):
        if r := await guard(request, "content", token):
            return r
        await db.run("DELETE FROM quiz WHERE id=?", qid)
        return go(f"/content/{back}#quiz" if back else "/content")

    # ---------- yangi qism xabari ----------
    async def notify_new_episodes(series: str, added: int):
        if not bot or await db.setting("notify_new") != "1":
            return
        url = await db.setting("webapp_url")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Ko'rish", web_app=WebAppInfo(url=url))]]) if url.startswith("https://") else None
        sent = 0
        by_parent: dict[int, list[str]] = {}
        for r in await db.watchers_of_series(series):
            by_parent.setdefault(r["parent_id"], []).append(r["name"])
        for pid, names in by_parent.items():
            who = ", ".join(sorted(set(names))[:3])
            try:
                await bot.send_message(pid, f"🎬 «{series}» serialiga {added} ta yangi qism qo'shildi!\n"
                                            f"{who} uchun Kiddy TV'da tayyor.", reply_markup=kb)
                sent += 1
            except Exception as e:
                logging.info("Yangi qism xabari yuborilmadi %s: %s", pid, e)
            await asyncio.sleep(0.05)
        logging.info("Yangi qism xabari: %s — %s ta oila", series, sent)

    return notify_new_episodes
