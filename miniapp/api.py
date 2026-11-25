"""Kiddy TV Telegram Mini App: sahifa va API (bot bilan bitta baza).
Har bir so'rov Telegram initData imzosi bilan tekshiriladi."""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time as _time
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.types import FSInputFile
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

import config
from db import DB, age_of, hash_pin, now, parse_birth

HERE = os.path.dirname(__file__)
INIT_MAX_AGE = 24 * 3600
YT_ID = re.compile(r"(?:youtu\.be/|v=|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})")
PIN_RE = re.compile(r"^\d{4}$")
PARENT_TTL = 10 * 60
GAME_IDS = {"colors", "pairs", "count", "coloring", "letters", "shapes", "bigsmall", "oddone", "simon", "math",
            "pairs8"}


def check_init_data(init_data: str, token: str) -> dict | None:
    """Telegram WebApp initData imzosini tekshiradi. To'g'ri bo'lsa user dict, aks holda None."""
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received = pairs.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    if _time.time() - int(pairs.get("auth_date", "0")) > INIT_MAX_AGE:
        return None
    try:
        user = json.loads(pairs.get("user", "{}"))
    except ValueError:
        return None
    return user if user.get("id") else None


def youtube_id(url: str) -> str | None:
    m = YT_ID.search(url or "")
    return m.group(1) if m else None


