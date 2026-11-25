"""Botni Telegram'siz sinash: soxta Telegram sessiyasi orqali butun jarayon.
Ishga tushirish: python -m tests.test_flow
"""
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ADMIN_IDS"] = "999"
os.environ["DB_PATH"] = "/tmp/kiddy_test.db"
if os.path.exists("/tmp/kiddy_test.db"):
    os.remove("/tmp/kiddy_test.db")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import (CallbackQuery, Chat, Message, PhotoSize, Update, User,  # noqa: E402
                           Video)

import config  # noqa: E402
import db as dbm  # noqa: E402
import scheduler  # noqa: E402
from handlers import admin, parent, user  # noqa: E402

SENT = []


class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        SENT.append(method)
        ret = method.__returning__
        if ret is bool:
            return True
        name = getattr(ret, "__name__", str(ret))
        if type(method).__name__ == "GetMe":
            return User(id=42, is_bot=True, first_name="Kiddy", username="kiddytvbot")
        if "Message" in name:
            chat_id = getattr(method, "chat_id", 1) or 1
            return Message(message_id=len(SENT), date=datetime.now(), chat=Chat(id=chat_id, type="private"),
                           text=getattr(method, "text", None) or getattr(method, "caption", None))
        return True

    async def stream_content(self, *a, **k):
        yield b""

    async def close(self):
        pass


PARENT = User(id=111, is_bot=False, first_name="Ota")
ADMIN = User(id=999, is_bot=False, first_name="Admin")
uid = 0


def msg(u, text=None, **extra):
    global uid
    uid += 1
    return Update(update_id=uid, message=Message(message_id=uid, date=datetime.now(),
                  chat=Chat(id=u.id, type="private"), from_user=u, text=text, **extra))


def cbq(u, data):
    global uid
    uid += 1
    m = Message(message_id=uid, date=datetime.now(), chat=Chat(id=u.id, type="private"), from_user=u, text="x")
    return Update(update_id=uid, callback_query=CallbackQuery(id=str(uid), from_user=u, chat_instance="c",
                                                              message=m, data=data))


def texts():
    return [getattr(m, "text", None) or getattr(m, "caption", None) or "" for m in SENT]


def last_alert():
    for m in reversed(SENT):
        if type(m).__name__ == "AnswerCallbackQuery":
            return m.text or ""
    return ""


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        print("     oxirgi xabarlar:", texts()[-4:])
        os._exit(1)


