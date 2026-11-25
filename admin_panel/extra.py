"""Admin panel: sovg'alar katalogi, kassada sovg'a kodi, banner, video savollari, yangi qism xabari."""
import asyncio
import html as _h
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

    @app.get("/quiz", response_class=HTMLResponse)
    async def quiz_page(request: Request, status: str = "draft", series: str = ""):
        if r := await guard(request, "quiz"):
            return r
        approved = 0 if status == "draft" else 1
        sql = ("SELECT q.*, COALESCE(c.series, q.series) AS ser, c.title AS ctitle FROM quiz q "
               "LEFT JOIN content c ON c.id=q.content_id WHERE q.approved=?")
        a = [approved]
        if series:
            sql += " AND COALESCE(c.series, q.series)=?"
            a.append(series)
        rows = await db.all(sql + " ORDER BY ser, c.episode, q.id LIMIT 400", *a)
        groups = await db.all("SELECT COALESCE(c.series, q.series) AS ser, COUNT(*) n FROM quiz q "
                              "LEFT JOIN content c ON c.id=q.content_id WHERE q.approved=? GROUP BY ser ORDER BY n DESC",
                              approved)
        counts = {r["approved"]: r["n"] for r in await db.all("SELECT approved, COUNT(*) n FROM quiz GROUP BY approved")}
        return await page(request, "quiz.html", "quiz", rows=rows, groups=groups, status=status, series=series,
                          drafts=counts.get(0, 0), live=counts.get(1, 0))

    @app.post("/quiz/approve")
    async def quiz_approve(request: Request):
        form = await request.form()
        if r := await guard(request, "quiz", form.get("token", "")):
            return r
        ids = [int(x) for x in form.getlist("id") if str(x).isdigit()]
        ser = str(form.get("series", ""))
        if form.get("all_series") and ser:
            cur = await db.conn.execute(
                "UPDATE quiz SET approved=1 WHERE approved=0 AND (series=? OR content_id IN "
                "(SELECT id FROM content WHERE series=?))", (ser, ser))
            await db.conn.commit()
            n = cur.rowcount
        else:
            for i in ids:
                await db.run("UPDATE quiz SET approved=1 WHERE id=?", i)
            n = len(ids)
        flash(request, f"{n} ta savol tasdiqlandi — endi ilovada chiqadi.")
        ref = request.headers.get("referer") or ""
        if "/content/" in ref:
            return go(ref[ref.index("/content/"):])
        return go(f"/quiz?status=draft&series={ser}" if ser and not form.get("all_series") else "/quiz?status=draft")

    @app.post("/quiz/{qid}/delete")
    async def quiz_delete(request: Request, qid: int, token: str = Form(""), back: int = Form(0)):
        if r := await guard(request, "content", token):
            return r
        await db.run("DELETE FROM quiz WHERE id=?", qid)
        ref = request.headers.get("referer") or ""
        if "/quiz" in ref and not back:
            return go(ref[ref.index("/quiz"):])
        return go(f"/content/{back}#quiz" if back else "/quiz")

    # ---------- do'kon: ma'lumot va QR ----------
    async def qr_link():
        code = await db.store_qr()
        user = "kiddytvbot"
        if bot:
            try:
                user = (await bot.me()).username
            except Exception:
                pass
        return f"https://t.me/{user}?start=qr_{code}"

    def qr_svg(text: str) -> str:
        import io
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=20, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode().split("?>", 1)[-1]

    @app.get("/store", response_class=HTMLResponse)
    async def store_page(request: Request):
        if r := await guard(request, "store"):
            return r
        link = await qr_link()
        return await page(request, "store.html", "store", st=await db.settings(), link=link, svg=qr_svg(link),
                          stats=await db.checkin_stats())

    @app.get("/store/print", response_class=HTMLResponse)
    async def store_print(request: Request):
        if r := await guard(request, "store"):
            return r
        link = await qr_link()
        st = await db.settings()
        return HTMLResponse(f"""<!doctype html><html lang="uz"><head><meta charset="utf-8"><title>Kiddy TV QR</title>
<style>body{{font-family:system-ui,sans-serif;text-align:center;color:#1F2A6B;margin:30px}}h1{{font-size:44px;margin:0}}
p{{font-size:24px}}svg{{width:420px;height:420px}}.big{{font-size:30px;font-weight:800;color:#E0312B}}
@media print{{button{{display:none}}}}</style></head><body>
<img src="/logo.png" width="110" alt=""><h1>Kiddy TV</h1>
<p class="big">Skanerlang — har hafta +{st['checkin_stars']} yulduz!</p>{qr_svg(link)}
<p>Telefon kamerasini QR kodga qarating yoki Kiddy TV ilovasida «Do'kon QR» tugmasini bosing.</p>
<p><b>{_h.escape(st['store_name'])}</b></p><button onclick="print()" style="font-size:20px;padding:12px 28px">Chop etish</button>
</body></html>""")

    @app.post("/store")
    async def store_save(request: Request):
        form = await request.form()
        if r := await guard(request, "store", form.get("token", "")):
            return r
        for k, lim in (("store_name", 60), ("store_address", 160), ("store_hours", 80), ("store_phone", 40)):
            await db.set_setting(k, str(form.get(k, "")).strip()[:lim])
        m = str(form.get("store_map", "")).strip()
        if m and not URL_RE.match(m):
            flash(request, "Xarita havolasi https:// bilan boshlansin.", "err")
            return go("/store")
        await db.set_setting("store_map", m)
        for key, (lo, hi) in {"checkin_stars": (0, 200), "checkin_days": (1, 60), "remind_days": (1, 30)}.items():
            v = str(form.get(key, "")).strip()
            if v.isdigit() and lo <= int(v) <= hi:
                await db.set_setting(key, int(v))
        flash(request, "Saqlandi.")
        return go("/store")

    @app.post("/store/regenerate")
    async def store_regen(request: Request, token: str = Form("")):
        if r := await guard(request, "store", token):
            return r
        await db.store_qr(regenerate=True)
        flash(request, "Yangi QR yaratildi. Eskisi endi ishlamaydi — yangisini chop etib, almashtiring.")
        return go("/store")

    # ---------- tanlov ko'rgazmasi ----------
    @app.post("/contest/{eid}/exhibit")
    async def contest_exhibit(request: Request, eid: int, token: str = Form("")):
        if r := await guard(request, "contest", token):
            return r
        e = await db.one("SELECT * FROM contest WHERE id=?", eid)
        if not e:
            return go("/contest")
        await db.run("UPDATE contest SET exhibit=1 WHERE id=?", eid)
        c = await db.child(e["child_id"]) if e["child_id"] else None
        info = await db.store_info()
        where = f"\n📍 {info['address']}" if info["address"] else ""
        if bot and not e["exhibit"]:
            try:
                await bot.send_message(e["parent_id"], f"🖼 <b>{c['name'] if c else 'Farzandingiz'}ning rasmi Kiddy Toys "
                                                       f"do'konida ko'rgazmaga qo'yildi!</b>\n\nKelib, birga ko'ring — "
                                                       f"rasmingiz devorimizda!{where}")
            except Exception:
                pass
        flash(request, "Ko'rgazmaga qo'shildi, oilaga xabar yuborildi.")
        return go("/contest")

    @app.get("/contest/gallery", response_class=HTMLResponse)
    async def contest_gallery(request: Request):
        if r := await guard(request, "contest"):
            return r
        from db import age_of
        st = await db.settings()
        cards = "".join(
            f"<figure><img src='/tg-file/{_h.escape(e['file_id'])}' alt=''><figcaption><b>{_h.escape(e['child_name'] or 'Bola')}</b>"
            f"{', ' + str(age_of(e['birth_date'], now().date())) + ' yosh' if e['birth_date'] else ''}"
            f"{' · 🏆 G‘olib' if e['winner'] else ''}</figcaption></figure>" for e in await db.exhibit_entries())
        return HTMLResponse(f"""<!doctype html><html lang="uz"><head><meta charset="utf-8"><title>Ko'rgazma</title>
<style>body{{font-family:system-ui,sans-serif;color:#1F2A6B;margin:24px}}h1{{text-align:center;font-size:40px;margin:0}}
.sub{{text-align:center;font-size:20px;margin:6px 0 24px}}.g{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}}
figure{{margin:0;border:6px solid #F28C1E;border-radius:22px;padding:10px;break-inside:avoid}}
img{{width:100%;aspect-ratio:1;object-fit:contain;border-radius:12px;background:#fff}}
figcaption{{text-align:center;font-size:20px;margin-top:8px}}@media print{{button{{display:none}}}}</style></head><body>
<h1>Kiddy TV ijod ko'rgazmasi</h1><p class="sub">Mavzu: «{_h.escape(st['contest_title'])}»</p>
<div class="g">{cards or "<p>Hali ko'rgazmaga rasm qo'yilmagan.</p>"}</div>
<p style="text-align:center"><button onclick="print()" style="font-size:20px;padding:12px 28px">Chop etish</button></p></body></html>""")

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
