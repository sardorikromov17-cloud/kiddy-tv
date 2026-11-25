"""Admin panelni sinash (Telegram'siz). Ishga tushirish: python -m tests.test_panel"""
import asyncio
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = "/tmp/kiddy_panel_test.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["PANEL_SECRET"] = "test-secret"
if os.path.exists("/tmp/kiddy_panel_test.db"):
    os.remove("/tmp/kiddy_panel_test.db")

import html as _html  # noqa: E402

import httpx  # noqa: E402


def H(r):
    return _html.unescape(r.text)

import db as dbm  # noqa: E402
from admin_panel.app import create_app  # noqa: E402


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **k):
        self.sent.append((chat_id, text))

    async def send_video(self, chat_id, inp, **k):
        self.sent.append((chat_id, "VIDEO"))
        return SimpleNamespace(video=SimpleNamespace(file_id="TGVID42", duration=420))

    async def send_audio(self, chat_id, inp, **k):
        return SimpleNamespace(audio=SimpleNamespace(file_id="TGAUD1", duration=90))

    async def get_file(self, fid):
        return SimpleNamespace(file_path="x.jpg")

    async def download_file(self, path):
        import io
        return io.BytesIO(b"\xff\xd8JPEG")


def check(cond, label, extra=""):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        print("    ", str(extra)[:600])
        os._exit(1)


def token(html):
    m = re.search(r'name="token" value="([^"]+)"', html)
    return m.group(1) if m else ""


