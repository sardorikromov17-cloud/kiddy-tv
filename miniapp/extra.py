"""Mini App: davom ettirish, sevimlilar, qidiruv, seriya, daraja/nishonlar, sovg'alar, banner, savollar."""
import logging
import time as _time

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from db import age_of, now, parse_tiers

LEVELS = [(0, "Kichik tomoshabin"), (50, "Qiziquvchan"), (150, "Bilimdon"), (300, "Zukko"),
          (600, "Kiddy yulduzi"), (1200, "Kiddy qahramoni")]

# (id, nomi, izoh, rang, qiymatni olish, kerak)
BADGES = [
    ("first", "Birinchi qadam", "Birinchi kontentni ko'rding", "orange",
     lambda s: sum(s["kinds"].values()), 1),
    ("cartoon", "Multfilm muxlisi", "10 ta multfilm ko'r", "red", lambda s: s["kinds"].get("cartoon", 0), 10),
    ("audio", "Ertakchi", "10 ta ertak tingla", "blue", lambda s: s["kinds"].get("audio", 0), 10),
    ("music", "Qo'shiqchi", "10 ta qo'shiq tingla", "green", lambda s: s["kinds"].get("music", 0), 10),
    ("islamic", "Odobli bola", "10 ta islomiy multfilm ko'r", "green", lambda s: s["kinds"].get("islamic", 0), 10),
    ("games", "O'yinchi", "20 marta o'yna", "orange", lambda s: s["games"], 20),
    ("quiz", "Zukko", "10 ta savolga to'g'ri javob ber", "blue", lambda s: s["quiz_ok"], 10),
    ("streak7", "Haftalik qahramon", "7 kun ketma-ket kir", "red", lambda s: s["best_streak"], 7),
    ("streak30", "Oylik qahramon", "30 kun ketma-ket kir", "orange", lambda s: s["best_streak"], 30),
    ("artist", "Rassom", "Tanlovga rasm yubor", "blue", lambda s: s["contest"], 1),
    ("likes", "Didli tomoshabin", "10 ta kontentga «Yoqdi» bos", "red", lambda s: s["likes"], 10),
]


def level_of(total: int):
    total = total or 0
    idx = max(i for i, (need, _) in enumerate(LEVELS) if total >= need)
    cur_need, name = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    return {"n": idx + 1, "name": name, "total": total, "from": cur_need,
            "next": nxt[0] if nxt else None, "next_name": nxt[1] if nxt else None}


