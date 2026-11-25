"""Mini App API sinovi (Telegram'siz). Ishga tushirish: python -m tests.test_miniapp"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = "/tmp/kiddy_mini_test.db"
if os.path.exists("/tmp/kiddy_mini_test.db"):
    os.remove("/tmp/kiddy_mini_test.db")

import httpx  # noqa: E402

import db as dbm  # noqa: E402
from miniapp.api import check_init_data, create_miniapp  # noqa: E402

TOKEN = "123456:TEST-token"


def init_data(uid, name="Aziz", token=TOKEN, age=0):
    d = {"auth_date": str(int(time.time()) - age), "query_id": "q1",
         "user": json.dumps({"id": uid, "first_name": name}, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)


def check(cond, label, extra=""):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        print("    ", str(extra)[:500])
        os._exit(1)


async def main():
    db = dbm.DB(os.environ["DB_PATH"])
    await db.connect()
    app = create_miniapp(db, None, TOKEN)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    H = {"X-Init-Data": init_data(111)}

    # imzo
    check(check_init_data(init_data(111), TOKEN)["id"] == 111, "to'g'ri imzo qabul qilinadi")
    check(check_init_data(init_data(111, token="999:other"), TOKEN) is None, "boshqa bot imzosi rad etiladi")
    check(check_init_data(init_data(111, age=90000), TOKEN) is None, "eskirgan (25 soat) imzo rad etiladi")
    tampered = init_data(111).replace("Aziz", "Hack")
    check(check_init_data(tampered, TOKEN) is None, "o'zgartirilgan ma'lumot rad etiladi")
    r = await c.get("/api/me")
    check(r.status_code == 401, "imzosiz so'rov -> 401")
    r = await c.get("/")
    check(r.status_code == 200 and "Kiddy TV" in r.text, "sahifa ochiladi")

    # profil
    r = (await c.get("/api/me", headers=H)).json()
    check(r["ok"] and r["active"] is None and r["children"] == [], "yangi foydalanuvchi: bola yo'q")
    r = await c.post("/api/child", headers=H, json={"name": "Ali", "birth": "2099-01-01"})
    check(r.status_code == 400, "kelajakdagi sana rad etildi")
    r = (await c.post("/api/child", headers=H, json={"name": "Ali", "birth": "2020-03-15"})).json()
    ali = r["child"]["id"]
    check(r["ok"] and r["child"]["age"] >= 6, "bola qo'shildi (date input formati)")
    r = (await c.post("/api/child", headers=H, json={"name": "Madina", "birth": "2023-01-01"})).json()
    mad = r["child"]["id"]
    me = (await c.get("/api/me", headers=H)).json()
    check(me["active"]["name"] == "Madina" and len(me["children"]) == 2, "ikkinchi bola faol")
    await c.post("/api/child/active", headers=H, json={"id": ali})
    H2 = {"X-Init-Data": init_data(222, "Begona")}
    r = await c.post("/api/child/active", headers=H2, json={"id": ali})
    check(r.status_code == 404, "boshqa oilaning bolasini tanlab bo'lmaydi")

    # kontent
    z = await db.add_content("cartoon", "Zumrad va Qimmat", "youtube", "https://youtu.be/dQw4w9WgXcQ", None, 3, 8, 12)
    small = await db.add_content("cartoon", "Alifbo", "youtube", "https://www.youtube.com/watch?v=abcdefghijk", None, 1, 3, 4)
    r = (await c.get("/api/content?kind=cartoon", headers=H)).json()
    titles = [i["title"] for i in r["items"]]
    check(titles == ["Zumrad va Qimmat"] and r["items"][0]["thumb"].endswith("dQw4w9WgXcQ/hqdefault.jpg"),
          "yoshga mos ro'yxat + YouTube rasmi")
    r = await c.post("/api/open", headers=H, json={"id": small})
    check(r.status_code == 403, "yoshga mos bo'lmagan kontentni ochib bo'lmaydi")
    await db.set_parent(111, sleep_on=0)
    r = (await c.post("/api/open", headers=H, json={"id": z})).json()
    check(r["ok"] and r["youtube"] == "dQw4w9WgXcQ" and r["stars_added"] == 0 and r["view_id"],
          "ochildi: YouTube id, yulduz hali yo'q")
    p = (await c.post("/api/progress", headers=H, json={"view_id": r["view_id"], "played": 400, "duration": 720})).json()
    check(p["stars_added"] == 0 and p["reason"] == "erta", "darhol 'yarmi ko'rildi' deb aldab bo'lmaydi (vaqt o'tmagan)")
    await db.run("UPDATE views SET created_at=? WHERE id=?", dbm.iso(dbm.now() - __import__('datetime').timedelta(minutes=7)), r["view_id"])
    p = (await c.post("/api/progress", headers=H, json={"view_id": r["view_id"], "played": 200, "duration": 720})).json()
    check(p["stars_added"] == 0, "yarmidan kam ko'rilgan: yulduz yo'q")
    p = (await c.post("/api/progress", headers=H, json={"view_id": r["view_id"], "played": 370, "duration": 720})).json()
    check(p["stars_added"] == 5, "yarmi ko'rildi: +5 yulduz")
    p = (await c.post("/api/progress", headers=H, json={"view_id": r["view_id"], "played": 700, "duration": 720})).json()
    check(p["stars_added"] == 0 and p["reason"] == "allaqachon", "ikkinchi marta berilmaydi")
    r = (await c.post("/api/like", headers=H, json={"id": z})).json()
    check(r["liked"], "yoqdi")

    # limit
    await db.set_parent(111, daily_limit=20)
    r = await c.post("/api/open", headers=H, json={"id": z})
    check(r.status_code == 200, "12+12 daq: hali limit ichida edi (12<20)")
    r = await c.post("/api/open", headers=H, json={"id": z})
    check(r.status_code == 403 and "vaqt" in r.json()["error"], "kunlik limit (24>=20) ishladi")
    r = (await c.post("/api/game/start", headers=H, json={})).json()
    check(r["ok"] is False, "limit tugasa o'yin ham yopiq")
    await db.set_parent(111, daily_limit=240)

    # o'yinlar
    r = (await c.post("/api/game/done", headers=H, json={"game": "pairs"})).json()
    check(r["stars_added"] == 3, "o'yin: +3 yulduz")
    r = await c.post("/api/game/done", headers=H, json={"game": "hack"})
    check(r.status_code == 400, "noma'lum o'yin rad etildi")
    for _ in range(12):
        r = (await c.post("/api/game/done", headers=H, json={"game": "colors"})).json()
    check(r["stars_added"] == 0, "kuniga 10 tadan ortiq o'yin yulduz bermaydi")

    # kupon
    me = (await c.get("/api/me", headers=H)).json()
    stars = me["active"]["stars"]
    r = await c.post("/api/redeem", headers=H, json={"percent": 50, "cost": 1})
    check(r.status_code == 400, "soxta tarif rad etildi")
    await db.run("UPDATE children SET stars=150 WHERE id=?", ali)
    r = (await c.post("/api/redeem", headers=H, json={"percent": 5, "cost": 100})).json()
    check(r["ok"] and r["code"].startswith("KIDDY-") and r["stars"] == 50, f"kupon olindi {r.get('code')}")
    r = (await c.get("/api/coupons", headers=H)).json()
    check(len(r["coupons"]) == 1, "kuponlar ro'yxati")

    # ota-ona
    r = await c.get("/api/parent", headers=H)
    check(r.status_code == 403, "PINsiz ota-ona paneli yopiq")
    r = (await c.post("/api/parent/unlock", headers=H, json={"pin": "1234"})).json()
    key = r["key"]
    check(r["ok"] and (await db.get_parent(111))["pin_hash"] == dbm.hash_pin("1234"), "birinchi PIN o'rnatildi")
    HP = {**H, "X-Parent-Key": key}
    d = (await c.get("/api/parent", headers=HP)).json()
    check(d["ok"] and len(d["kids"]) == 2 and d["kids"][0]["today"] > 0, "panel: bolalar va bugungi vaqt")
    r = await c.get("/api/parent", headers={**H2, "X-Parent-Key": key})
    check(r.status_code == 403, "boshqa odam bu kalit bilan kira olmaydi")
    await c.post("/api/parent", headers=HP, json={"limit": 999, "sleep_from": "20:30", "report": False})
    p = await db.get_parent(111)
    check(p["daily_limit"] == 240 and p["sleep_from"] == "20:30" and p["report_on"] == 0, "sozlamalar saqlandi")
    r = await c.post("/api/parent", headers=HP, json={"sleep_to": "25:99"})
    check(r.status_code == 400, "noto'g'ri vaqt rad etildi")
    await c.post("/api/parent", headers=HP, json={"block": z})
    r = (await c.get("/api/content?kind=cartoon", headers=H)).json()
    check(r["items"] == [], "yopilgan kontent ro'yxatda yo'q")
    await c.post("/api/parent", headers=HP, json={"unblock": z})
    for _ in range(5):
        r = await c.post("/api/parent/unlock", headers=H, json={"pin": "0000"})
    r = await c.post("/api/parent/unlock", headers=H, json={"pin": "1234"})
    check(r.status_code == 429, "5 ta xato PINdan keyin bloklanadi")
    await c.post("/api/parent", headers=HP, json={"delete_child": mad})
    check(len(await db.children(111)) == 1, "bola o'chirildi")

    await db.close()
    print("\nMini App testlari o'tdi.")
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