async def main():
    db = dbm.DB(os.environ["DB_PATH"])
    await db.connect()
    bot = FakeBot()
    app = create_app(db, bot)
    T = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=T, base_url="http://t", follow_redirects=True)

    # --- birinchi sozlash ---
    r = await c.get("/")
    check(str(r.url).endswith("/setup") and "Birinchi admin" in H(r), "bo'sh panel -> birinchi admin sahifasi")
    r = await c.post("/setup", data={"username": "a", "password": "123"})
    check("kamida 6" in H(r), "qisqa login/parol rad etildi")
    r = await c.post("/setup", data={"username": "ikromov", "full_name": "Ikromov", "password": "kiddy2026"})
    check("Bosh sahifa" in H(r) and "Xush kelibsiz" in H(r), "admin yaratildi, bosh sahifa ochildi")
    r = await c.get("/setup")
    check("Birinchi admin" not in H(r), "setup ikkinchi marta ochilmaydi")

    # --- ma'lumot tayyorlash (bot orqali kelgan kabi) ---
    await db.ensure_parent(111, "Aziz Karimov")
    ali = await db.add_child(111, "Ali", "2020-03-15")
    await db.ensure_parent(222, "Dilnoza")
    mad = await db.add_child(222, "Madina", "2022-01-01")

    # --- kontent ---
    r = await c.get("/content")
    t = token(r.text)
    r = await c.post("/content/add", data={"token": t, "kind": "cartoon", "title": "Zumrad va Qimmat",
                                           "age_min": 3, "age_max": 8, "link": "https://example.com/x"})
    check("YouTube havolasini" in H(r), "YouTube bo'lmagan havola rad etildi")
    r = await c.post("/content/add", data={"token": t, "kind": "cartoon", "title": "Zumrad va Qimmat",
                                           "age_min": 3, "age_max": 8, "minutes": 12,
                                           "link": "https://youtu.be/abc"})
    check("Qo'shildi: Zumrad" in H(r), "YouTube multfilm qo'shildi")
    r = await c.post("/content/add", data={"token": t, "kind": "video", "title": "Raqamlar", "age_min": 3,
                                           "age_max": 6}, files={"file": ("r.mp4", b"0" * 2048, "video/mp4")})
    vid = await db.one("SELECT * FROM content WHERE title='Raqamlar'")
    check(vid and vid["source"] == "TGVID42" and vid["minutes"] == 7, "video fayl Telegram'ga yuklandi, 7 daq")
    r = await c.post("/content/add", data={"token": t, "kind": "video", "title": "PDF", "age_min": 3,
                                           "age_max": 6}, files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    check("Faqat video yoki audio" in H(r), "PDF rad etildi")
    r = await c.post("/content/add", data={"token": "xato", "kind": "cartoon", "title": "X", "age_min": 1,
                                           "age_max": 2, "link": "https://youtu.be/q"})
    check("eskirgan" in H(r) and not await db.one("SELECT 1 FROM content WHERE title='X'"),
          "noto'g'ri token (CSRF) bilan hech narsa saqlanmadi")
    zid = (await db.one("SELECT id FROM content WHERE title='Zumrad va Qimmat'"))["id"]
    r = await c.get(f"/content/{zid}")
    r = await c.post(f"/content/{zid}", data={"token": token(r.text), "title": "Zumrad va Qimmat (1-qism)",
                                              "kind": "cartoon", "age_min": 4, "age_max": 9, "minutes": 13,
                                              "active": 1, "link": "https://youtu.be/abc2"})
    z = await db.get_content(zid)
    check(z["title"].endswith("(1-qism)") and z["age_min"] == 4 and z["source"] == "https://youtu.be/abc2",
          "kontent tahrirlandi")
    r = await c.post(f"/content/{zid}/toggle", data={"token": t})
    check((await db.get_content(zid))["active"] == 0, "kontent yashirildi")
    items, _ = await db.list_content("cartoon", age=6)
    check(not items, "yashirilgan kontent botda ko'rinmaydi")
    await c.post(f"/content/{zid}/toggle", data={"token": t})

    # --- yosh chegarasi tugmasi ---
    items, _ = await db.list_content("cartoon", age=1)
    check(not items, "yosh chegarasi yoqilgan: 1 yoshliga 4-9 yosh multfilm ko'rinmaydi")
    r = await c.get("/content")
    check("Yosh chegarasini olib tashlash" in H(r), "kontent sahifasida yosh chegarasi tugmasi bor")
    r = await c.post("/age-limit", data={"token": token(r.text), "back": "/content"})
    check("olib tashlandi" in H(r) and "Yosh chegarasini qo'yish" in H(r), "yosh chegarasi olib tashlandi")
    items, _ = await db.list_content("cartoon", age=1)
    g = await db.list_grouped("cartoon", 1, 111)
    check(items and g, "chegarasiz: 1 yoshliga ham hamma kontent ochiq (bot va ilova)")
    r = await c.post("/age-limit", data={"token": token(r.text), "back": "/"})
    check("Bosh sahifa" in H(r) and "qo'yildi" in H(r), "yosh chegarasi qayta yoqildi")
    items, _ = await db.list_content("cartoon", age=1)
    check(not items, "chegara qaytdi")

    # --- ko'rishlar, yoqdi, reyting ---
    for _ in range(3):
        await db.record_view(ali, await db.get_content(zid))
    await db.record_view(mad, vid)
    await db.toggle_like(ali, zid)
    await db.toggle_like(mad, zid)
    r = await c.get("/ratings?period=7")
    check("Ali" in H(r) and "Zumrad va Qimmat (1-qism)" in H(r), "reytinglar sahifasi")
    r = await c.get("/")
    check("Multfilmlar" in H(r) and "Hafta yulduzlari" in H(r), "bosh sahifa statistikasi")

    # --- sozlamalar -> bot ---
    r = await c.get("/settings")
    st = token(r.text)
    form = {"token": st, "stars_per_view": 7, "coupon_days": 14, "birthday_percent": 12,
            "contest_percent": 25, "default_daily_limit": 45, "contest_title": "Qishki ertak",
            "tp0": 5, "tc0": 50, "tp1": 10, "tc1": 120, "tp2": "", "tc2": "", "tp3": "", "tc3": ""}
    r = await c.post("/settings", data=dict(form, stars_per_view=0))
    check("oralig'ida" in H(r), "noto'g'ri sozlama rad etildi")
    r = await c.post("/settings", data=form)
    check("saqlandi" in H(r), "sozlamalar saqlandi")
    s = await db.record_view(ali, vid)
    check(s == 7, "bot endi 7 yulduz beradi")
    check(await db.tiers() == [(5, 50), (10, 120)], "yangi tariflar: 5%/50, 10%/120")
    check(await db.redeem_stars(111, ali, 15, 400) is None, "eski tarif (15%/400) endi ishlamaydi")
    await db.ensure_parent(333, "Yangi")
    check((await db.get_parent(333))["daily_limit"] == 45, "yangi oila 45 daqiqa limit bilan")

    # --- kuponlar ---
    await db.run("UPDATE children SET stars=80 WHERE id=?", ali)
    code = await db.redeem_stars(111, ali, 5, 50)
    check(code is not None, f"bola yulduzni almashtirdi: {code}")
    cp = await db.one("SELECT * FROM coupons WHERE code=?", code)
    check(cp["expires_at"][:10] > cp["created_at"][:10], "muddat 14 kun bilan")
    r = await c.get(f"/coupons?check={code.lower()}")
    check("5% chegirma" in H(r) and "Ishlatildi deb belgilash" in H(r), "kassada kupon topildi")
    r = await c.post("/coupons/use", data={"token": token(r.text), "code": code})
    check("ishlatildi" in H(r) and (await db.one("SELECT used_by FROM coupons WHERE code=?", code))["used_by"]
          == "panel:ikromov", "kupon ishlatildi, kim ishlatgani yozildi")
    check(any(cid == 111 and "ishlatildi" in tx for cid, tx in bot.sent), "ota-onaga xabar ketdi")
    r = await c.post("/coupons/use", data={"token": t, "code": code})
    check("allaqachon" in H(r), "ikkinchi marta ishlamaydi")
    r = await c.get("/coupons?status=used")
    check(code in H(r), "ishlatilganlar ro'yxatida")

    # --- oilalar: qo'lda kupon ---
    r = await c.get("/families?q=Madina")
    check("Dilnoza" in H(r) and "Aziz" not in H(r), "oilalar qidiruvi")
    r = await c.post(f"/families/{mad}/coupon", data={"token": token(r.text), "percent": 15})
    check("Madina uchun kupon" in H(r) and any(cid == 222 for cid, _ in bot.sent), "qo'lda kupon berildi")

    # --- tanlov ---
    await db.run("INSERT INTO contest (parent_id, child_id, file_id, created_at) VALUES (111,?,?,?)",
                 ali, "PHOTO1", "2026-11-24 10:00:00")
    r = await c.get("/contest")
    check("Qishki ertak" in H(r) and "/tg-file/PHOTO1" in H(r), "tanlov rasmlari")
    img = await c.get("/tg-file/PHOTO1")
    check(img.status_code == 200 and img.content.startswith(b"\xff\xd8"), "rasm Telegram'dan olindi")
    eid = (await db.one("SELECT id FROM contest"))["id"]
    r = await c.post(f"/contest/{eid}/win", data={"token": token(r.text)})
    win = await db.one("SELECT * FROM coupons WHERE reason='contest'")
    check(win and win["percent"] == 25 and any("g'olib" in tx for _, tx in bot.sent), "g'olib: 25% kupon va tabrik")

    # --- xabar yuborish ---
    n0 = len(bot.sent)
    r = await c.get("/broadcast")
    r = await c.post("/broadcast", data={"token": token(r.text), "text": "Yangi ertaklar!"})
    await asyncio.sleep(0.5)
    check(len([1 for _, tx in bot.sent[n0:] if tx == "Yangi ertaklar!"]) == 3, "xabar 3 ta oilaga ketdi")

    # --- xodimlar va kassir roli ---
    r = await c.get("/staff")
    r = await c.post("/staff/add", data={"token": token(r.text), "username": "kassir1", "full_name": "Soy bo'yi",
                                         "password": "kassa123", "role": "kassir"})
    check("Xodim qo'shildi" in H(r), "kassir qo'shildi")
    k = httpx.AsyncClient(transport=T, base_url="http://t", follow_redirects=True)
    r = await k.post("/login", data={"username": "kassir1", "password": "xato"})
    check("noto'g'ri" in H(r), "xato parol bilan kirib bo'lmaydi")
    r = await k.post("/login", data={"username": "KASSIR1", "password": "kassa123"})
    check(str(r.url).endswith("/coupons"), "kassir kirdi -> kuponlar sahifasi")
    for path in ["/", "/settings", "/staff", "/content", "/broadcast"]:
        r = await k.get(path)
        check(str(r.url).endswith("/coupons"), f"kassir {path} ga kira olmaydi")
    r = await k.post("/settings", data=dict(form, token="x", stars_per_view=99))
    check(await db.setting("stars_per_view") == "7", "kassir sozlamani o'zgartira olmaydi")
    kid = (await db.one("SELECT id FROM staff WHERE username='kassir1'"))["id"]
    r = await c.get("/staff")
    await c.post(f"/staff/{kid}/toggle", data={"token": token(r.text)})
    r = await k.get("/coupons")
    check(str(r.url).endswith("/login"), "o'chirilgan kassir paneldan chiqarildi")
    me = (await db.one("SELECT id FROM staff WHERE username='ikromov'"))["id"]
    r = await c.post(f"/staff/{me}/toggle", data={"token": t})
    check("O'zingizni" in H(r), "admin o'zini o'chira olmaydi")

    # --- chiqish ---
    await c.get("/logout")
    r = await c.get("/content")
    check(str(r.url).endswith("/login"), "chiqqandan keyin panel yopiq")
    anon = httpx.AsyncClient(transport=T, base_url="http://t")
    r = await anon.get("/tg-file/PHOTO1")
    check(r.status_code == 403, "kirmagan odam rasmlarni ko'ra olmaydi")

    await db.close()
    print("\nPanel testlari o'tdi.")
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
