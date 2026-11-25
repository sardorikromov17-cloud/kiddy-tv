"""Yangi imkoniyatlar sinovi: davom ettirish, sevimlilar, qidiruv, seriya, daraja, sovg'a, banner, savollar,
yangi qism xabari. Ishga tushirish: python -m tests.test_features"""
import asyncio
import hashlib
import hmac
import html as _html
import json
import os
import re
import sys
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = "/tmp/kiddy_feat_test.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["PANEL_SECRET"] = "test-secret"
if os.path.exists("/tmp/kiddy_feat_test.db"):
    os.remove("/tmp/kiddy_feat_test.db")

import httpx  # noqa: E402

import db as dbm  # noqa: E402
from admin_panel.app import create_app  # noqa: E402
from miniapp.api import create_miniapp  # noqa: E402

TOKEN = "123456:TEST-token"


def init_data(uid):
    d = {"auth_date": str(int(time.time())), "query_id": "q1",
         "user": json.dumps({"id": uid, "first_name": "Aziz"}, separators=(",", ":"))}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    sec = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **k):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, inp, **k):
        return SimpleNamespace(photo=[SimpleNamespace(file_id="PHOTO1")])


def check(cond, label, extra=""):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        print("    ", str(extra)[:600])
        os._exit(1)


def token(text):
    m = re.search(r'name="token" value="([^"]+)"', text)
    return m.group(1) if m else ""


