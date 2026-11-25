"""Kiddy TV — do'kon xodimlari uchun admin panel (FastAPI)."""
import asyncio
import logging
import os
import re
import secrets
import tempfile
from datetime import timedelta

from aiogram import Bot
from aiogram.types import FSInputFile
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import config
from db import DB, age_of, now, parse_tiers
from youtube_import import fetch_list

HERE = os.path.dirname(__file__)
YT_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/\S+$")
URL_RE = re.compile(r"^https?://\S+$")
ROLE_PAGES = {"kassir": {"coupons"}}  # kassir faqat kuponlarni ko'radi
MAX_UPLOAD_MB = 50  # Telegram bot API cheklovi

KIND_LABELS = config.KINDS
RECOMMENDED = [  # rasmiy / taniqli o'zbekcha bolalar kanallari (qo'shishdan oldin ko'rib chiqing)
    {"name": "Bek va Lola", "url": "https://www.youtube.com/@BekvaLola", "kind": "cartoon", "a": 2, "b": 7,
     "note": "O'zbek multserial: odob, hafta kunlari, mevalar, ertaklar"},
    {"name": "O'zbek bolalar qo'shiqlari", "url": "https://www.youtube.com/@ozbekbolalarqoshiqlari8677",
     "kind": "video", "a": 1, "b": 6, "note": "Kichkintoylar uchun qo'shiqlar"},
]
REASONS = {"stars": "Yulduz", "birthday": "Tug'ilgan kun", "contest": "Tanlov", "manual": "Qo'lda"}