def create_miniapp(db: DB, bot: Bot | None, token: str) -> FastAPI:
    app = FastAPI(title="Kiddy TV", docs_url=None, redoc_url=None, openapi_url=None)
    parent_sessions: dict[str, tuple[int, float]] = {}  # kalit -> (tg_id, tugash vaqti)
    pin_fails: dict[int, list[float]] = {}
    file_cache: dict[str, tuple[str, float]] = {}

    def err(msg, code=400):
        return JSONResponse({"ok": False, "error": msg}, status_code=code)

    async def auth(request: Request):
        init = request.headers.get("X-Init-Data") or request.query_params.get("init") or ""
        user = check_init_data(init, token)
        if not user:
            return None, None
        name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)
        parent = await db.ensure_parent(int(user["id"]), name or "")
        return user, parent

    async def body(request: Request) -> dict:
        try:
            d = await request.json()
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def parent_ok(request: Request, uid: int) -> bool:
        key = request.headers.get("X-Parent-Key", "")
        s = parent_sessions.get(key)
        if s and s[0] == uid and s[1] > _time.time():
            parent_sessions[key] = (uid, _time.time() + PARENT_TTL)
            return True
        return False

    def child_out(c):
        return {"id": c["id"], "name": c["name"], "age": age_of(c["birth_date"], now().date()),
                "stars": c["stars"], "birth": c["birth_date"]}

    def item_out(it):
        yt = youtube_id(it["source"]) if it["source_type"] == "youtube" else None
        return {"id": it["id"], "kind": it["kind"], "title": it["title"], "minutes": it["minutes"],
                "age_min": it["age_min"], "age_max": it["age_max"],
                "thumb": f"https://i.ytimg.com/vi/{yt}/hqdefault.jpg" if yt else None,
                "type": it["source_type"], "file_type": it["file_type"],
                "series": it["series"], "episode": it["episode"]}

    # ---------- sahifa ----------
    @app.get("/")
    @app.get("/app")
    async def index():
        return FileResponse(os.path.join(HERE, "static", "index.html"),
                            headers={"Cache-Control": "no-cache"})

    @app.get("/logo.png")
    async def logo():
        return FileResponse(os.path.join(os.path.dirname(HERE), "assets", "logo.png"),
                            headers={"Cache-Control": "max-age=86400"})

    # ---------- profil ----------
    @app.get("/api/me")
    async def me(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        kids = await db.children(p["tg_id"])
        active = await db.active_child(p["tg_id"])
        st = await db.settings()
        today = await db.minutes_today(active["id"]) if active else 0
        ok, reason = await db.time_check(p, active) if active else (True, "")
        return {"ok": True, "user": {"id": user["id"], "name": user.get("first_name", "")},
                "children": [child_out(c) for c in kids],
                "active": child_out(active) if active else None,
                "limit": p["daily_limit"], "used": today, "blocked_reason": "" if ok else reason,
                "sleep": {"on": bool(p["sleep_on"]), "from": p["sleep_from"], "to": p["sleep_to"]},
                "report": bool(p["report_on"]), "has_pin": bool(p["pin_hash"]),
                "tiers": [{"percent": a, "cost": b} for a, b in await db.tiers()],
                "coupon_days": int(st["coupon_days"]), "contest_title": st["contest_title"],
                "kinds": config.KINDS}

    @app.post("/api/child")
    async def add_child(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        name = str(d.get("name", "")).strip()
        birth = parse_birth(str(d.get("birth", "")))
        if not (1 <= len(name) <= 40) or not birth:
            return err("Ism va tug'ilgan sanani to'g'ri kiriting (masalan 25.03.2020).")
        if len(await db.children(p["tg_id"])) >= 8:
            return err("Ko'pi bilan 8 ta bola.")
        cid = await db.add_child(p["tg_id"], name, birth)
        return {"ok": True, "child": child_out(await db.child(cid))}

    @app.post("/api/child/active")
    async def set_active(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        c = await db.child(int(d.get("id", 0) or 0))
        if not c or c["parent_id"] != p["tg_id"]:
            return err("Topilmadi", 404)
        await db.set_parent(p["tg_id"], active_child=c["id"])
        return {"ok": True}

    # ---------- kontent ----------
    @app.get("/api/content")
    async def content(request: Request, kind: str = "cartoon", offset: int = 0):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        if kind not in config.KINDS:
            return err("kind")
        c = await db.active_child(p["tg_id"])
        if not c:
            return {"ok": True, "items": [], "more": False}
        age = age_of(c["birth_date"], now().date())
        out = []
        for typ, r in await db.list_grouped(kind, age, p["tg_id"]):
            if typ == "item":
                out.append({"t": "item", **item_out(r)})
            else:
                yt = youtube_id(r["first_source"] or "")
                out.append({"t": "series", "series": r["series"], "count": r["cnt"], "minutes": r["total"],
                            "thumb": f"https://i.ytimg.com/vi/{yt}/hqdefault.jpg" if yt else None})
        return {"ok": True, "items": out, "more": False}

    @app.get("/api/series")
    async def series(request: Request, name: str = ""):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        c = await db.active_child(p["tg_id"])
        if not c or not name:
            return {"ok": True, "items": []}
        age = age_of(c["birth_date"], now().date())
        rows = await db.series_items(name, age, p["tg_id"])
        return {"ok": True, "items": [item_out(r) for r in rows]}

    @app.post("/api/open")
    async def open_item(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        it = await db.get_content(int(d.get("id", 0) or 0))
        c = await db.active_child(p["tg_id"])
        if not it or not it["active"] or not c:
            return err("Topilmadi", 404)
        age = age_of(c["birth_date"], now().date())
        if await db.age_filter(age) is not None and not (it["age_min"] <= age <= it["age_max"]):
            return err("Bu kontent boshqa yosh uchun.", 403)
        ok, reason = await db.check_access(p, c, it)
        if not ok:
            return err(reason, 403)
        if it["source_type"] == "link":  # tashqi o'yin/sayt — kuzatib bo'lmaydi, darhol beriladi
            view_id, added = None, await db.record_view(c["id"], it)
        else:
            view_id, added = await db.start_view(c["id"], it), 0
        out = {"ok": True, "stars_added": added, "view_id": view_id, "reward": int(await db.setting("stars_per_view")),
               "stars": (await db.child(c["id"]))["stars"], "item": item_out(it)}
        if it["source_type"] == "youtube":
            out["youtube"] = youtube_id(it["source"])
            out["url"] = it["source"]
        elif it["source_type"] == "link":
            out["url"] = it["source"]
        else:
            out["media"] = f"/api/media/{it['id']}"
        nxt = await db.next_episode(it, age=age, parent_id=p["tg_id"])
        out["next"] = {"id": nxt["id"], "title": nxt["title"]} if nxt else None
        if it["series"]:
            out["series"] = {"name": it["series"], "episode": it["episode"]}
        out["pos"] = await db.last_pos(c["id"], it["id"]) if view_id else 0
        out["quiz"] = len(await db.quiz_for(it))
        liked = await db.one("SELECT 1 FROM likes WHERE child_id=? AND content_id=?", c["id"], it["id"])
        out["liked"] = bool(liked)
        return out

    @app.get("/api/media/{cid}")
    async def media(request: Request, cid: int):
        """Telegram'dagi video/audio faylni Mini App'ga uzatadi (token tashqariga chiqmaydi)."""
        user, p = await auth(request)
        if not user or not bot:
            return Response(status_code=401)
        it = await db.get_content(cid)
        if not it or it["source_type"] != "file":
            return Response(status_code=404)
        try:
            path, exp = file_cache.get(it["source"], ("", 0))
            if exp < _time.time():
                f = await bot.get_file(it["source"])
                path = f.file_path
                file_cache[it["source"]] = (path, _time.time() + 3000)
            stream = await bot.session.stream_content(
                f"{bot.session.api.file_url(bot.token, path)}", chunk_size=256 * 1024)
            ctype = "audio/mpeg" if it["file_type"] == "audio" else "video/mp4"
            return StreamingResponse(stream, media_type=ctype)
        except Exception as e:
            logging.warning("Media yuborilmadi: %s", e)
            return Response("Fayl 20 MB dan katta bo'lsa Telegram uni bermaydi", status_code=502)

    @app.post("/api/progress")
    async def progress(request: Request):
        """Pleyer: kontentning yarmi ko'rilganda yulduz."""
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        c = await db.active_child(p["tg_id"])
        if not c:
            return err("Topilmadi", 404)
        try:
            vid, played, dur = int(d.get("view_id", 0)), float(d.get("played", 0)), float(d.get("duration", 0) or 0)
        except (TypeError, ValueError):
            return err("Xato so'rov")
        stars, why = await db.finish_half(vid, c["id"], played, dur)
        return {"ok": True, "stars_added": stars, "reason": why, "stars": (await db.child(c["id"]))["stars"]}

    @app.post("/api/clientlog")
    async def clientlog(request: Request):
        try:
            d = await request.json()
            logging.warning("MINIAPP %s: %s | v=%s | %s", str(d.get("k"))[:10], str(d.get("m"))[:500],
                            str(d.get("v"))[:10], str(d.get("ua"))[:160])
        except Exception:
            pass
        return {"ok": True}

    @app.post("/api/like")
    async def like(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        c = await db.active_child(p["tg_id"])
        it = await db.get_content(int(d.get("id", 0) or 0))
        if not c or not it:
            return err("Topilmadi", 404)
        return {"ok": True, "liked": await db.toggle_like(c["id"], it["id"])}

    # ---------- o'yinlar ----------
    @app.post("/api/game/start")
    async def game_start(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        c = await db.active_child(p["tg_id"])
        if not c:
            return err("Avval bola qo'shing")
        ok, reason = await db.time_check(p, c)
        return {"ok": ok, "error": reason}

    @app.post("/api/game/done")
    async def game_done(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        game = str(d.get("game", ""))
        if game not in GAME_IDS:
            return err("game")
        c = await db.active_child(p["tg_id"])
        if not c:
            return err("Avval bola qo'shing")
        ok, reason = await db.time_check(p, c)
        if not ok:
            return err(reason, 403)
        stars = await db.record_game(c["id"], game)
        return {"ok": True, "stars_added": stars, "stars": (await db.child(c["id"]))["stars"]}

    # ---------- yulduz va kupon ----------
    @app.post("/api/redeem")
    async def redeem(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        c = await db.active_child(p["tg_id"])
        try:
            pct, cost = int(d.get("percent")), int(d.get("cost"))
        except (TypeError, ValueError):
            return err("Noto'g'ri")
        code = await db.redeem_stars(p["tg_id"], c["id"], pct, cost) if c else None
        if not code:
            return err(f"Yulduz yetmaydi: {cost} ta kerak.")
        return {"ok": True, "code": code, "percent": pct, "stars": (await db.child(c["id"]))["stars"]}

    @app.get("/api/coupons")
    async def coupons(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        rows = await db.parent_coupons(p["tg_id"])
        return {"ok": True, "coupons": [{"code": r["code"], "percent": r["percent"],
                                         "until": r["expires_at"][:10], "reason": r["reason"]} for r in rows]}

    # ---------- tanlov (bo'yash rasmi) ----------
    @app.post("/api/contest")
    async def contest(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        if not bot:
            return err("Bot ulanmagan")
        d = await body(request)
        data = str(d.get("png", ""))
        if not data.startswith("data:image/png;base64,") or len(data) > 4_000_000:
            return err("Rasm noto'g'ri")
        c = await db.active_child(p["tg_id"])
        raw = base64.b64decode(data.split(",", 1)[1])
        storage = int(os.getenv("STORAGE_CHAT_ID") or next(iter(config.ADMIN_IDS), 0) or p["tg_id"])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(raw)
        try:
            age = age_of(c["birth_date"], now().date()) if c else ""
            m = await bot.send_photo(storage, FSInputFile(tmp.name),
                                     caption=f"Tanlov: {c['name'] if c else ''}, {age} yosh (Mini App)")
            fid = m.photo[-1].file_id
        except Exception as e:
            return err(f"Yuborilmadi: {e}")
        finally:
            os.unlink(tmp.name)
        await db.run("INSERT INTO contest (parent_id, child_id, file_id, created_at) VALUES (?,?,?,?)",
                     p["tg_id"], c["id"] if c else None, fid, now().strftime("%Y-%m-%d %H:%M:%S"))
        return {"ok": True}

    # ---------- ota-ona ----------
    @app.post("/api/parent/unlock")
    async def unlock(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        d = await body(request)
        pin = str(d.get("pin", ""))
        uid = p["tg_id"]
        recent = [t for t in pin_fails.get(uid, []) if t > _time.time() - 300]
        pin_fails[uid] = recent
        if len(recent) >= 5:
            return err("Juda ko'p urinish. 5 daqiqadan keyin.", 429)
        if not PIN_RE.match(pin):
            return err("PIN 4 ta raqam")
        if not p["pin_hash"]:
            await db.set_parent(uid, pin_hash=hash_pin(pin))  # birinchi marta — PIN o'rnatiladi
        elif hash_pin(pin) != p["pin_hash"]:
            pin_fails[uid].append(_time.time())
            return err("PIN noto'g'ri", 403)
        key = secrets.token_urlsafe(24)
        parent_sessions[key] = (uid, _time.time() + PARENT_TTL)
        return {"ok": True, "key": key}

    @app.get("/api/parent")
    async def parent_info(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        if not parent_ok(request, p["tg_id"]):
            return err("pin", 403)
        kids = []
        for c in await db.children(p["tg_id"]):
            w = await db.week_stats(c["id"])
            kids.append({**child_out(c), "today": await db.minutes_today(c["id"]), "week": w})
        blocked = [{"id": b["id"], "title": b["title"]} for b in await db.blocked_list(p["tg_id"])]
        return {"ok": True, "limit": p["daily_limit"], "report": bool(p["report_on"]),
                "sleep": {"on": bool(p["sleep_on"]), "from": p["sleep_from"], "to": p["sleep_to"]},
                "kids": kids, "blocked": blocked}

    @app.post("/api/parent")
    async def parent_save(request: Request):
        user, p = await auth(request)
        if not user:
            return err("auth", 401)
        if not parent_ok(request, p["tg_id"]):
            return err("pin", 403)
        d = await body(request)
        f = {}
        if "limit" in d:
            f["daily_limit"] = max(15, min(240, int(d["limit"])))
        if "report" in d:
            f["report_on"] = 1 if d["report"] else 0
        if "sleep_on" in d:
            f["sleep_on"] = 1 if d["sleep_on"] else 0
        for k in ("sleep_from", "sleep_to"):
            if k in d:
                v = str(d[k])
                if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
                    return err("Vaqt HH:MM bo'lsin")
                f[k] = v
        if "pin" in d:
            if not PIN_RE.match(str(d["pin"])):
                return err("PIN 4 ta raqam")
            f["pin_hash"] = hash_pin(str(d["pin"]))
        if f:
            await db.set_parent(p["tg_id"], **f)
        if "unblock" in d:
            await db.run("DELETE FROM blocked WHERE parent_id=? AND content_id=?", p["tg_id"], int(d["unblock"]))
        if "block" in d:
            await db.run("INSERT OR IGNORE INTO blocked VALUES (?,?)", p["tg_id"], int(d["block"]))
        if "delete_child" in d:
            await db.delete_child(p["tg_id"], int(d["delete_child"]))
        return {"ok": True}

    from miniapp.extra import register as _reg_extra
    _reg_extra(app, db, bot, auth, err, body, item_out, youtube_id)

    return app