async def main():
    db = dbm.DB(os.environ["DB_PATH"])
    await db.connect()
    bot = FakeBot()
    mini = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_miniapp(db, bot, TOKEN)), base_url="http://m")
    panel = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(db, bot)), base_url="http://p",
                              follow_redirects=True)
    H = {"X-Init-Data": init_data(111)}

    await db.ensure_parent(111, "Aziz")
    kid = await db.add_child(111, "Ali", "2019-01-01")
    await db.set_parent(111, sleep_on=0)
    eps = [await db.add_content("cartoon", f"{i}-qism Mevalar", "youtube", f"https://youtu.be/abcdefghij{i}",
                                None, 3, 10, 10, "Bek va Lola", i) for i in (1, 2, 3)]
    other = await db.add_content("audio", "Zumrad va Qimmat", "youtube", "https://youtu.be/zzzzzzzzzzz", None, 3, 10, 6)

    # --- davom ettirish va oxirgilar ---
    r = (await mini.post("/api/open", headers=H, json={"id": eps[0]})).json()
    vid = r["view_id"]
    check(r["pos"] == 0 and r["quiz"] == 0, "birinchi ochilish: joy 0, savol yo'q")
    await mini.post("/api/pos", headers=H, json={"view_id": vid, "pos": 125})
    h = (await mini.get("/api/home", headers=H)).json()
    check([i["id"] for i in h["cont"]] == [eps[1]], "Davom ettirish: keyingi qism (2-qism)", h["cont"])
    check(h["recent"][0]["id"] == eps[0] and h["recent"][0]["pos"] == 125, "Oxirgi ko'rganlar + joyi saqlangan")
    r = (await mini.post("/api/open", headers=H, json={"id": eps[0]})).json()
    check(r["pos"] == 125, "qayta ochilganda qolgan joydan (125 s)")

    # --- sevimlilar va qidiruv ---
    await mini.post("/api/like", headers=H, json={"id": other})
    f = (await mini.get("/api/favorites", headers=H)).json()["items"]
    check([i["id"] for i in f] == [other], "Sevimlilarim: yoqdi bosilgan kontent")
    s = (await mini.get("/api/search?q=bek", headers=H)).json()["items"]
    check(len(s) == 3 and all(i["series"] == "Bek va Lola" for i in s), "qidiruv serial nomi bo'yicha")
    s = (await mini.get("/api/search?q=Zumrad", headers=H)).json()["items"]
    check([i["id"] for i in s] == [other], "qidiruv nom bo'yicha")
    check((await mini.get("/api/search?q=z", headers=H)).json()["items"] == [], "1 harf bilan qidirmaydi")

    # --- kunlik seriya ---
    today = dbm.now().date()
    for d in (1, 2):
        await db.run("INSERT OR IGNORE INTO child_days (child_id, day) VALUES (?,?)", kid,
                     (today - timedelta(days=d)).isoformat())
    before = (await db.child(kid))["stars"]
    h = (await mini.get("/api/home", headers=H)).json()
    check(h["streak"] == 3 and h["bonus"] == 5 and h["stars"] == before + 5, "3 kun ketma-ket: +5 bonus", h)
    h = (await mini.get("/api/home", headers=H)).json()
    check(h["bonus"] == 0 and h["stars"] == before + 5, "bonus kuniga bir marta")

    # --- daraja va nishonlar ---
    await db.run("UPDATE children SET total_stars=160 WHERE id=?", kid)
    pr = (await mini.get("/api/profile", headers=H)).json()
    check(pr["level"]["n"] == 3 and pr["level"]["name"] == "Bilimdon" and pr["level"]["next"] == 300,
          "daraja: 160 yulduz = 3-daraja Bilimdon", pr["level"])
    bad = {b["id"]: b for b in pr["badges"]}
    check(bad["likes"]["cur"] == 1 and not bad["likes"]["done"] and pr["streak"] == 3, "nishonlar va seriya")
    await db.add_stars(kid, 10)
    c = await db.child(kid)
    check(c["total_stars"] == 170, "umumiy yulduz ham oshadi")

    # --- panelga kirish ---
    r = await panel.post("/setup", data={"username": "ikromov", "full_name": "Ikromov", "password": "kiddy2026"})
    check("Bosh sahifa" in _html.unescape(r.text), "panel: admin")

    # --- sovg'alar ---
    r = await panel.get("/gifts")
    t = token(r.text)
    r = await panel.post("/gifts/add", data={"token": t, "title": "Kichik mashina", "stars": 50, "stock": "1",
                                             "note": "3+"}, files={"image": ("m.jpg", b"\xff\xd8JPEG", "image/jpeg")})
    check("Sovg'a qo'shildi" in _html.unescape(r.text), "panel: sovg'a qo'shildi (rasm bilan)")
    await panel.post("/gifts/add", data={"token": t, "title": "Katta ayiq", "stars": 9999})
    g = (await mini.get("/api/gifts", headers=H)).json()
    check(len(g["items"]) == 2 and g["items"][0]["img"], "ilovada sovg'alar ro'yxati")
    big = g["items"][1]["id"]
    r = (await mini.post("/api/gift/redeem", headers=H, json={"id": big})).json()
    check(not r["ok"] and "yetmaydi" in r["error"], "yulduz yetmasa sovg'a berilmaydi")
    await db.run("UPDATE children SET stars=60 WHERE id=?", kid)
    r = (await mini.post("/api/gift/redeem", headers=H, json={"id": g["items"][0]["id"]})).json()
    code = r.get("code", "")
    check(r["ok"] and code.startswith("SOVGA-") and r["stars"] == 10, "sovg'a olindi: kod, 50 yulduz yechildi", r)
    check(any("SOVGA-" in t for _, t in bot.sent), "ota-onaga kod botda yuborildi")
    g = (await mini.get("/api/gifts", headers=H)).json()
    check(len(g["items"]) == 1 and g["orders"][0]["code"] == code, "qoldiq tugadi — ro'yxatdan chiqdi, kod ko'rinadi")
    r = await panel.get(f"/coupons?check={code}")
    check(code in _html.unescape(r.text) and "Sovg'a berildi" in _html.unescape(r.text),
          "kassada kod -> sovg'a sahifasiga o'tadi")
    r = await panel.post("/gifts/issue", data={"token": token(r.text), "code": code})
    check("Berildi" in _html.unescape(r.text), "kassir sovg'ani berdi")
    r = await panel.post("/gifts/issue", data={"token": token(r.text), "code": code})
    check("allaqachon" in _html.unescape(r.text), "ikkinchi marta berib bo'lmaydi")

    # --- banner ---
    r = await panel.get("/banners")
    r = await panel.post("/banners/add", data={"token": token(r.text), "title": "Yangi konstruktorlar!",
                                               "text": "Do'konda", "link": "https://example.com",
                                               "image_url": "https://example.com/b.jpg"})
    check("Banner qo'shildi" in _html.unescape(r.text), "panel: banner qo'shildi")
    h = (await mini.get("/api/home", headers=H)).json()
    check(h["banners"][0]["title"] == "Yangi konstruktorlar!" and h["banners"][0]["img"], "ilovada banner")
    r = await mini.get(h["banners"][0]["img"], headers=H, follow_redirects=False)
    check(r.status_code in (302, 307) and r.headers["location"] == "https://example.com/b.jpg", "banner rasmi")

    # --- savollar ---
    r = await panel.get(f"/content/{eps[1]}")
    r = await panel.post(f"/content/{eps[1]}/quiz", data={"token": token(r.text), "q": "Lola nima yedi?",
                                                         "a": "Olma", "b": "Nok", "c": "Uzum", "correct": "b"})
    check("Lola nima yedi?" in _html.unescape(r.text), "panel: savol qo'shildi")
    r = await panel.post(f"/content/{eps[1]}/quiz", data={"token": token(r.text), "q": "Bek necha yoshda?",
                                                         "a": "5", "b": "7", "correct": "a", "whole": "1"})
    o = (await mini.post("/api/open", headers=H, json={"id": eps[1]})).json()
    check(o["quiz"] == 1, "2-qism: o'z savoli bor (1 ta)")
    o3 = (await mini.post("/api/open", headers=H, json={"id": eps[2]})).json()
    check(o3["quiz"] == 1, "3-qism: serial savoli chiqadi")
    q = (await mini.get(f"/api/quiz?id={eps[1]}", headers=H)).json()
    qid = q["items"][0]["id"]
    check("correct" not in json.dumps(q), "javob ilovaga oldindan berilmaydi")
    st0 = (await db.child(kid))["stars"]
    a = (await mini.post("/api/quiz/answer", headers=H, json={"id": qid, "choice": "a"})).json()
    check(not a["ok"] and a["correct"] == "b" and a["stars"] == 0, "noto'g'ri javob: yulduz yo'q")
    a = (await mini.post("/api/quiz/answer", headers=H, json={"id": qid, "choice": "b"})).json()
    check(a["stars"] == 0 and a["again"], "qayta javob yulduz bermaydi")
    q3 = (await mini.get(f"/api/quiz?id={eps[2]}", headers=H)).json()["items"][0]["id"]
    a = (await mini.post("/api/quiz/answer", headers=H, json={"id": q3, "choice": "a"})).json()
    check(a["ok"] and a["stars"] == 2 and a["total"] == st0 + 2, "to'g'ri javob: +2 yulduz")

    # --- yangi qism xabari ---
    from admin_panel.extra import register  # noqa
    bot.sent.clear()
    await db.set_setting("webapp_url", "https://kiddy.example/app")
    await db.ensure_parent(222, "Boshqa")
    await db.add_child(222, "Vali", "2018-01-01")
    app2 = create_app(db, bot)
    notify = None
    for r_ in app2.router.routes:
        pass
    from admin_panel import extra as ex
    fn = ex.register(app2, db, bot, None, None, None, None)
    await fn("Bek va Lola", 2)
    check(len(bot.sent) == 1 and bot.sent[0][0] == 111 and "Bek va Lola" in bot.sent[0][1] and "Ali" in bot.sent[0][1],
          "yangi qism xabari faqat serialni ko'rgan oilaga", bot.sent)
    await db.set_setting("notify_new", "0")
    bot.sent.clear()
    await fn("Bek va Lola", 1)
    check(not bot.sent, "sozlamada o'chirilsa xabar yuborilmaydi")

    # --- sozlamalar ---
    r = await panel.get("/settings")
    check("Ketma-ket kirish bonusi" in _html.unescape(r.text) and "Davom ettirish" in _html.unescape(r.text),
          "sozlamalarda yangi bo'limlar")
    form = {"token": token(r.text), "stars_per_view": 5, "birthday_percent": 10, "coupon_days": 30,
            "default_daily_limit": 60, "contest_percent": 20, "tp0": 5, "tc0": 100, "show_recent": "1"}
    r = await panel.post("/settings", data=form)
    h = (await mini.get("/api/home", headers=H)).json()
    check(h["cont"] == [] and h["recent"], "«Davom ettirish» o'chirildi, «Oxirgilar» yoniq")
    await db.set_parent(111, daily_limit=0)
    await mini.post("/api/open", headers=H, json={"id": eps[0]})
    form.pop("show_recent"); form["show_continue"] = "1"; form["token"] = token(r.text)
    await panel.post("/settings", data=form)
    h = (await mini.get("/api/home", headers=H)).json()
    check(h["cont"] and h["recent"] == [], "«Oxirgilar» o'chirildi, «Davom ettirish» yoniq")
    await db.set_setting("notify_new", "1")

    # --- do'st taklifi ---
    code = db.ref_code(111)
    check(db.ref_decode(code) == 111, "taklif kodi qaytariladi")
    check(not await db.register_referral(111, "Aziz", db.ref_code(222)), "eski foydalanuvchi taklif bilan hisoblanmaydi")
    check(not await db.register_referral(333, "O'zi", db.ref_code(333)), "o'zini taklif qilib bo'lmaydi")
    check(await db.register_referral(444, "Do'st", code), "yangi do'st taklif bilan keldi")
    ali_before = (await db.child(kid))["stars"]
    H4 = {"X-Init-Data": init_data(444)}
    bot.sent.clear()
    r = (await mini.post("/api/child", headers=H4, json={"name": "Sardor", "birth": "2020-05-05"})).json()
    check(r["ref_bonus"] == 10 and r["child"]["stars"] == 10, "do'stning bolasiga +10", r)
    check((await db.child(kid))["stars"] == ali_before + 20, "taklif qilganning bolasiga +20")
    check(any(cid == 111 and "taklif" in t for cid, t in bot.sent), "taklif qilganga xabar ketdi", bot.sent)
    r = (await mini.post("/api/child", headers=H4, json={"name": "Ikkinchi", "birth": "2021-05-05"})).json()
    check(r["ref_bonus"] == 0 and (await db.child(kid))["stars"] == ali_before + 20, "ikkinchi bola uchun qayta berilmaydi")
    inv = (await mini.get("/api/invite", headers=H)).json()
    check(inv["joined"] == 1 and inv["invited"] == 1 and inv["bonus"] == 20, "taklif statistikasi", inv)
    r = await panel.get("/ratings")
    check("Eng ko'p do'st taklif" in _html.unescape(r.text) and "Aziz" in _html.unescape(r.text), "reytingda takliflar", r.text[-1500:])

    # --- savollar qoralamasi ---
    import json as _j, tempfile
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    _j.dump([{"series": "Bek va Lola", "title": "3-qism Mevalar", "q": "Qaysi biri meva?", "a": "Olma", "b": "Sabzi",
              "c": None, "correct": "a"},
             {"series": "Bek va Lola", "title": None, "q": "Haftada necha kun?", "a": "5", "b": "7", "c": None,
              "correct": "b"},
             {"series": "Yo'q serial", "title": "Yo'q video", "q": "?", "a": "1", "b": "2", "c": None, "correct": "a"}],
            tmp)
    tmp.close()
    n = await db.import_quiz_drafts(tmp.name, "t1")
    check(n == 2 and await db.import_quiz_drafts(tmp.name, "t1") == 0, "qoralama yuklandi (topilmagan video tashlandi), qayta yuklanmaydi")
    await db.set_parent(111, daily_limit=0)
    o3 = (await mini.post("/api/open", headers=H, json={"id": eps[2]})).json()
    check(o3["quiz"] == 1, "tasdiqlanmagan savol ilovada chiqmaydi")
    r = await panel.get("/quiz?status=draft&series=Bek va Lola")
    check("Qaysi biri meva?" in _html.unescape(r.text), "panel: tasdiqlanmaganlar ro'yxati")
    r = await panel.post("/quiz/approve", data={"token": token(r.text), "series": "Bek va Lola", "all_series": "1"})
    check("2 ta savol tasdiqlandi" in _html.unescape(r.text), "serial savollari bittada tasdiqlandi")
    o3 = (await mini.post("/api/open", headers=H, json={"id": eps[2]})).json()
    check(o3["quiz"] == 1, "3-qism: endi o'z savoli (serial savoli o'rniga)")
    o0 = (await mini.post("/api/open", headers=H, json={"id": eps[0]})).json()
    check(o0["quiz"] == 2, "1-qism: serial savollari (2 ta tasdiqlangan)", o0["quiz"])

    # --- do'kon QR tashrifi ---
    r = await panel.get("/store")
    check("<svg" in r.text and "start=qr_" in r.text, "panel: do'kon QR sahifasi (SVG)")
    qr = await db.store_qr()
    r = await panel.post("/store", data={"token": token(r.text), "store_name": "Kiddy Toys Kokand",
                                         "store_address": "Qo'qon, Turkiston ko'chasi 1", "store_hours": "9:00–21:00",
                                         "store_phone": "+998 90 000 00 00", "store_map": "https://yandex.uz/maps/x",
                                         "checkin_stars": "15", "checkin_days": "7", "remind_days": "3"})
    check("Saqlandi" in _html.unescape(r.text), "do'kon ma'lumotlari saqlandi")
    st = (await mini.get("/api/store", headers=H)).json()
    check(st["address"].startswith("Qo'qon") and st["map"] and st["checkin_stars"] == 15, "ilovada do'kon ma'lumoti")
    s0 = (await db.child(kid))["stars"]
    c1 = (await mini.post("/api/checkin", headers=H, json={"code": "https://t.me/kiddytvbot?start=qr_XXXX"})).json()
    check(c1["stars_added"] == 0 and "emas" in c1["text"], "boshqa QR rad etildi")
    c1 = (await mini.post("/api/checkin", headers=H, json={"code": f"https://t.me/kiddytvbot?start=qr_{qr}"})).json()
    check(c1["stars_added"] == 15 and c1["stars"] == s0 + 15, "do'kon QR: +15 yulduz", c1)
    c2 = (await mini.post("/api/checkin", headers=H, json={"code": f"qr_{qr}"})).json()
    check(c2["stars_added"] == 0 and "kundan keyin" in c2["text"], "bir haftada ikkinchi marta berilmaydi", c2)
    ok, _ = await db.checkin(111, kid, f"qr_{qr}", at=dbm.now() + timedelta(days=7, minutes=1))
    check(ok == 15, "7 kundan keyin yana beriladi")
    r = await panel.get("/store")
    r = await panel.post("/store/regenerate", data={"token": token(r.text)})
    check(await db.store_qr() != qr, "QR yangilandi")
    ok, _ = await db.checkin(111, kid, f"qr_{qr}", at=dbm.now() + timedelta(days=30))
    check(ok == 0, "eski QR endi ishlamaydi")
    r = await panel.get("/store/print")
    check("<svg" in r.text and "Chop etish" in r.text, "QR chop etish sahifasi")

    # --- ko'rgazma ---
    eid = await db.run("INSERT INTO contest (parent_id, child_id, file_id, created_at) VALUES (111,?,?,?)",
                       kid, "FILE1", dbm.iso(dbm.now()))
    bot.sent.clear()
    r = await panel.get("/contest")
    check("Ko'rgazmaga qo'yish" in _html.unescape(r.text), "tanlovda ko'rgazma tugmasi")
    r = await panel.post(f"/contest/{eid}/exhibit", data={"token": token(r.text)})
    check(any("ko'rgazmaga" in t for _, t in bot.sent) and "Ko'rgazmada" in _html.unescape(r.text),
          "ko'rgazmaga qo'yildi, oilaga xabar", bot.sent)
    r = await panel.get("/contest/gallery")
    check("FILE1" in r.text and "Ali" in r.text, "ko'rgazma chop etish sahifasi")

    # --- kupon eslatmasi ---
    import scheduler
    code_c = await db.make_coupon(111, kid, 10, 0, "manual")
    await db.run("UPDATE coupons SET expires_at=? WHERE code=?", dbm.iso(dbm.now() + timedelta(days=2)), code_c)
    gcode = (await db.one("SELECT code FROM gift_orders LIMIT 1"))["code"]
    await db.run("UPDATE gift_orders SET issued_at=NULL, expires_at=? WHERE code=?",
                 dbm.iso(dbm.now() + timedelta(days=1)), gcode)
    bot.sent.clear()

    class Clock:
        pass
    real_now = scheduler.now
    scheduler.now = lambda: real_now().replace(hour=11)
    await scheduler.reminders(bot, db)
    await scheduler.reminders(bot, db)
    scheduler.now = real_now
    msgs = [t for _, t in bot.sent]
    check(sum(code_c in t for t in msgs) == 1 and sum(gcode in t for t in msgs) == 1 and "Turkiston" in msgs[0],
          "kupon va sovg'a eslatmasi bir martadan, manzil bilan", msgs)

    await db.close()
    print("\nYangi imkoniyatlar testlari o'tdi.")
    os._exit(0)


asyncio.run(main())