def create_app(db: DB, bot: Bot | None) -> FastAPI:
    app = FastAPI(title="Kiddy TV admin", docs_url=None, redoc_url=None, openapi_url=None)
    secret = os.getenv("PANEL_SECRET") or _secret_file()
    app.add_middleware(SessionMiddleware, secret_key=secret, max_age=12 * 3600, same_site="lax")
    tpl = Jinja2Templates(directory=os.path.join(HERE, "templates"))
    tpl.env.globals.update(KINDS=KIND_LABELS, REASONS=REASONS)
    tpl.env.filters["age"] = lambda b: age_of(b, now().date()) if b else ""
    tpl.env.filters["hm"] = lambda m: (f"{m // 60} s {m % 60} d" if m >= 60 else f"{m} daq")

    # ---------- yordamchilar ----------
    def flash(request: Request, text: str, kind: str = "ok"):
        request.session.setdefault("flash", []).append([kind, text])

    async def current(request: Request):
        sid = request.session.get("staff_id")
        if not sid:
            return None
        return await db.one("SELECT * FROM staff WHERE id=? AND active=1", sid)

    async def page(request: Request, name: str, section: str, **ctx):
        user = await current(request)
        msgs = request.session.pop("flash", [])
        return tpl.TemplateResponse(request, name, {"user": user, "section": section, "flashes": msgs,
                                                    "bot_ok": bot is not None, "csrf": csrf(request),
                                                    "age_on": await db.setting("age_limit") != "0", **ctx})

    def csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(16)
        return request.session["csrf"]

    def go(url: str):
        return RedirectResponse(url, status_code=303)

    async def guard(request: Request, section: str, post_token: str | None = None):
        """None bo'lsa ruxsat; aks holda qaytariladigan javob."""
        user = await current(request)
        if not user:
            if await db.staff_count() == 0:
                return go("/setup")
            return go("/login")
        allowed = ROLE_PAGES.get(user["role"])
        if allowed is not None and section not in allowed:
            return go("/coupons")
        if post_token is not None and post_token != request.session.get("csrf"):
            flash(request, "Sahifa eskirgan, qaytadan urinib ko'ring.", "err")
            return go(request.headers.get("referer") or "/")
        return None

    # ---------- kirish ----------
    @app.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request):
        if await db.staff_count():
            return go("/login")
        return await page(request, "setup.html", "setup")

    @app.post("/setup")
    async def setup_post(request: Request, username: str = Form(...), full_name: str = Form(""),
                         password: str = Form(...)):
        if await db.staff_count():
            return go("/login")
        if len(password) < 6 or not re.match(r"^[a-zA-Z0-9_.]{3,30}$", username):
            flash(request, "Login 3–30 ta lotin harf/raqam, parol kamida 6 belgi bo'lsin.", "err")
            return go("/setup")
        sid = await db.add_staff(username, password, "admin", full_name)
        request.session["staff_id"] = sid
        flash(request, "Xush kelibsiz! Birinchi admin yaratildi.")
        return go("/")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if await db.staff_count() == 0:
            return go("/setup")
        return await page(request, "login.html", "login")

    @app.post("/login")
    async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
        await asyncio.sleep(0.4)  # parol terib topishni sekinlashtirish
        user = await db.check_staff(username, password)
        if not user:
            flash(request, "Login yoki parol noto'g'ri.", "err")
            return go("/login")
        request.session.clear()
        request.session["staff_id"] = user["id"]
        return go("/" if user["role"] == "admin" else "/coupons")

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return go("/login")

    # ---------- bosh sahifa ----------
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if r := await guard(request, "dashboard"):
            return r
        stats = await db.stats_overview()
        n = now()
        month = n.strftime("%Y-%m")
        extra = await db.one(
            "SELECT (SELECT COUNT(*) FROM coupons WHERE used_at IS NULL AND expires_at>=?) active_c, "
            "(SELECT COUNT(*) FROM coupons WHERE substr(used_at,1,7)=?) used_month, "
            "(SELECT COUNT(*) FROM coupons WHERE substr(created_at,1,7)=?) issued_month, "
            "(SELECT COUNT(*) FROM contest) contest_n, "
            "(SELECT COUNT(*) FROM parents WHERE created_at>=?) new_week",
            n.strftime("%Y-%m-%d %H:%M:%S"), month, month, (n - timedelta(days=7)).strftime("%Y-%m-%d"))
        days = await db.views_by_day(14)
        peak = max([d["views"] for d in days] + [1])
        split = await db.kind_split()
        total = sum(r["n"] for r in split) or 1
        return await page(request, "dashboard.html", "dashboard", s=stats, x=extra, days=days, peak=peak,
                          split=split, total=total, top_c=await db.top_content(5, days=7),
                          top_k=await db.top_children(5, days=7))

    # ---------- kontent ----------
    @app.get("/content", response_class=HTMLResponse)
    async def content_list(request: Request, kind: str = "", q: str = "", hidden: int = 0):
        if r := await guard(request, "content"):
            return r
        rows = await db.admin_content(kind or None, q or None, bool(hidden))
        return await page(request, "content.html", "content", rows=rows, kind=kind, q=q, hidden=hidden,
                          max_mb=MAX_UPLOAD_MB)

    @app.post("/content/add")
    async def content_add(request: Request, token: str = Form(""), kind: str = Form(...), title: str = Form(...),
                          age_min: int = Form(0), age_max: int = Form(12), minutes: int = Form(0),
                          link: str = Form(""), file: UploadFile | None = File(None)):
        if r := await guard(request, "content", token):
            return r
        title = title.strip()[:80]
        if kind not in KIND_LABELS or not title or not (0 <= age_min <= age_max <= 14):
            flash(request, "Bo'lim, nom va yoshni to'g'ri kiriting (yosh 0–14).", "err")
            return go("/content")
        link = link.strip()
        has_file = file is not None and file.filename
        if has_file:
            if bot is None:
                flash(request, "Fayl yuklash uchun .env da BOT_TOKEN kerak.", "err")
                return go("/content")
            try:
                file_id, ftype, dur = await upload_to_telegram(file)
            except ValueError as e:
                flash(request, str(e), "err")
                return go("/content")
            minutes = minutes or (max(1, round(dur / 60)) if dur else 5)
            cid = await db.add_content(kind, title, "file", file_id, ftype, age_min, age_max, minutes)
        elif link:
            if kind == "game":
                if not URL_RE.match(link):
                    flash(request, "O'yin havolasi https:// bilan boshlansin.", "err")
                    return go("/content")
                st = "link"
            else:
                if not YT_RE.match(link):
                    flash(request, "YouTube havolasini kiriting (youtube.com yoki youtu.be).", "err")
                    return go("/content")
                st = "youtube"
            cid = await db.add_content(kind, title, st, link, None, age_min, age_max, minutes or 5)
        else:
            flash(request, "YouTube havola yoki fayl kerak.", "err")
            return go("/content")
        flash(request, f"Qo'shildi: {title} (ID {cid}). Bot ro'yxatida darhol ko'rinadi.")
        return go(f"/content?kind={kind}")

    async def upload_to_telegram(file: UploadFile):
        ctype = (file.content_type or "").lower()
        if ctype.startswith("video/"):
            ftype = "video"
        elif ctype.startswith("audio/"):
            ftype = "audio"
        else:
            raise ValueError("Faqat video yoki audio fayl yuklang (mp4, mp3, m4a...).")
        storage = int(os.getenv("STORAGE_CHAT_ID") or next(iter(config.ADMIN_IDS), 0))
        if not storage:
            raise ValueError(".env da STORAGE_CHAT_ID yoki ADMIN_IDS ko'rsating (fayllar shu chatga saqlanadi).")
        suffix = os.path.splitext(file.filename)[1][:8]
        size = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    tmp.close()
                    os.unlink(tmp.name)
                    raise ValueError(f"Fayl {MAX_UPLOAD_MB} MB dan katta. Kichikroq qiling yoki YouTube'ga joylang.")
                tmp.write(chunk)
            path = tmp.name
        try:
            inp = FSInputFile(path, filename=file.filename)
            if ftype == "video":
                m = await bot.send_video(storage, inp, caption="Kiddy TV kontent", supports_streaming=True)
                return m.video.file_id, "video", m.video.duration
            m = await bot.send_audio(storage, inp, caption="Kiddy TV kontent")
            return m.audio.file_id, "audio", m.audio.duration
        except Exception as e:
            logging.exception("Yuklash xatosi")
            raise ValueError(f"Telegram'ga yuklab bo'lmadi: {e}")
        finally:
            os.unlink(path)

    @app.get("/content/{cid}", response_class=HTMLResponse)
    async def content_edit_page(request: Request, cid: int):
        if r := await guard(request, "content"):
            return r
        item = (await db.all("SELECT c.*, (SELECT COUNT(*) FROM views v WHERE v.content_id=c.id) views, "
                             "(SELECT COUNT(*) FROM likes l WHERE l.content_id=c.id) likes "
                             "FROM content c WHERE c.id=?", cid))
        if not item:
            return go("/content")
        return await page(request, "content_edit.html", "content", it=item[0])

    @app.post("/content/{cid}")
    async def content_edit(request: Request, cid: int, token: str = Form(""), title: str = Form(...),
                           kind: str = Form(...), age_min: int = Form(...), age_max: int = Form(...),
                           minutes: int = Form(...), active: int = Form(0), link: str = Form("")):
        if r := await guard(request, "content", token):
            return r
        item = await db.get_content(cid)
        if not item or kind not in KIND_LABELS or not (0 <= age_min <= age_max <= 14) or not (1 <= minutes <= 300):
            flash(request, "Ma'lumotlar noto'g'ri.", "err")
            return go(f"/content/{cid}")
        fields = dict(title=title.strip()[:80], kind=kind, age_min=age_min, age_max=age_max, minutes=minutes,
                      active=1 if active else 0)
        if item["source_type"] != "file" and link.strip():
            ok = URL_RE.match(link.strip()) if item["source_type"] == "link" else YT_RE.match(link.strip())
            if not ok:
                flash(request, "Havola noto'g'ri.", "err")
                return go(f"/content/{cid}")
            fields["source"] = link.strip()
        await db.update_content(cid, **fields)
        flash(request, "Saqlandi.")
        return go(f"/content?kind={kind}")

    @app.post("/content/{cid}/toggle")
    async def content_toggle(request: Request, cid: int, token: str = Form("")):
        if r := await guard(request, "content", token):
            return r
        item = await db.get_content(cid)
        if item:
            await db.update_content(cid, active=0 if item["active"] else 1)
            flash(request, f"{item['title']}: " + ("yashirildi" if item["active"] else "qayta ko'rinadi"))
        return go(request.headers.get("referer") or "/content")

    # ---------- YouTube'dan import ----------
    previews: dict[str, dict] = {}

    @app.get("/import", response_class=HTMLResponse)
    async def import_page(request: Request, url: str = "", kind: str = "cartoon", a: int = 3, b: int = 8):
        if r := await guard(request, "content"):
            return r
        return await page(request, "import.html", "content", rec=RECOMMENDED, url=url, kind=kind, a=a, b=b,
                          preview=None)

    @app.post("/import/preview", response_class=HTMLResponse)
    async def import_preview(request: Request, token: str = Form(""), url: str = Form(...),
                             kind: str = Form("cartoon"), a: int = Form(3), b: int = Form(8)):
        if r := await guard(request, "content", token):
            return r
        try:
            data = await fetch_list(url)
        except ValueError as e:
            flash(request, str(e), "err")
            return go(f"/import?kind={kind}&a={a}&b={b}")
        if not data["items"]:
            flash(request, "Bu havolada video topilmadi.", "err")
            return go("/import")
        have = await db.existing_youtube_ids()
        for it in data["items"]:
            it["exists"] = it["id"] in have
        key = secrets.token_urlsafe(8)
        previews[key] = {**data, "at": now()}
        for k in list(previews)[:-20]:  # eski ko'rinishlarni tozalash
            previews.pop(k, None)
        new_n = sum(1 for i in data["items"] if not i["exists"])
        return await page(request, "import.html", "content", rec=RECOMMENDED, url=url, kind=kind, a=a, b=b,
                          preview=data, key=key, new_n=new_n)

    @app.post("/import/save")
    async def import_save(request: Request):
        form = await request.form()
        if r := await guard(request, "content", form.get("token", "")):
            return r
        data = previews.pop(str(form.get("key", "")), None)
        if not data:
            flash(request, "Ko'rinish eskirgan, qaytadan oching.", "err")
            return go("/import")
        kind = str(form.get("kind", "cartoon"))
        try:
            a, b = int(form.get("a", 0)), int(form.get("b", 12))
            default_min = int(form.get("minutes") or 5)
        except ValueError:
            a, b, default_min = -1, -1, 5
        if kind not in KIND_LABELS or not (0 <= a <= b <= 14):
            flash(request, "Bo'lim va yoshni to'g'ri tanlang.", "err")
            return go("/import")
        chosen = set(form.getlist("v"))
        series = str(form.get("series", "")).strip()[:60] or None
        have = await db.existing_youtube_ids()
        added = 0
        ep = 0
        for it in data["items"]:
            if it["id"] not in chosen or it["id"] in have:
                continue
            ep += 1
            await db.add_content(kind, it["title"] or f"{series or 'Video'} {ep}", "youtube",
                                 f"https://www.youtube.com/watch?v={it['id']}", None, a, b,
                                 min(300, it["minutes"] or default_min), series, ep if series else None)
            added += 1
        flash(request, f"{added} ta video qo'shildi" + (f" («{series}» seriali)" if series else "") +
              ". Botda va ilovada darhol ko'rinadi.")
        return go(f"/content?kind={kind}")

    # ---------- kuponlar ----------
    @app.get("/coupons", response_class=HTMLResponse)
    async def coupons(request: Request, status: str = "active", q: str = "", check: str = ""):
        if r := await guard(request, "coupons"):
            return r
        found = None
        if check:
            found = await db.one("SELECT cp.*, ch.name child_name FROM coupons cp "
                                 "LEFT JOIN children ch ON ch.id=cp.child_id WHERE cp.code=?", check.strip().upper())
        rows = await db.admin_coupons(status, q or None)
        return await page(request, "coupons.html", "coupons", rows=rows, status=status, q=q, check=check,
                          found=found, now_s=now().strftime("%Y-%m-%d %H:%M:%S"))

    @app.post("/coupons/use")
    async def coupon_use(request: Request, token: str = Form(""), code: str = Form(...)):
        if r := await guard(request, "coupons", token):
            return r
        user = await current(request)
        status, c = await db.use_coupon(code, f"panel:{user['username']}")
        msg = {"ok": (f"Kupon {code.upper()} ishlatildi: {c['percent']}% chegirma bering.", "ok"),
               "used": ("Bu kupon allaqachon ishlatilgan.", "err"),
               "expired": ("Kupon muddati o'tgan.", "err"),
               "not_found": ("Bunday kupon yo'q.", "err")}[status]
        flash(request, *msg)
        if status == "ok" and bot:
            try:
                await bot.send_message(c["parent_id"], f"Kupon <code>{c['code']}</code> Kiddy Toys do'konida "
                                                       f"ishlatildi ({c['percent']}%). Xaridingiz uchun rahmat!")
            except Exception:
                pass
        return go(f"/coupons?check={code.strip().upper()}")

    # ---------- reytinglar ----------
    @app.get("/ratings", response_class=HTMLResponse)
    async def ratings(request: Request, period: str = "7"):
        if r := await guard(request, "ratings"):
            return r
        days = {"7": 7, "30": 30}.get(period)
        return await page(request, "ratings.html", "ratings", period=period,
                          kids=await db.top_children(20, days=days),
                          views=await db.top_content(15, days=days, order="views"),
                          liked=await db.top_content(15, order="likes"))

    # ---------- yosh chegarasi ----------
    @app.post("/age-limit")
    async def age_limit_toggle(request: Request, token: str = Form(""), back: str = Form("/content")):
        if r := await guard(request, "content", token):
            return r
        on = await db.setting("age_limit") != "0"
        await db.set_setting("age_limit", "0" if on else "1")
        flash(request, "Yosh chegarasi olib tashlandi — endi hamma kontent hamma bolalarga ochiq." if on
              else "Yosh chegarasi qo'yildi — har bir bolaga faqat o'z yoshiga mos kontent ko'rinadi.")
        return go(back if back.startswith("/") and not back.startswith("//") else "/content")

    # ---------- oilalar ----------
    @app.get("/families", response_class=HTMLResponse)
    async def families(request: Request, q: str = ""):
        if r := await guard(request, "families"):
            return r
        rows = await db.families(q or None)
        kids = {}
        for c in await db.all("SELECT * FROM children ORDER BY id"):
            kids.setdefault(c["parent_id"], []).append(c)
        return await page(request, "families.html", "families", rows=rows, kids=kids, q=q)

    @app.post("/families/{child_id}/coupon")
    async def give_coupon(request: Request, child_id: int, token: str = Form(""), percent: int = Form(...)):
        if r := await guard(request, "families", token):
            return r
        c = await db.child(child_id)
        if not c or not (1 <= percent <= 50):
            flash(request, "Foiz 1–50 oralig'ida bo'lsin.", "err")
            return go("/families")
        code = await db.make_coupon(c["parent_id"], c["id"], percent, 0, "manual")
        sent = await notify(c["parent_id"], f"Kiddy Toys'dan {c['name']} uchun sovg'a kuponi: <code>{code}</code> — "
                                            f"{percent}% chegirma. Do'konda kassirga ko'rsating.")
        flash(request, f"{c['name']} uchun kupon: {code}" + (" (botga yuborildi)" if sent else ""))
        return go("/families")

    async def notify(chat_id, text) -> bool:
        if not bot:
            return False
        try:
            await bot.send_message(chat_id, text)
            return True
        except Exception:
            return False

    # ---------- tanlov ----------
    @app.get("/contest", response_class=HTMLResponse)
    async def contest(request: Request):
        if r := await guard(request, "contest"):
            return r
        return await page(request, "contest.html", "contest", rows=await db.contest_entries(),
                          st=await db.settings())

    @app.post("/contest/{eid}/win")
    async def contest_win(request: Request, eid: int, token: str = Form("")):
        if r := await guard(request, "contest", token):
            return r
        e = await db.one("SELECT * FROM contest WHERE id=?", eid)
        if not e or e["winner"]:
            return go("/contest")
        pct = int(await db.setting("contest_percent"))
        code = await db.make_coupon(e["parent_id"], e["child_id"], pct, 0, "contest")
        await db.run("UPDATE contest SET winner=1 WHERE id=?", eid)
        c = await db.child(e["child_id"]) if e["child_id"] else None
        name = c["name"] if c else "Farzandingiz"
        sent = await notify(e["parent_id"], f"<b>Tabriklaymiz!</b> {name} ijod tanlovida g'olib bo'ldi!\n\n"
                                            f"Sovg'a kuponi: <code>{code}</code> — {pct}% chegirma. "
                                            "Kiddy Toys do'konida kassirga ko'rsating.")
        flash(request, f"G'olib belgilandi, kupon {code}" + (" yuborildi." if sent else " (bot ulanmagan)."))
        return go("/contest")

    @app.get("/tg-file/{file_id}")
    async def tg_file(request: Request, file_id: str):
        if await guard(request, "contest"):
            return Response(status_code=403)
        if not bot:
            return Response(status_code=404)
        try:
            f = await bot.get_file(file_id)
            data = await bot.download_file(f.file_path)
            return Response(data.read(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
        except Exception:
            return Response(status_code=404)

    # ---------- xabar yuborish ----------
    @app.get("/broadcast", response_class=HTMLResponse)
    async def broadcast_page(request: Request):
        if r := await guard(request, "broadcast"):
            return r
        n = (await db.one("SELECT COUNT(*) c FROM parents"))["c"]
        return await page(request, "broadcast.html", "broadcast", total=n)

    @app.post("/broadcast")
    async def broadcast(request: Request, token: str = Form(""), text: str = Form(...)):
        if r := await guard(request, "broadcast", token):
            return r
        text = text.strip()
        if not text or not bot:
            flash(request, "Matn bo'sh yoki bot ulanmagan.", "err")
            return go("/broadcast")
        ids = [r["tg_id"] for r in await db.all("SELECT tg_id FROM parents")]

        async def send_all():
            for i in ids:
                await notify(i, text)
                await asyncio.sleep(0.05)
        asyncio.create_task(send_all())
        flash(request, f"Xabar {len(ids)} ta ota-onaga yuborilmoqda.")
        return go("/broadcast")

    # ---------- sozlamalar ----------
    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        if r := await guard(request, "settings"):
            return r
        st = await db.settings()
        tiers = parse_tiers(st["reward_tiers"])
        tiers += [("", "")] * (4 - len(tiers))
        return await page(request, "settings.html", "settings", st=st, tiers=tiers[:4])

    @app.post("/settings")
    async def settings_save(request: Request):
        form = await request.form()
        if r := await guard(request, "settings", form.get("token", "")):
            return r
        nums = {"stars_per_view": (1, 100), "birthday_percent": (0, 50), "coupon_days": (1, 365),
                "default_daily_limit": (15, 240), "contest_percent": (0, 50)}
        for key, (lo, hi) in nums.items():
            v = str(form.get(key, "")).strip()
            if not v.isdigit() or not (lo <= int(v) <= hi):
                flash(request, f"«{key}» {lo}–{hi} oralig'ida bo'lsin.", "err")
                return go("/settings")
            await db.set_setting(key, int(v))
        tiers = []
        for i in range(4):
            p, c = str(form.get(f"tp{i}", "")).strip(), str(form.get(f"tc{i}", "")).strip()
            if p and c:
                if not (p.isdigit() and c.isdigit() and 1 <= int(p) <= 50 and int(c) >= 1):
                    flash(request, "Chegirma 1–50%, yulduz 1 dan ko'p bo'lsin.", "err")
                    return go("/settings")
                tiers.append(f"{int(p)}:{int(c)}")
        if not tiers:
            flash(request, "Kamida bitta chegirma tarifi kerak.", "err")
            return go("/settings")
        await db.set_setting("reward_tiers", ",".join(tiers))
        title = str(form.get("contest_title", "")).strip()[:80]
        if title:
            await db.set_setting("contest_title", title)
        flash(request, "Sozlamalar saqlandi. Bot darhol yangi qiymatlardan foydalanadi.")
        return go("/settings")

    # ---------- xodimlar ----------
    @app.get("/staff", response_class=HTMLResponse)
    async def staff_page(request: Request):
        if r := await guard(request, "staff"):
            return r
        return await page(request, "staff.html", "staff", rows=await db.all_staff())

    @app.post("/staff/add")
    async def staff_add(request: Request, token: str = Form(""), username: str = Form(...),
                        full_name: str = Form(""), password: str = Form(...), role: str = Form("kassir")):
        if r := await guard(request, "staff", token):
            return r
        if role not in ("admin", "kassir") or len(password) < 6 or not re.match(r"^[a-zA-Z0-9_.]{3,30}$", username):
            flash(request, "Login 3–30 lotin harf/raqam, parol kamida 6 belgi.", "err")
            return go("/staff")
        if await db.one("SELECT 1 FROM staff WHERE username=?", username.lower()):
            flash(request, "Bu login band.", "err")
            return go("/staff")
        await db.add_staff(username, password, role, full_name)
        flash(request, f"Xodim qo'shildi: {username} ({role})")
        return go("/staff")

    @app.post("/staff/{sid}/toggle")
    async def staff_toggle(request: Request, sid: int, token: str = Form("")):
        if r := await guard(request, "staff", token):
            return r
        me = await current(request)
        s = await db.one("SELECT * FROM staff WHERE id=?", sid)
        if not s or s["id"] == me["id"]:
            flash(request, "O'zingizni o'chira olmaysiz.", "err")
            return go("/staff")
        await db.run("UPDATE staff SET active=? WHERE id=?", 0 if s["active"] else 1, sid)
        return go("/staff")

    @app.post("/staff/{sid}/password")
    async def staff_pw(request: Request, sid: int, token: str = Form(""), password: str = Form(...)):
        if r := await guard(request, "staff", token):
            return r
        if len(password) < 6:
            flash(request, "Parol kamida 6 belgi.", "err")
            return go("/staff")
        from db import hash_password
        await db.run("UPDATE staff SET pw_hash=? WHERE id=?", hash_password(password), sid)
        flash(request, "Parol yangilandi.")
        return go("/staff")

    @app.get("/logo.png")
    async def logo():
        path = os.path.join(os.path.dirname(HERE), "assets", "logo.png")
        with open(path, "rb") as f:
            return Response(f.read(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    return app


def _secret_file() -> str:
    """Sessiya kaliti: .panel_secret faylida saqlanadi (birinchi marta o'zi yaratiladi)."""
    path = os.path.join(os.path.dirname(HERE), ".panel_secret")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()