async def main():
    config.ADMIN_IDS.add(999)
    db = dbm.DB("/tmp/kiddy_test.db")
    await db.connect()
    bot = Bot("123:ABC", session=FakeSession(), default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage(), db=db)
    dp.include_routers(admin.router, parent.router, user.router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731

    # 1. Ro'yxatdan o'tish
    await feed(msg(PARENT, "/start"))
    check(any("ismi nima" in t for t in texts()), "start: bola ismini so'raydi")
    await feed(msg(PARENT, "Ali"))
    await feed(msg(PARENT, "32.13.2020"))
    check("tushunmadim" in texts()[-1], "noto'g'ri sana rad etildi")
    await feed(msg(PARENT, "15.03.2020"))
    kid = await db.active_child(111)
    check(kid and kid["name"] == "Ali", "bola saqlandi: Ali")

    # 2. Admin kontent qo'shadi
    await feed(msg(ADMIN, "/add"))
    await feed(cbq(ADMIN, "ak:cartoon"))
    await feed(msg(ADMIN, "https://www.youtube.com/watch?v=abc123"))
    await feed(msg(ADMIN, "Zumrad va Qimmat"))
    await feed(msg(ADMIN, "3-8"))
    await feed(msg(ADMIN, "40"))
    check(any("Saqlandi" in t for t in texts()), "admin: YouTube multfilm qo'shildi")
    await feed(msg(ADMIN, "/add"))
    await feed(cbq(ADMIN, "ak:cartoon"))
    await feed(msg(ADMIN, None, video=Video(file_id="VID1", file_unique_id="u1", width=1, height=1, duration=600)))
    await feed(msg(ADMIN, "Alifbo qo'shig'i"))
    await feed(msg(ADMIN, "3-5"))
    v2 = await db.one("SELECT * FROM content WHERE title=?", "Alifbo qo'shig'i")
    check(v2 and v2["minutes"] == 10 and v2["source_type"] == "file", "admin: video fayl, davomiylik avtomatik 10 daq")
    await feed(msg(ADMIN, "/add"))
    await feed(cbq(ADMIN, "ak:film"))
    await feed(msg(ADMIN, "https://youtu.be/xyz"))
    await feed(msg(ADMIN, "Katta bolalar kinosi"))
    await feed(msg(ADMIN, "10-14"))
    await feed(msg(ADMIN, "90"))

    # 3. Yoshga mos ro'yxat (Ali 6 yosh: 3-5 lik video ko'rinmasligi kerak)
    await feed(msg(PARENT, "Multfilmlar"))
    lst = SENT[-1]
    titles = [b.text for row in lst.reply_markup.inline_keyboard for b in row]
    check(any("Zumrad" in t for t in titles) and not any("Alifbo" in t for t in titles),
          "ro'yxat yoshga mos (6 yosh): Zumrad bor, 3–5 yoshlik yo'q")
    await feed(msg(PARENT, "Kinolar"))
    check("mos kontent yo'q" in texts()[-1], "kino 10–14 yosh: 6 yoshliga ko'rinmaydi")

    # 4. Ko'rish -> yulduz (test kechasi ishlashi mumkin, uxlash vaqtini vaqtincha o'chiramiz)
    await db.set_parent(111, sleep_on=0)
    zid = (await db.one("SELECT id FROM content WHERE title='Zumrad va Qimmat'"))["id"]
    await feed(cbq(PARENT, f"open:{zid}"))
    kid = await db.child(kid["id"])
    check(kid["stars"] == 0 and await db.minutes_today(kid["id"]) == 40,
          "botda ochildi: yulduz hali berilmaydi (yarmi ko'rilganda), 40 daqiqa yozildi")
    vid = (await db.one("SELECT id FROM views WHERE child_id=? ORDER BY id DESC", kid["id"]))["id"]
    s0, why = await db.finish_half(vid, kid["id"], 10, 0)
    check(s0 == 0 and why == "erta", "yarmi ko'rilmasa yulduz yo'q")
    from datetime import timedelta
    s1, _ = await db.finish_half(vid, kid["id"], 20 * 60, 0, at=dbm.now() + timedelta(minutes=25))
    s2, why2 = await db.finish_half(vid, kid["id"], 40 * 60, 0, at=dbm.now() + timedelta(minutes=45))
    kid = await db.child(kid["id"])
    check(s1 == 5 and s2 == 0 and why2 == "allaqachon" and kid["stars"] == 5, "yarmi ko'rildi: +5 yulduz, faqat bir marta")

    # 5. Kunlik limit (60 daq): ikkinchi ko'rish -> 80 daq, uchinchisi bloklanadi
    await feed(cbq(PARENT, f"open:{zid}"))
    await feed(cbq(PARENT, f"open:{zid}"))
    check("vaqti tugadi" in last_alert(), "kunlik limit ishladi")

    # 6. Uxlash vaqti
    p = await db.get_parent(111)
    late = datetime(2026, 11, 24, 22, 30)
    ok, reason = await db.check_access(dict(p, daily_limit=0, sleep_on=1), kid, await db.get_content(zid), late)
    check(not ok and "uxlash" in reason.lower(), "22:30 da uxlash vaqti bloklaydi")
    check(dbm.is_sleep_time(datetime(2026, 1, 1, 6, 59).time(), "21:00", "07:00") and
          not dbm.is_sleep_time(datetime(2026, 1, 1, 7, 0).time(), "21:00", "07:00"), "06:59 yopiq, 07:00 ochiq")

    # 7. Ota-ona PIN va panel
    await feed(msg(PARENT, "Ota-ona nazorati"))
    await feed(msg(PARENT, "12a4"))
    check("4 ta raqam" in texts()[-1], "noto'g'ri PIN formati rad etildi")
    await feed(msg(PARENT, "1234"))
    await feed(msg(PARENT, "1234"))
    check((await db.get_parent(111))["pin_hash"] == dbm.hash_pin("1234"), "PIN saqlandi (xesh)")
    await feed(cbq(PARENT, "pm:limit:15"))
    check((await db.get_parent(111))["daily_limit"] == 75, "limit +15 -> 75")
    await feed(cbq(PARENT, "pm:sleeptime"))
    await feed(msg(PARENT, "20:30-06:45"))
    pp = await db.get_parent(111)
    check(pp["sleep_from"] == "20:30" and pp["sleep_to"] == "06:45", "uxlash vaqti o'zgardi 20:30–06:45")
    await feed(cbq(PARENT, "pm:exit"))
    await feed(cbq(PARENT, "pm:limit:15"))
    check("Sessiya tugadi" in last_alert(), "chiqqandan keyin panel yopiq")
    await feed(msg(PARENT, "Ota-ona nazorati"))
    await feed(msg(PARENT, "0000"))
    check("noto'g'ri" in texts()[-1], "xato PIN rad etildi")
    await feed(msg(PARENT, "1234"))
    check("Ota-ona nazorati" in texts()[-1], "to'g'ri PIN bilan panel ochildi")

    # 8. Bloklash
    await feed(cbq(PARENT, f"block:{zid}"))
    await feed(msg(PARENT, "Multfilmlar"))
    check("mos kontent yo'q" in texts()[-1], "yopilgan multfilm ro'yxatdan yo'qoldi")
    await feed(cbq(PARENT, f"unblock:{zid}"))
    check(not await db.blocked_list(111), "ota-ona panelidan qayta ochildi")

    # 9. Ikkinchi bola va almashtirish
    await feed(msg(PARENT, "Bolani almashtirish"))
    await feed(cbq(PARENT, "child:add"))
    await feed(msg(PARENT, "Madina"))
    await feed(msg(PARENT, "01.01.2022"))
    check((await db.active_child(111))["name"] == "Madina", "ikkinchi bola qo'shildi va faol")
    await feed(msg(PARENT, "Multfilmlar"))
    titles = [b.text for row in SENT[-1].reply_markup.inline_keyboard for b in row]
    check(any("Alifbo" in t for t in titles), "Madina (4 yosh) uchun 3–5 yoshlik video ko'rinadi")
    await feed(cbq(PARENT, f"child:{kid['id']}"))
    check((await db.active_child(111))["name"] == "Ali", "Ali ga qaytildi")

    # 10. Yulduz -> kupon -> kassa
    await db.run("UPDATE children SET stars=150 WHERE id=?", kid["id"])
    await feed(cbq(PARENT, "redeem:10:200"))
    check("yetmaydi" in last_alert(), "200 yulduz yetmasa kupon berilmaydi")
    await feed(cbq(PARENT, "redeem:5:100"))
    code = (await db.parent_coupons(111))[0]["code"]
    check((await db.child(kid["id"]))["stars"] == 50 and code.startswith("KIDDY-"), f"5% kupon olindi: {code}")
    await feed(cbq(PARENT, "redeem:50:1"))
    check(len(await db.parent_coupons(111)) == 1, "soxta tarif (50%/1) rad etildi")
    await feed(msg(ADMIN, f"/kupon {code.lower()}"))
    check("to'g'ri" in texts()[-1], "kassada kupon qabul qilindi")
    await feed(msg(ADMIN, f"/kupon {code}"))
    check("allaqachon" in texts()[-1], "kupon ikkinchi marta ishlamaydi")
    n_before = len(SENT)
    await feed(msg(PARENT, f"/kupon {code}"))
    check(not any("Kupon" in t or "kupon" in t for t in texts()[n_before:]), "oddiy foydalanuvchi /kupon ishlata olmaydi")

    # 11. Tanlov
    await feed(msg(PARENT, "Ijod tanlovi"))
    await feed(msg(PARENT, None, photo=[PhotoSize(file_id="PH1", file_unique_id="p1", width=1, height=1)]))
    check(await db.one("SELECT * FROM contest WHERE file_id='PH1'") is not None, "tanlov rasmi saqlandi")
    check(any(type(m).__name__ == "SendPhoto" and m.chat_id == 999 for m in SENT), "rasm adminga yuborildi")

    # 12. Tug'ilgan kun va haftalik hisobot
    today = dbm.now()
    await db.run("UPDATE children SET birth_date=? WHERE name='Madina'", f"2021-{today:%m-%d}")
    orig_hour = config.BIRTHDAY_HOUR
    config.BIRTHDAY_HOUR = 0
    await scheduler.birthdays(bot, db)
    await scheduler.birthdays(bot, db)
    bd = [t for t in texts() if "Tug'ilgan kuning" in t]
    check(len(bd) == 1, "tug'ilgan kun tabrigi bir marta yuborildi")
    config.BIRTHDAY_HOUR = orig_hour
    config.REPORT_WEEKDAY, config.REPORT_HOUR = today.weekday(), 0
    await scheduler.weekly_reports(bot, db)
    await scheduler.weekly_reports(bot, db)
    rep = [t for t in texts() if "Haftalik hisobot" in t]
    check(len(rep) == 1 and "Ali" in rep[0] and "Zumrad" in rep[0], "haftalik hisobot bir marta, to'g'ri ma'lumot")

    # 13. Admin statistika va o'chirish
    await feed(msg(ADMIN, "/stat"))
    check("Bolalar: 2" in texts()[-1], "statistika")
    await feed(msg(ADMIN, f"/del {zid}"))
    await feed(msg(PARENT, "Multfilmlar"))
    check("mos kontent yo'q" in texts()[-1], "o'chirilgan kontent ko'rinmaydi")

    # do'st taklifi botda
    await feed(msg(PARENT, "/taklif"))
    code = db.ref_code(PARENT.id)
    check(f"t.me/kiddytvbot?start={code}" in texts()[-1], "/taklif: shaxsiy havola")
    ali = await db.active_child(PARENT.id)
    s0 = ali["stars"]
    FRIEND = User(id=555, is_bot=False, first_name="Do'st")
    await feed(msg(FRIEND, f"/start {code}"))
    check((await db.get_parent(555))["referred_by"] == PARENT.id, "do'st havola bilan keldi")
    await feed(msg(FRIEND, "Sardor"))
    await feed(msg(FRIEND, "01.02.2020"))
    check((await db.active_child(PARENT.id))["stars"] == s0 + 20 and (await db.active_child(555))["stars"] == 10,
          "do'st bolasini qo'shdi: +20 taklif qilganga, +10 yangi bolaga")
    check(any("+10 yulduz" in t for t in texts()[-4:]), "yangi oilaga bonus xabari")

    # do'kondagi QR botda
    qr = await db.store_qr()
    s1 = (await db.active_child(PARENT.id))["stars"]
    await feed(msg(PARENT, f"/start qr_{qr}"))
    check(any("+15 yulduz" in t for t in texts()[-3:]) and (await db.active_child(PARENT.id))["stars"] == s1 + 15,
          "bot: do'kon QR skanerlandi, +15 yulduz")
    await feed(msg(PARENT, "/dokon"))
    check("Kiddy Toys" in texts()[-1], "/dokon: do'kon ma'lumoti")

    await db.close()
    print("\nHamma testlar o'tdi.")
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
