"""SQLite ma'lumotlar bazasi va asosiy mantiq (bot handlerlaridan mustaqil, test qilish oson)."""
import hashlib
import os
import re
import secrets
from datetime import date, datetime, time, timedelta

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS parents (
    tg_id INTEGER PRIMARY KEY,
    full_name TEXT,
    pin_hash TEXT,
    daily_limit INTEGER DEFAULT 60,
    sleep_on INTEGER DEFAULT 1,
    sleep_from TEXT DEFAULT '21:00',
    sleep_to TEXT DEFAULT '07:00',
    report_on INTEGER DEFAULT 1,
    active_child INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    stars INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- cartoon / film / video / audio / game
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,       -- youtube / file / link
    source TEXT NOT NULL,            -- havola yoki telegram file_id
    file_type TEXT,                  -- video / audio / document (faqat file uchun)
    age_min INTEGER DEFAULT 0,
    age_max INTEGER DEFAULT 12,
    minutes INTEGER DEFAULT 5,
    active INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    minutes INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocked (
    parent_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    PRIMARY KEY (parent_id, content_id)
);
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    parent_id INTEGER NOT NULL,
    child_id INTEGER,
    percent INTEGER NOT NULL,
    stars_cost INTEGER DEFAULT 0,
    reason TEXT,                     -- stars / birthday / contest
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by INTEGER
);
CREATE TABLE IF NOT EXISTS contest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL,
    child_id INTEGER,
    file_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    winner INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS birthday_sent (
    child_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    PRIMARY KEY (child_id, year)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'kassir',   -- admin / kassir
    active INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS likes (
    child_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    created_at TEXT,
    PRIMARY KEY (child_id, content_id)
);
CREATE TABLE IF NOT EXISTS game_plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS child_days (
    child_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (child_id, day)
);
CREATE TABLE IF NOT EXISTS streak_awards (
    child_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    days INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    PRIMARY KEY (child_id, day)
);
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT,
    stars INTEGER NOT NULL,
    image TEXT,                      -- telegram file_id yoki https havola
    stock INTEGER,                   -- NULL = cheklanmagan
    active INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS gift_orders (
    code TEXT PRIMARY KEY,
    gift_id INTEGER NOT NULL,
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    issued_at TEXT,
    issued_by TEXT
);
CREATE TABLE IF NOT EXISTS banners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    text TEXT,
    image TEXT,
    link TEXT,
    active INTEGER DEFAULT 1,
    sort INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS quiz (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER,
    series TEXT,                     -- butun serial uchun savol bo'lsa
    q TEXT NOT NULL,
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    c TEXT,
    correct TEXT NOT NULL            -- 'a' / 'b' / 'c'
);
CREATE TABLE IF NOT EXISTS quiz_done (
    child_id INTEGER NOT NULL,
    quiz_id INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at TEXT,
    PRIMARY KEY (child_id, quiz_id)
);
CREATE TABLE IF NOT EXISTS notified (
    parent_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    PRIMARY KEY (parent_id, content_id)
);
CREATE TABLE IF NOT EXISTS report_sent (
    parent_id INTEGER NOT NULL,
    week TEXT NOT NULL,
    PRIMARY KEY (parent_id, week)
);
"""


def now() -> datetime:
    return datetime.now(config.TZ).replace(tzinfo=None)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    salt, _, _h = stored.partition("$")
    return secrets.compare_digest(hash_password(pw, salt), stored)


DEFAULT_SETTINGS = {
    "stars_per_view": str(config.STARS_PER_VIEW),
    "reward_tiers": ",".join(f"{p}:{c}" for p, c in config.REWARD_TIERS),
    "birthday_percent": str(config.BIRTHDAY_PERCENT),
    "coupon_days": str(config.COUPON_DAYS),
    "default_daily_limit": "60",
    "contest_title": "Mening sevimli o'yinchog'im",
    "contest_percent": "20",
    "webapp_url": "",
    "age_limit": "1",
    "streak_bonus": "3:5,7:15,14:25,30:50",   # ketma-ket kun:yulduz
    "quiz_stars": "2",
    "gift_days": "30",
    "notify_new": "1",
    "ref_bonus": "20",        # do'stini taklif qilganga
    "ref_new_bonus": "10",    # taklif bilan kelgan yangi bolaga
    "quiz_drafts": "",  # 1 = yosh chegarasi yoqilgan, 0 = hamma kontent hammaga ochiq
}


def parse_tiers(text: str) -> list[tuple[int, int]]:
    """'5:100,10:200' -> [(5,100),(10,200)]"""
    out = []
    for part in text.split(","):
        if ":" in part:
            p, c = part.split(":", 1)
            if p.strip().isdigit() and c.strip().isdigit():
                out.append((int(p), int(c)))
    return sorted(out, key=lambda x: x[1])


def hash_pin(pin: str) -> str:
    return hashlib.sha256(("kiddy-tv:" + pin).encode()).hexdigest()


def age_of(birth: str, today: date) -> int:
    b = date.fromisoformat(birth)
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def parse_birth(text: str) -> str | None:
    """'25.03.2020' yoki '2020-03-25' -> '2020-03-25'. Xato bo'lsa None."""
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if d > now().date() or now().date().year - d.year > 14:
            return None
        return d.isoformat()
    return None


def is_sleep_time(t: time, start: str, end: str) -> bool:
    s = time.fromisoformat(start)
    e = time.fromisoformat(end)
    if s == e:
        return False
    if s < e:
        return s <= t < e
    return t >= s or t < e  # yarim tundan o'tadigan oraliq (21:00–07:00)


class DB:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        # eski bazalar uchun yangi ustunlar
        for sql in ["ALTER TABLE contest ADD COLUMN winner INTEGER DEFAULT 0",
                    "ALTER TABLE content ADD COLUMN series TEXT",
                    "ALTER TABLE content ADD COLUMN episode INTEGER",
                    "ALTER TABLE views ADD COLUMN pos INTEGER DEFAULT 0",
                    "ALTER TABLE children ADD COLUMN total_stars INTEGER",
                    "ALTER TABLE quiz ADD COLUMN approved INTEGER DEFAULT 1",
                    "ALTER TABLE parents ADD COLUMN referred_by INTEGER",
                    "ALTER TABLE parents ADD COLUMN ref_awarded INTEGER DEFAULT 0"]:
            try:
                await self.conn.execute(sql)
            except Exception:
                pass
        # umumiy (sarflanmagan + sarflangan) yulduz — daraja uchun
        await self.conn.execute(
            "UPDATE children SET total_stars = COALESCE((SELECT SUM(stars) FROM views v WHERE v.child_id=children.id),0)"
            " + COALESCE((SELECT SUM(stars) FROM game_plays g WHERE g.child_id=children.id),0) WHERE total_stars IS NULL")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def one(self, sql, *a):
        cur = await self.conn.execute(sql, a)
        return await cur.fetchone()

    async def all(self, sql, *a):
        cur = await self.conn.execute(sql, a)
        return await cur.fetchall()

    async def run(self, sql, *a):
        cur = await self.conn.execute(sql, a)
        await self.conn.commit()
        return cur.lastrowid

    # ---------- ota-ona va bolalar ----------
    async def get_parent(self, tg_id):
        return await self.one("SELECT * FROM parents WHERE tg_id=?", tg_id)

    async def ensure_parent(self, tg_id, full_name):
        if not await self.get_parent(tg_id):
            limit = int(await self.setting("default_daily_limit"))
            await self.run("INSERT INTO parents (tg_id, full_name, daily_limit, created_at) VALUES (?,?,?,?)",
                           tg_id, full_name, limit, iso(now()))
        return await self.get_parent(tg_id)

    async def set_parent(self, tg_id, **fields):
        keys = ", ".join(f"{k}=?" for k in fields)
        await self.run(f"UPDATE parents SET {keys} WHERE tg_id=?", *fields.values(), tg_id)

    async def add_child(self, parent_id, name, birth):
        cid = await self.run("INSERT INTO children (parent_id, name, birth_date, created_at) VALUES (?,?,?,?)",
                             parent_id, name.strip()[:40], birth, iso(now()))
        await self.set_parent(parent_id, active_child=cid)
        return cid

    async def children(self, parent_id):
        return await self.all("SELECT * FROM children WHERE parent_id=? ORDER BY id", parent_id)

    async def child(self, child_id):
        return await self.one("SELECT * FROM children WHERE id=?", child_id)

    async def active_child(self, parent_id):
        p = await self.get_parent(parent_id)
        if p and p["active_child"]:
            c = await self.child(p["active_child"])
            if c and c["parent_id"] == parent_id:
                return c
        kids = await self.children(parent_id)
        return kids[0] if kids else None

    async def delete_child(self, parent_id, child_id):
        await self.run("DELETE FROM children WHERE id=? AND parent_id=?", child_id, parent_id)
        p = await self.get_parent(parent_id)
        if p["active_child"] == child_id:
            kids = await self.children(parent_id)
            await self.set_parent(parent_id, active_child=kids[0]["id"] if kids else None)

    # ---------- kontent ----------
    async def add_content(self, kind, title, source_type, source, file_type=None,
                          age_min=0, age_max=12, minutes=5, series=None, episode=None):
        return await self.run(
            "INSERT INTO content (kind,title,source_type,source,file_type,age_min,age_max,minutes,created_at,"
            "series,episode) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            kind, title, source_type, source, file_type, age_min, age_max, minutes, iso(now()), series, episode)

    async def get_content(self, cid):
        return await self.one("SELECT * FROM content WHERE id=?", cid)

    async def list_content(self, kind, age=None, parent_id=None, offset=0, limit=6):
        sql = "SELECT * FROM content WHERE active=1 AND kind=?"
        args = [kind]
        age = await self.age_filter(age)
        if age is not None:
            sql += " AND age_min<=? AND age_max>=?"
            args += [age, age]
        if parent_id is not None:
            sql += " AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?)"
            args.append(parent_id)
        # seriallar bitta blok bo'lib, qismlari tartib bilan chiqadi
        sql += (" ORDER BY CASE WHEN series IS NULL THEN id ELSE (SELECT MAX(c2.id) FROM content c2 "
                "WHERE c2.series=content.series) END DESC, COALESCE(episode, 0) ASC, id DESC LIMIT ? OFFSET ?")
        args += [limit + 1, offset]  # +1: keyingi sahifa bormi
        rows = await self.all(sql, *args)
        return rows[:limit], len(rows) > limit

    async def deactivate_content(self, cid):
        await self.run("UPDATE content SET active=0 WHERE id=?", cid)

    async def toggle_block(self, parent_id, cid) -> bool:
        if await self.one("SELECT 1 FROM blocked WHERE parent_id=? AND content_id=?", parent_id, cid):
            await self.run("DELETE FROM blocked WHERE parent_id=? AND content_id=?", parent_id, cid)
            return False
        await self.run("INSERT INTO blocked VALUES (?,?)", parent_id, cid)
        return True

    async def blocked_list(self, parent_id):
        return await self.all("SELECT c.* FROM blocked b JOIN content c ON c.id=b.content_id "
                              "WHERE b.parent_id=? ORDER BY c.title", parent_id)

    # ---------- ko'rish, vaqt chegarasi, yulduz ----------
    async def minutes_today(self, child_id, at: datetime | None = None):
        at = at or now()
        start = iso(datetime.combine(at.date(), time()))
        r = await self.one("SELECT (SELECT COALESCE(SUM(minutes),0) FROM views WHERE child_id=? AND created_at>=?) + "
                           "(SELECT COALESCE(SUM(minutes),0) FROM game_plays WHERE child_id=? AND created_at>=?) m",
                           child_id, start, child_id, start)
        return r["m"]

    async def check_access(self, parent, child, item, at: datetime | None = None):
        """Ruxsat bormi? -> (True, '') yoki (False, sabab)."""
        at = at or now()
        if await self.one("SELECT 1 FROM blocked WHERE parent_id=? AND content_id=?", parent["tg_id"], item["id"]):
            return False, "Bu kontent ota-ona tomonidan yopilgan."
        if parent["sleep_on"] and is_sleep_time(at.time(), parent["sleep_from"], parent["sleep_to"]):
            return False, (f"Hozir uxlash vaqti ({parent['sleep_from']}–{parent['sleep_to']}). "
                           "Ertaga yana ko'ramiz! Yaxshi tush ko'ring.")
        used = await self.minutes_today(child["id"], at)
        if parent["daily_limit"] and used >= parent["daily_limit"]:
            return False, "Bugungi ko'rish vaqti tugadi. Biroz dam olamiz, ertaga davom etamiz!"
        return True, ""

    async def record_view(self, child_id, item, at: datetime | None = None):
        stars = int(await self.setting("stars_per_view"))
        await self.run("INSERT INTO views (child_id, content_id, minutes, stars, created_at) VALUES (?,?,?,?,?)",
                       child_id, item["id"], item["minutes"] or 1, stars, iso(at or now()))
        await self.run("UPDATE children SET stars=stars+?, total_stars=COALESCE(total_stars,0)+? WHERE id=?", stars, stars, child_id)
        return stars

    async def start_view(self, child_id, item, at: datetime | None = None) -> int:
        """Ko'rish boshlandi: yulduz hali berilmaydi (yarmi ko'rilganda beriladi). view id qaytaradi."""
        return await self.run("INSERT INTO views (child_id, content_id, minutes, stars, created_at) VALUES (?,?,?,0,?)",
                              child_id, item["id"], item["minutes"] or 1, iso(at or now()))

    async def finish_half(self, view_id, child_id, played_sec: float, duration_sec: float,
                          at: datetime | None = None):
        """Kontentning yarmi ko'rilgan bo'lsa yulduz beradi. -> (berilgan yulduz, sabab)."""
        v = await self.one("SELECT * FROM views WHERE id=? AND child_id=?", view_id, child_id)
        if not v:
            return 0, "topilmadi"
        if v["stars"]:
            return 0, "allaqachon"
        item = await self.get_content(v["content_id"])
        dur = float(duration_sec or 0)
        if not (20 <= dur <= 4 * 3600):  # pleyer bermasa — kontent daqiqasi
            dur = (item["minutes"] or 1) * 60 if item else 60
        need = dur / 2
        elapsed = ((at or now()) - datetime.fromisoformat(v["created_at"])).total_seconds()
        if played_sec < need or elapsed < need * 0.9:  # haqiqatan ham shuncha vaqt o'tgan bo'lsin
            return 0, "erta"
        stars = int(await self.setting("stars_per_view"))
        await self.run("UPDATE views SET stars=? WHERE id=? AND stars=0", stars, view_id)
        await self.run("UPDATE children SET stars=stars+?, total_stars=COALESCE(total_stars,0)+? WHERE id=?", stars, stars, child_id)
        return stars, ""

    # ---------- kuponlar ----------
    async def make_coupon(self, parent_id, child_id, percent, stars_cost=0, reason="stars"):
        while True:
            code = "KIDDY-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
            if not await self.one("SELECT 1 FROM coupons WHERE code=?", code):
                break
        n = now()
        days = int(await self.setting("coupon_days"))
        await self.run("INSERT INTO coupons (code,parent_id,child_id,percent,stars_cost,reason,created_at,expires_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", code, parent_id, child_id, percent, stars_cost, reason,
                       iso(n), iso(n + timedelta(days=days)))
        return code

    async def redeem_stars(self, parent_id, child_id, percent, cost):
        """Yulduzni chegirmaga almashtirish. Yetmasa yoki tarif yo'q bo'lsa None."""
        if (percent, cost) not in await self.tiers():
            return None
        c = await self.child(child_id)
        if not c or c["parent_id"] != parent_id or c["stars"] < cost:
            return None
        await self.run("UPDATE children SET stars=stars-? WHERE id=? AND stars>=?", cost, child_id, cost)
        return await self.make_coupon(parent_id, child_id, percent, cost, "stars")

    async def use_coupon(self, code, cashier):
        """Kassir kuponni tekshiradi va ishlatadi. cashier: kim ishlatgani (matn). -> (holat, kupon)"""
        code = code.strip().upper()
        c = await self.one("SELECT * FROM coupons WHERE code=?", code)
        if not c:
            return "not_found", None
        if c["used_at"]:
            return "used", c
        if c["expires_at"] < iso(now()):
            return "expired", c
        await self.run("UPDATE coupons SET used_at=?, used_by=? WHERE code=?", iso(now()), str(cashier), code)
        return "ok", c

    async def parent_coupons(self, parent_id):
        return await self.all("SELECT * FROM coupons WHERE parent_id=? AND used_at IS NULL AND expires_at>=? "
                              "ORDER BY created_at DESC", parent_id, iso(now()))

    # ---------- hisobot ----------
    async def week_stats(self, child_id, end: datetime | None = None):
        end = end or now()
        start = iso(end - timedelta(days=7))
        r = await self.one(
            "SELECT COALESCE(SUM(v.minutes),0) m, COUNT(v.id) n, COALESCE(SUM(v.stars),0) s, "
            "SUM(CASE WHEN c.kind='game' THEN 1 ELSE 0 END) g "
            "FROM views v JOIN content c ON c.id=v.content_id WHERE v.child_id=? AND v.created_at>=?",
            child_id, start)
        top = await self.one(
            "SELECT c.title, COUNT(*) k FROM views v JOIN content c ON c.id=v.content_id "
            "WHERE v.child_id=? AND v.created_at>=? GROUP BY c.id ORDER BY k DESC LIMIT 1", child_id, start)
        return {"minutes": r["m"], "count": r["n"], "stars": r["s"], "games": r["g"] or 0,
                "top": top["title"] if top else None}

    async def stats_overview(self):
        r = {}
        for key, sql in [("parents", "SELECT COUNT(*) FROM parents"),
                         ("children", "SELECT COUNT(*) FROM children"),
                         ("content", "SELECT COUNT(*) FROM content WHERE active=1"),
                         ("views_today", "SELECT COUNT(*) FROM views WHERE created_at>=?"),
                         ("coupons_used", "SELECT COUNT(*) FROM coupons WHERE used_at IS NOT NULL")]:
            args = (iso(datetime.combine(now().date(), time())),) if "?" in sql else ()
            row = await self.one(sql, *args)
            r[key] = row[0]
        return r

    async def age_filter(self, age):
        """Yosh chegarasi o'chirilgan bo'lsa None qaytaradi (filtrsiz)."""
        if age is None or await self.setting("age_limit") == "0":
            return None
        return age

    # ================= admin panel uchun =================
    async def setting(self, key):
        r = await self.one("SELECT value FROM settings WHERE key=?", key)
        return r["value"] if r else DEFAULT_SETTINGS[key]

    async def settings(self):
        d = dict(DEFAULT_SETTINGS)
        for r in await self.all("SELECT key, value FROM settings"):
            d[r["key"]] = r["value"]
        return d

    async def set_setting(self, key, value):
        await self.run("INSERT INTO settings (key, value) VALUES (?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, str(value))

    async def tiers(self):
        return parse_tiers(await self.setting("reward_tiers"))

    # --- xodimlar ---
    async def staff_count(self):
        return (await self.one("SELECT COUNT(*) c FROM staff"))["c"]

    async def add_staff(self, username, password, role="kassir", full_name=""):
        return await self.run("INSERT INTO staff (username, full_name, pw_hash, role, created_at) VALUES (?,?,?,?,?)",
                              username.strip().lower(), full_name.strip(), hash_password(password), role, iso(now()))

    async def check_staff(self, username, password):
        r = await self.one("SELECT * FROM staff WHERE username=? AND active=1", username.strip().lower())
        return r if r and check_password(password, r["pw_hash"]) else None

    async def all_staff(self):
        return await self.all("SELECT * FROM staff ORDER BY role, username")

    # --- yoqdi ---
    async def toggle_like(self, child_id, content_id) -> bool:
        if await self.one("SELECT 1 FROM likes WHERE child_id=? AND content_id=?", child_id, content_id):
            await self.run("DELETE FROM likes WHERE child_id=? AND content_id=?", child_id, content_id)
            return False
        await self.run("INSERT INTO likes VALUES (?,?,?)", child_id, content_id, iso(now()))
        return True

    # --- kontent (statistika bilan) ---
    async def admin_content(self, kind=None, q=None, show_hidden=False):
        sql = ("SELECT c.*, (SELECT COUNT(*) FROM views v WHERE v.content_id=c.id) AS views, "
               "(SELECT COUNT(*) FROM likes l WHERE l.content_id=c.id) AS likes FROM content c WHERE 1=1")
        args = []
        if not show_hidden:
            sql += " AND c.active=1"
        if kind:
            sql += " AND c.kind=?"
            args.append(kind)
        if q:
            sql += " AND c.title LIKE ?"
            args.append(f"%{q}%")
        return await self.all(sql + " ORDER BY c.id DESC", *args)

    async def update_content(self, cid, **f):
        keys = ", ".join(f"{k}=?" for k in f)
        await self.run(f"UPDATE content SET {keys} WHERE id=?", *f.values(), cid)

    # --- kuponlar ---
    async def admin_coupons(self, status="all", q=None):
        sql = ("SELECT cp.*, ch.name AS child_name, p.full_name AS parent_name "
               "FROM coupons cp LEFT JOIN children ch ON ch.id=cp.child_id "
               "LEFT JOIN parents p ON p.tg_id=cp.parent_id WHERE 1=1")
        args = []
        n = iso(now())
        if status == "active":
            sql += " AND cp.used_at IS NULL AND cp.expires_at>=?"
            args.append(n)
        elif status == "used":
            sql += " AND cp.used_at IS NOT NULL"
        elif status == "expired":
            sql += " AND cp.used_at IS NULL AND cp.expires_at<?"
            args.append(n)
        if q:
            sql += " AND (cp.code LIKE ? OR ch.name LIKE ?)"
            args += [f"%{q.strip().upper()}%", f"%{q.strip()}%"]
        return await self.all(sql + " ORDER BY cp.created_at DESC LIMIT 500", *args)

    # --- reytinglar ---
    async def top_children(self, limit=20, days=None):
        if days:
            since = iso(now() - timedelta(days=days))
            return await self.all(
                "SELECT ch.*, COALESCE(SUM(v.stars),0) AS earned, COUNT(v.id) AS cnt FROM children ch "
                "JOIN views v ON v.child_id=ch.id AND v.created_at>=? GROUP BY ch.id "
                "ORDER BY earned DESC LIMIT ?", since, limit)
        return await self.all("SELECT ch.*, ch.stars AS earned, "
                              "(SELECT COUNT(*) FROM views v WHERE v.child_id=ch.id) AS cnt "
                              "FROM children ch ORDER BY ch.stars DESC LIMIT ?", limit)

    async def top_content(self, limit=20, days=None, order="views"):
        since = iso(now() - timedelta(days=days)) if days else "0"
        return await self.all(
            "SELECT c.*, (SELECT COUNT(*) FROM views v WHERE v.content_id=c.id AND v.created_at>=?) AS views, "
            "(SELECT COUNT(*) FROM likes l WHERE l.content_id=c.id) AS likes FROM content c WHERE c.active=1 "
            f"ORDER BY {'likes' if order == 'likes' else 'views'} DESC, c.id DESC LIMIT ?", since, limit)

    async def views_by_day(self, days=14):
        start = now().date() - timedelta(days=days - 1)
        rows = await self.all("SELECT substr(created_at,1,10) d, COUNT(*) n, COALESCE(SUM(minutes),0) m "
                              "FROM views WHERE created_at>=? GROUP BY d", iso(datetime.combine(start, time())))
        by = {r["d"]: r for r in rows}
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            out.append({"date": d, "views": by[d]["n"] if d in by else 0, "minutes": by[d]["m"] if d in by else 0})
        return out

    async def kind_split(self):
        return await self.all("SELECT c.kind, COUNT(v.id) n FROM views v JOIN content c ON c.id=v.content_id "
                              "GROUP BY c.kind ORDER BY n DESC")

    # --- oilalar ---
    async def families(self, q=None):
        sql = ("SELECT p.*, (SELECT COUNT(*) FROM children c WHERE c.parent_id=p.tg_id) AS kids, "
               "(SELECT group_concat(name, ', ') FROM children c WHERE c.parent_id=p.tg_id) AS kid_names "
               "FROM parents p")
        args = []
        if q:
            sql += " WHERE p.full_name LIKE ? OR p.tg_id IN (SELECT parent_id FROM children WHERE name LIKE ?)"
            args = [f"%{q}%", f"%{q}%"]
        return await self.all(sql + " ORDER BY p.created_at DESC LIMIT 500", *args)

    # --- tanlov ---
    async def contest_entries(self):
        return await self.all("SELECT t.*, ch.name AS child_name, ch.birth_date FROM contest t "
                              "LEFT JOIN children ch ON ch.id=t.child_id ORDER BY t.winner DESC, t.id DESC LIMIT 300")

    # --- Mini App o'yinlari ---
    async def time_check(self, parent, child, at: datetime | None = None):
        """Uxlash vaqti va kunlik limit (bloklashsiz). -> (True,'') yoki (False, sabab)"""
        at = at or now()
        if parent["sleep_on"] and is_sleep_time(at.time(), parent["sleep_from"], parent["sleep_to"]):
            return False, f"Hozir uxlash vaqti ({parent['sleep_from']}–{parent['sleep_to']}). Yaxshi tush ko'ring!"
        if parent["daily_limit"] and await self.minutes_today(child["id"], at) >= parent["daily_limit"]:
            return False, "Bugungi vaqt tugadi. Biroz dam olamiz, ertaga davom etamiz!"
        return True, ""

    async def record_game(self, child_id, game, minutes=2, max_per_day=10):
        start = iso(datetime.combine(now().date(), time()))
        n = (await self.one("SELECT COUNT(*) c FROM game_plays WHERE child_id=? AND created_at>=? AND stars>0",
                            child_id, start))["c"]
        stars = 3 if n < max_per_day else 0
        await self.run("INSERT INTO game_plays (child_id, game, minutes, stars, created_at) VALUES (?,?,?,?,?)",
                       child_id, game[:20], minutes, stars, iso(now()))
        if stars:
            await self.run("UPDATE children SET stars=stars+?, total_stars=COALESCE(total_stars,0)+? WHERE id=?", stars, stars, child_id)
        return stars

    # --- seriallar ---
    async def next_episode(self, item, age=None, parent_id=None):
        if not item["series"] or item["episode"] is None:
            return None
        sql = "SELECT * FROM content WHERE active=1 AND series=? AND episode>?"
        args = [item["series"], item["episode"]]
        age = await self.age_filter(age)
        if age is not None:
            sql += " AND age_min<=? AND age_max>=?"
            args += [age, age]
        if parent_id is not None:
            sql += " AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?)"
            args.append(parent_id)
        return await self.one(sql + " ORDER BY episode LIMIT 1", *args)

    async def existing_youtube_ids(self):
        ids = set()
        for r in await self.all("SELECT source FROM content WHERE source_type='youtube'"):
            m = re.search(r"(?:youtu\.be/|v=|/embed/|/shorts/)([A-Za-z0-9_-]{11})", r["source"])
            if m:
                ids.add(m.group(1))
        return ids

    # --- ilova uchun: seriallar papka bo'lib ---
    async def list_grouped(self, kind, age, parent_id, limit=80):
        age = await self.age_filter(age)
        if age is None:
            cond = "active=1 AND kind=? AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?)"
            args = [kind, parent_id]
        else:
            cond = ("active=1 AND kind=? AND age_min<=? AND age_max>=? "
                    "AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?)")
            args = [kind, age, age, parent_id]
        singles = await self.all(f"SELECT *, id AS sort_id FROM content WHERE {cond} AND series IS NULL "
                                 "ORDER BY id DESC LIMIT ?", *args, limit)
        series = await self.all(
            f"SELECT series, COUNT(*) AS cnt, MAX(id) AS sort_id, SUM(minutes) AS total, "
            f"(SELECT c2.source FROM content c2 WHERE c2.series=content.series AND c2.active=1 "
            f" ORDER BY c2.episode LIMIT 1) AS first_source FROM content WHERE {cond} AND series IS NOT NULL "
            "GROUP BY series ORDER BY sort_id DESC LIMIT ?", *args, limit)
        out = [("item", r) for r in singles] + [("series", r) for r in series]
        out.sort(key=lambda x: -x[1]["sort_id"])
        return out[:limit]

    async def series_items(self, series, age, parent_id):
        age = await self.age_filter(age)
        if age is None:
            return await self.all(
                "SELECT * FROM content WHERE active=1 AND series=? "
                "AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?) ORDER BY episode, id",
                series, parent_id)
        return await self.all(
            "SELECT * FROM content WHERE active=1 AND series=? AND age_min<=? AND age_max>=? "
            "AND id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?) ORDER BY episode, id",
            series, age, age, parent_id)

    # ================= qo'shimcha imkoniyatlar =================
    async def add_stars(self, child_id, n):
        if n:
            await self.run("UPDATE children SET stars=stars+?, total_stars=COALESCE(total_stars,0)+? WHERE id=?",
                           n, n, child_id)

    # --- davom ettirish, oxirgilar, sevimlilar, qidiruv ---
    async def save_pos(self, view_id, child_id, pos):
        await self.run("UPDATE views SET pos=? WHERE id=? AND child_id=?", int(max(0, pos)), view_id, child_id)

    async def last_pos(self, child_id, content_id):
        r = await self.one("SELECT pos FROM views WHERE child_id=? AND content_id=? AND pos>0 ORDER BY id DESC LIMIT 1",
                           child_id, content_id)
        return r["pos"] if r else 0

    def _vis(self, age):
        return ("" if age is None else " AND c.age_min<=? AND c.age_max>=?"), ([] if age is None else [age, age])

    async def recent(self, child_id, age, parent_id, limit=10):
        age = await self.age_filter(age)
        cond, a = self._vis(age)
        return await self.all(
            "SELECT c.*, MAX(v.id) AS last_view, (SELECT pos FROM views v2 WHERE v2.child_id=v.child_id AND "
            "v2.content_id=c.id ORDER BY v2.id DESC LIMIT 1) AS pos FROM views v JOIN content c ON c.id=v.content_id "
            f"WHERE v.child_id=? AND c.active=1 AND c.source_type!='link'{cond} "
            "AND c.id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?) "
            "GROUP BY c.id ORDER BY last_view DESC LIMIT ?", child_id, *a, parent_id, limit)

    async def continue_series(self, child_id, age, parent_id, limit=6):
        """Har bir boshlangan serial uchun keyingi ko'rilmagan qism."""
        out = []
        rows = await self.all(
            "SELECT c.series, MAX(v.id) AS last_view FROM views v JOIN content c ON c.id=v.content_id "
            "WHERE v.child_id=? AND c.series IS NOT NULL GROUP BY c.series ORDER BY last_view DESC LIMIT 12", child_id)
        for r in rows:
            last = await self.one("SELECT c.* FROM views v JOIN content c ON c.id=v.content_id WHERE v.child_id=? "
                                  "AND c.series=? ORDER BY v.id DESC LIMIT 1", child_id, r["series"])
            nxt = await self.next_episode(last, age=age, parent_id=parent_id) if last else None
            if nxt:
                out.append(nxt)
            if len(out) >= limit:
                break
        return out

    async def favorites(self, child_id, age, parent_id):
        age = await self.age_filter(age)
        cond, a = self._vis(age)
        return await self.all(
            f"SELECT c.* FROM likes l JOIN content c ON c.id=l.content_id WHERE l.child_id=? AND c.active=1{cond} "
            "AND c.id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?) ORDER BY l.created_at DESC",
            child_id, *a, parent_id)

    async def search(self, q, age, parent_id, limit=40):
        q = (q or "").strip()
        if len(q) < 2:
            return []
        age = await self.age_filter(age)
        cond, a = self._vis(age)
        like = f"%{q}%"
        return await self.all(
            f"SELECT c.* FROM content c WHERE c.active=1{cond} AND (c.title LIKE ? OR c.series LIKE ?) "
            "AND c.id NOT IN (SELECT content_id FROM blocked WHERE parent_id=?) "
            "ORDER BY CASE WHEN c.title LIKE ? THEN 0 ELSE 1 END, c.series, c.episode, c.id DESC LIMIT ?",
            *a, like, like, parent_id, f"{q}%", limit)

    # --- kunlik seriya ---
    async def touch_day(self, child_id, at: datetime | None = None):
        """Bola bugun kirdi. -> (ketma-ket kunlar, bugun berilgan bonus)"""
        d = (at or now()).date()
        await self.run("INSERT OR IGNORE INTO child_days (child_id, day) VALUES (?,?)", child_id, d.isoformat())
        streak = await self.streak(child_id, d)
        bonus = 0
        tiers = dict(parse_tiers(await self.setting("streak_bonus")))  # {kun: yulduz}
        if streak in tiers and not await self.one("SELECT 1 FROM streak_awards WHERE child_id=? AND day=?",
                                                  child_id, d.isoformat()):
            bonus = tiers[streak]
            await self.run("INSERT INTO streak_awards (child_id, day, days, stars) VALUES (?,?,?,?)",
                           child_id, d.isoformat(), streak, bonus)
            await self.add_stars(child_id, bonus)
        return streak, bonus

    async def streak(self, child_id, d: date | None = None):
        d = d or now().date()
        days = {r["day"] for r in await self.all(
            "SELECT day FROM child_days WHERE child_id=? AND day>=?", child_id, (d - timedelta(days=400)).isoformat())}
        n = 0
        while (d - timedelta(days=n)).isoformat() in days:
            n += 1
        return n

    async def best_streak(self, child_id):
        rows = [date.fromisoformat(r["day"]) for r in await self.all(
            "SELECT day FROM child_days WHERE child_id=? ORDER BY day", child_id)]
        best = cur = 0
        prev = None
        for d in rows:
            cur = cur + 1 if prev and (d - prev).days == 1 else 1
            best, prev = max(best, cur), d
        return best

    # --- daraja va nishonlar ---
    async def child_stats(self, child_id):
        kinds = {r["kind"]: r["n"] for r in await self.all(
            "SELECT c.kind, COUNT(DISTINCT c.id) n FROM views v JOIN content c ON c.id=v.content_id "
            "WHERE v.child_id=? AND v.stars>0 GROUP BY c.kind", child_id)}
        games = (await self.one("SELECT COUNT(*) n FROM game_plays WHERE child_id=?", child_id))["n"]
        quiz_ok = (await self.one("SELECT COUNT(*) n FROM quiz_done WHERE child_id=? AND ok=1", child_id))["n"]
        contest = (await self.one("SELECT COUNT(*) n FROM contest WHERE child_id=?", child_id))["n"]
        likes = (await self.one("SELECT COUNT(*) n FROM likes WHERE child_id=?", child_id))["n"]
        return {"kinds": kinds, "games": games, "quiz_ok": quiz_ok, "contest": contest, "likes": likes,
                "best_streak": await self.best_streak(child_id)}

    # --- sovg'alar ---
    async def gifts_list(self, only_active=True):
        return await self.all("SELECT * FROM gifts" + (" WHERE active=1 AND (stock IS NULL OR stock>0)" if only_active
                                                        else "") + " ORDER BY stars, id")

    async def add_gift(self, title, stars, note="", image=None, stock=None):
        return await self.run("INSERT INTO gifts (title, note, stars, image, stock, created_at) VALUES (?,?,?,?,?,?)",
                              title, note, stars, image, stock, iso(now()))

    async def redeem_gift(self, parent_id, child_id, gift_id):
        """-> (kod, xato)"""
        g = await self.one("SELECT * FROM gifts WHERE id=? AND active=1", gift_id)
        if not g or (g["stock"] is not None and g["stock"] <= 0):
            return None, "Bu sovg'a hozir yo'q."
        c = await self.child(child_id)
        if not c or c["parent_id"] != parent_id:
            return None, "Topilmadi"
        if c["stars"] < g["stars"]:
            return None, f"Yulduz yetmaydi: yana {g['stars'] - c['stars']} ta kerak."
        cur = await self.conn.execute("UPDATE children SET stars=stars-? WHERE id=? AND stars>=?",
                                      (g["stars"], child_id, g["stars"]))
        if cur.rowcount != 1:
            await self.conn.commit()
            return None, "Yulduz yetmaydi."
        if g["stock"] is not None:
            await self.conn.execute("UPDATE gifts SET stock=stock-1 WHERE id=?", (gift_id,))
        await self.conn.commit()
        while True:
            code = "SOVGA-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))
            if not await self.one("SELECT 1 FROM gift_orders WHERE code=?", code):
                break
        n = now()
        days = int(await self.setting("gift_days"))
        await self.run("INSERT INTO gift_orders (code, gift_id, parent_id, child_id, stars, created_at, expires_at) "
                       "VALUES (?,?,?,?,?,?,?)", code, gift_id, parent_id, child_id, g["stars"], iso(n),
                       iso(n + timedelta(days=days)))
        return code, ""

    async def gift_orders(self, parent_id=None, child_id=None, limit=100):
        sql = ("SELECT o.*, g.title, ch.name AS child_name, p.full_name AS parent_name FROM gift_orders o "
               "JOIN gifts g ON g.id=o.gift_id LEFT JOIN children ch ON ch.id=o.child_id "
               "LEFT JOIN parents p ON p.tg_id=o.parent_id WHERE 1=1")
        a = []
        if parent_id:
            sql += " AND o.parent_id=?"; a.append(parent_id)
        if child_id:
            sql += " AND o.child_id=?"; a.append(child_id)
        return await self.all(sql + " ORDER BY o.created_at DESC LIMIT ?", *a, limit)

    async def issue_gift(self, code, cashier):
        """Kassir sovg'ani beradi. -> (holat, buyurtma) holat: ok/used/expired/none"""
        code = code.strip().upper()
        o = await self.one("SELECT o.*, g.title FROM gift_orders o JOIN gifts g ON g.id=o.gift_id WHERE o.code=?", code)
        if not o:
            return "none", None
        if o["issued_at"]:
            return "used", o
        if o["expires_at"] < iso(now()):
            return "expired", o
        await self.run("UPDATE gift_orders SET issued_at=?, issued_by=? WHERE code=?", iso(now()), cashier, code)
        return "ok", await self.one("SELECT o.*, g.title FROM gift_orders o JOIN gifts g ON g.id=o.gift_id "
                                    "WHERE o.code=?", code)

    # --- bannerlar ---
    async def banners(self, only_active=True):
        return await self.all("SELECT * FROM banners" + (" WHERE active=1" if only_active else "")
                              + " ORDER BY sort, id DESC")

    # --- savollar ---
    async def quiz_for(self, item):
        rows = await self.all("SELECT * FROM quiz WHERE content_id=? AND approved=1 ORDER BY id", item["id"])
        if not rows and item["series"]:
            rows = await self.all("SELECT * FROM quiz WHERE series=? AND content_id IS NULL AND approved=1 ORDER BY id",
                                  item["series"])
        return rows

    async def answer_quiz(self, child_id, quiz_id, choice):
        q = await self.one("SELECT * FROM quiz WHERE id=?", quiz_id)
        if not q:
            return None
        if await self.one("SELECT 1 FROM quiz_done WHERE child_id=? AND quiz_id=?", child_id, quiz_id):
            return {"ok": choice == q["correct"], "correct": q["correct"], "stars": 0, "again": True}
        ok = choice == q["correct"]
        stars = int(await self.setting("quiz_stars")) if ok else 0
        await self.run("INSERT INTO quiz_done (child_id, quiz_id, ok, stars, created_at) VALUES (?,?,?,?,?)",
                       child_id, quiz_id, int(ok), stars, iso(now()))
        await self.add_stars(child_id, stars)
        return {"ok": ok, "correct": q["correct"], "stars": stars, "again": False}

    # --- yangi qism xabari ---
    async def watchers_of_series(self, series):
        """Shu serialni ko'rgan ota-onalar (bola ismi bilan)."""
        return await self.all(
            "SELECT DISTINCT ch.parent_id, ch.name FROM views v JOIN content c ON c.id=v.content_id "
            "JOIN children ch ON ch.id=v.child_id WHERE c.series=?", series)

    async def import_quiz_drafts(self, path, version="1"):
        """Tayyorlangan savollar qoralamasi (tasdiqlanmagan holda) — bir marta."""
        import json as _json
        if await self.setting("quiz_drafts") == version or not os.path.exists(path):
            return 0
        if (await self.one("SELECT COUNT(*) c FROM content"))["c"] == 0:
            return 0  # kontent hali yuklanmagan — keyingi ishga tushishda
        with open(path, encoding="utf-8") as f:
            items = _json.load(f)
        n = 0
        for q in items:
            if q.get("title"):
                c = await self.one("SELECT id FROM content WHERE series IS ? AND title=? ORDER BY id LIMIT 1",
                                   q["series"], q["title"])
                if not c:
                    continue
                if await self.one("SELECT 1 FROM quiz WHERE content_id=? AND q=?", c["id"], q["q"]):
                    continue
                cid, series = c["id"], None
            else:
                if await self.one("SELECT 1 FROM quiz WHERE series=? AND content_id IS NULL AND q=?", q["series"], q["q"]):
                    continue
                cid, series = None, q["series"]
            await self.conn.execute("INSERT INTO quiz (content_id, series, q, a, b, c, correct, approved) "
                                    "VALUES (?,?,?,?,?,?,?,0)", (cid, series, q["q"], q["a"], q["b"], q["c"], q["correct"]))
            n += 1
        await self.conn.commit()
        await self.set_setting("quiz_drafts", version)
        return n

    # --- do'st taklifi ---
    @staticmethod
    def ref_code(tg_id: int) -> str:
        n, s = int(tg_id), ""
        while n:
            n, r = divmod(n, 36)
            s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
        return "r" + (s or "0")

    @staticmethod
    def ref_decode(code: str):
        try:
            return int(code[1:], 36) if code and code.startswith("r") else None
        except ValueError:
            return None

    async def register_referral(self, new_tg_id, full_name, code):
        """Yangi foydalanuvchi taklif havolasi bilan keldi. Faqat haqiqatan yangi bo'lsa yoziladi."""
        ref = self.ref_decode(code)
        if await self.get_parent(new_tg_id):
            return False
        await self.ensure_parent(new_tg_id, full_name)
        if ref and ref != new_tg_id and await self.get_parent(ref):
            await self.set_parent(new_tg_id, referred_by=ref)
            return True
        return False

    async def settle_referral(self, parent_id):
        """Taklif bilan kelgan oila birinchi bolasini qo'shdi -> ikkala tomonga yulduz.
        -> None yoki {"ref": taklif qilgan tg_id, "ref_child": ism, "bonus": n, "new_bonus": m}"""
        p = await self.get_parent(parent_id)
        if not p or not p["referred_by"] or p["ref_awarded"]:
            return None
        cur = await self.conn.execute("UPDATE parents SET ref_awarded=1 WHERE tg_id=? AND ref_awarded=0", (parent_id,))
        await self.conn.commit()
        if cur.rowcount != 1:
            return None
        bonus, new_bonus = int(await self.setting("ref_bonus")), int(await self.setting("ref_new_bonus"))
        ref_child = await self.active_child(p["referred_by"])
        if ref_child:
            await self.add_stars(ref_child["id"], bonus)
        new_child = await self.active_child(parent_id)
        if new_child:
            await self.add_stars(new_child["id"], new_bonus)
        return {"ref": p["referred_by"], "ref_child": ref_child["name"] if ref_child else "", "bonus": bonus if ref_child else 0,
                "new_bonus": new_bonus if new_child else 0, "new_name": new_child["name"] if new_child else ""}

    async def ref_stats(self, tg_id):
        r = await self.one("SELECT COUNT(*) n, SUM(ref_awarded) ok FROM parents WHERE referred_by=?", tg_id)
        return {"invited": r["n"] or 0, "joined": r["ok"] or 0}

    async def top_referrers(self, limit=15):
        return await self.all(
            "SELECT p.tg_id, p.full_name, COUNT(r.tg_id) n, SUM(r.ref_awarded) ok FROM parents r "
            "JOIN parents p ON p.tg_id=r.referred_by GROUP BY p.tg_id ORDER BY ok DESC, n DESC LIMIT ?", limit)