def register(app, db, bot, auth, err, body, item_out, youtube_id):
    img_cache: dict[str, tuple[str, float]] = {}

    async def child_ctx(request):
        user, p = await auth(request)
        if not user:
            return None, None, None
        c = await db.active_child(p["tg_id"])
        return p, c, (age_of(c["birth_date"], now().date()) if c else None)

    def img_url(kind, row):
        return f"/api/img/{kind}/{row['id']}" if row["image"] else None

    # ---------- bosh ekran qatorlari ----------
    @app.get("/api/home")
    async def home(request: Request):
        p, c, age = await child_ctx(request)
        if not p:
            return err("auth", 401)
        banners = [{"id": b["id"], "title": b["title"], "text": b["text"] or "", "link": b["link"] or "",
                    "img": img_url("banner", b)} for b in await db.banners()]
        if not c:
            return {"ok": True, "banners": banners, "recent": [], "cont": [], "streak": 0, "bonus": 0}
        streak, bonus = await db.touch_day(c["id"])
        recent = []
        if await db.setting("show_recent") == "1":
            for r in await db.recent(c["id"], age, p["tg_id"]):
                o = item_out(r)
                o["pos"] = r["pos"] or 0
                recent.append(o)
        cont = [item_out(r) for r in await db.continue_series(c["id"], age, p["tg_id"])] \
            if await db.setting("show_continue") == "1" else []
        child = await db.child(c["id"])
        return {"ok": True, "banners": banners, "recent": recent, "cont": cont, "streak": streak, "bonus": bonus,
                "stars": child["stars"], "level": level_of(child["total_stars"])}

    @app.get("/api/favorites")
    async def favorites(request: Request):
        p, c, age = await child_ctx(request)
        if not p:
            return err("auth", 401)
        rows = await db.favorites(c["id"], age, p["tg_id"]) if c else []
        return {"ok": True, "items": [item_out(r) for r in rows]}

    @app.get("/api/search")
    async def search(request: Request, q: str = ""):
        p, c, age = await child_ctx(request)
        if not p:
            return err("auth", 401)
        rows = await db.search(q[:60], age, p["tg_id"]) if c else []
        return {"ok": True, "items": [item_out(r) for r in rows]}

    @app.post("/api/pos")
    async def save_pos(request: Request):
        p, c, _ = await child_ctx(request)
        if not p or not c:
            return err("auth", 401)
        d = await body(request)
        try:
            await db.save_pos(int(d.get("view_id", 0)), c["id"], float(d.get("pos", 0)))
        except (TypeError, ValueError):
            return err("Xato so'rov")
        return {"ok": True}

    # ---------- daraja va nishonlar ----------
    @app.get("/api/profile")
    async def profile(request: Request):
        p, c, _ = await child_ctx(request)
        if not p or not c:
            return err("auth", 401)
        st = await db.child_stats(c["id"])
        child = await db.child(c["id"])
        badges = []
        for bid, title, desc, color, fn, need in BADGES:
            cur = int(fn(st))
            badges.append({"id": bid, "title": title, "desc": desc, "color": color, "cur": min(cur, need),
                           "need": need, "done": cur >= need})
        return {"ok": True, "level": level_of(child["total_stars"]), "streak": await db.streak(c["id"]),
                "best_streak": st["best_streak"], "badges": badges,
                "streak_tiers": [{"days": a, "stars": b} for a, b in
                                 sorted(dict(parse_tiers(await db.setting("streak_bonus"))).items())]}

    # ---------- sovg'alar ----------
    @app.get("/api/gifts")
    async def gifts(request: Request):
        p, c, _ = await child_ctx(request)
        if not p:
            return err("auth", 401)
        items = [{"id": g["id"], "title": g["title"], "note": g["note"] or "", "stars": g["stars"],
                  "stock": g["stock"], "img": img_url("gift", g)} for g in await db.gifts_list()]
        orders = [{"code": o["code"], "title": o["title"], "issued": bool(o["issued_at"]),
                   "until": o["expires_at"][:10]} for o in await db.gift_orders(parent_id=p["tg_id"], limit=20)]
        return {"ok": True, "items": items, "orders": orders}

    @app.post("/api/gift/redeem")
    async def gift_redeem(request: Request):
        p, c, _ = await child_ctx(request)
        if not p or not c:
            return err("auth", 401)
        d = await body(request)
        code, why = await db.redeem_gift(p["tg_id"], c["id"], int(d.get("id", 0) or 0))
        if not code:
            return err(why)
        g = await db.one("SELECT title FROM gifts WHERE id=?", int(d.get("id", 0) or 0))
        if bot:
            try:
                await bot.send_message(p["tg_id"], f"🎁 {c['name']} yulduzlarini sovg'aga almashtirdi: <b>{g['title']}</b>\n"
                                                   f"Kod: <code>{code}</code>\nKiddy Toys do'konida kassirga ko'rsating.")
            except Exception:
                pass
        return {"ok": True, "code": code, "title": g["title"], "stars": (await db.child(c["id"]))["stars"]}

    @app.get("/api/img/{kind}/{rid}")
    async def img(kind: str, rid: int):
        table = {"gift": "gifts", "banner": "banners"}.get(kind)
        if not table:
            return Response(status_code=404)
        r = await db.one(f"SELECT image FROM {table} WHERE id=?", rid)
        if not r or not r["image"]:
            return Response(status_code=404)
        src = r["image"]
        if src.startswith("http"):
            return RedirectResponse(src)
        if not bot:
            return Response(status_code=404)
        try:
            path, exp = img_cache.get(src, ("", 0))
            if exp < _time.time():
                f = await bot.get_file(src)
                path = f.file_path
                img_cache[src] = (path, _time.time() + 3000)
            data = await bot.download_file(path)
            return Response(data.read(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
        except Exception as e:
            logging.warning("Rasm berilmadi: %s", e)
            return Response(status_code=502)

    # ---------- do'st taklifi ----------
    @app.get("/api/invite")
    async def invite(request: Request):
        p, c, _ = await child_ctx(request)
        if not p:
            return err("auth", 401)
        username = ""
        if bot:
            try:
                username = (await bot.me()).username
            except Exception:
                pass
        link = f"https://t.me/{username}?start={db.ref_code(p['tg_id'])}" if username else ""
        st = await db.ref_stats(p["tg_id"])
        return {"ok": True, "link": link, **st, "bonus": int(await db.setting("ref_bonus")),
                "new_bonus": int(await db.setting("ref_new_bonus"))}

    # ---------- do'kon: QR tashrif va ma'lumot ----------
    @app.post("/api/checkin")
    async def checkin(request: Request):
        p, c, _ = await child_ctx(request)
        if not p:
            return err("auth", 401)
        d = await body(request)
        raw = str(d.get("code", ""))[:300]
        m = __import__("re").search(r"qr_([A-Za-z0-9]+)", raw)
        stars, text = await db.checkin(p["tg_id"], c["id"] if c else None, m.group(0) if m else raw)
        return {"ok": True, "stars_added": stars, "text": text,
                "stars": (await db.child(c["id"]))["stars"] if c else 0}

    @app.get("/api/store")
    async def store(request: Request):
        p, _, _ = await child_ctx(request)
        if not p:
            return err("auth", 401)
        return {"ok": True, **await db.store_info(), "checkin_stars": int(await db.setting("checkin_stars")),
                "checkin_days": int(await db.setting("checkin_days"))}

    # ---------- savollar ----------
    @app.get("/api/quiz")
    async def quiz(request: Request, id: int = 0):
        p, c, _ = await child_ctx(request)
        if not p or not c:
            return err("auth", 401)
        it = await db.get_content(id)
        if not it:
            return err("Topilmadi", 404)
        rows = await db.quiz_for(it)
        done = {r["quiz_id"]: r["ok"] for r in await db.all(
            "SELECT quiz_id, ok FROM quiz_done WHERE child_id=?", c["id"])}
        return {"ok": True, "items": [{"id": q["id"], "q": q["q"], "opts": [x for x in (
            ("a", q["a"]), ("b", q["b"]), ("c", q["c"])) if x[1]], "done": q["id"] in done} for q in rows],
            "stars": int(await db.setting("quiz_stars"))}

    @app.post("/api/quiz/answer")
    async def quiz_answer(request: Request):
        p, c, _ = await child_ctx(request)
        if not p or not c:
            return err("auth", 401)
        d = await body(request)
        r = await db.answer_quiz(c["id"], int(d.get("id", 0) or 0), str(d.get("choice", ""))[:1])
        if r is None:
            return err("Topilmadi", 404)
        return {"ok": True, **r, "total": (await db.child(c["id"]))["stars"]}
