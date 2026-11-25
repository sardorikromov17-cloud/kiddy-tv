"""YouTube import va seriallar sinovi (YouTube'siz). Ishga tushirish: python -m tests.test_import"""
import asyncio
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = "/tmp/kiddy_import_test.db"
os.environ["PANEL_SECRET"] = "x"
if os.path.exists("/tmp/kiddy_import_test.db"):
    os.remove("/tmp/kiddy_import_test.db")

import httpx  # noqa: E402

import admin_panel.app as panel  # noqa: E402
import db as dbm  # noqa: E402
import youtube_import  # noqa: E402
from miniapp.api import create_miniapp  # noqa: E402
from tests.test_miniapp import init_data  # noqa: E402


def check(cond, label, extra=""):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        print("    ", str(extra)[:600])
        os._exit(1)


class FakeYDL:
    last_url = None

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=False):
        FakeYDL.last_url = url
        return {"title": "Bek va Lola - Videos", "entries": [
            {"id": "AAAAAAAAAA3", "title": "3-qism Mevalar", "duration": 300},
            {"id": "AAAAAAAAAA2", "title": "2-qism Top-toza", "duration": 250},
            {"_type": "playlist", "id": "PLxyz", "title": "Shorts"},
            {"id": "AAAAAAAAAA1", "title": "1-qism Hafta kunlari", "duration": None},
        ]}


async def main():
    # yt-dlp natijasini o'qish
    import yt_dlp
    yt_dlp.YoutubeDL = FakeYDL
    d = await youtube_import.fetch_list("https://www.youtube.com/@BekvaLola")
    check(FakeYDL.last_url.endswith("/@BekvaLola/videos"), "kanal havolasi -> /videos")
    check([i["id"] for i in d["items"]] == ["AAAAAAAAAA1", "AAAAAAAAAA2", "AAAAAAAAAA3"],
          "kanal: eng eskisi 1-qism, pleylist bo'limi tashlab ketildi")
    check(d["title"] == "Bek va Lola" and d["items"][0]["minutes"] is None and d["items"][1]["minutes"] == 4,
          "nom va davomiylik")
    try:
        await youtube_import.fetch_list("https://vimeo.com/123")
        check(False, "YouTube bo'lmagan havola rad etilishi kerak")
    except ValueError:
        check(True, "YouTube bo'lmagan havola rad etildi")

    # panel orqali import
    db = dbm.DB(os.environ["DB_PATH"])
    await db.connect()
    await db.add_staff("admin", "secret1", "admin")
    await db.add_content("cartoon", "Eski", "youtube", "https://youtu.be/AAAAAAAAAA2", None, 2, 7, 4)
    app = panel.create_app(db, None)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", follow_redirects=True)
    await c.post("/login", data={"username": "admin", "password": "secret1"})
    r = await c.get("/import?url=https://www.youtube.com/@BekvaLola&kind=cartoon&a=2&b=7")
    tok = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    check("Tavsiya etilgan" in html.unescape(r.text) and "Bek va Lola" in r.text, "import sahifasi va tavsiyalar")
    r = await c.post("/import/preview", data={"token": tok, "url": "https://www.youtube.com/@BekvaLola",
                                              "kind": "cartoon", "a": 2, "b": 7})
    t = html.unescape(r.text)
    check("3 ta video · 2 tasi yangi" in t, "ko'rinish: 3 ta, 1 tasi allaqachon bor", t[-800:])
    key = re.search(r'name="key" value="([^"]+)"', r.text).group(1)
    r = await c.post("/import/save", data={"token": tok, "key": key, "kind": "cartoon", "a": 2, "b": 7,
                                           "minutes": 6, "series": "Bek va Lola",
                                           "v": ["AAAAAAAAAA1", "AAAAAAAAAA2", "AAAAAAAAAA3"]})
    check("2 ta video qo'shildi" in html.unescape(r.text), "2 ta yangi qo'shildi, borini takrorlamadi")
    rows = await db.all("SELECT * FROM content WHERE series='Bek va Lola' ORDER BY episode")
    check([(x["episode"], x["minutes"]) for x in rows] == [(1, 6), (2, 5)], "qism raqamlari va davomiylik",
          [tuple(x) for x in rows])
    r = await c.post("/import/save", data={"token": tok, "key": key, "kind": "cartoon", "a": 2, "b": 7, "v": []})
    check("eskirgan" in html.unescape(r.text), "bir ko'rinishni ikki marta saqlab bo'lmaydi")

    # Mini App: keyingi qism
    await db.ensure_parent(111, "A")
    await db.add_child(111, "Ali", "2021-01-01")
    await db.set_parent(111, sleep_on=0)
    m = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_miniapp(db, None, "123456:TEST-token")),
                          base_url="http://t")
    H = {"X-Init-Data": init_data(111)}
    lst = (await m.get("/api/content?kind=cartoon", headers=H)).json()["items"]
    check(lst[0]["t"] == "series" and lst[0]["series"] == "Bek va Lola" and lst[0]["count"] == 2
          and lst[1]["t"] == "item" and lst[1]["title"] == "Eski", "ilovada serial bitta papka + alohida video", lst)
    eps = (await m.get("/api/series?name=Bek va Lola", headers=H)).json()["items"]
    check([i["title"] for i in eps] == ["1-qism Hafta kunlari", "3-qism Mevalar"], "papka ichida qismlar tartib bilan")
    r = (await m.post("/api/open", headers=H, json={"id": rows[0]["id"]})).json()
    check(r["next"] and r["next"]["id"] == rows[1]["id"] and r["series"]["episode"] == 1, "1-qism -> keyingi qism bor")
    r = (await m.post("/api/open", headers=H, json={"id": rows[1]["id"]})).json()
    check(r["next"] is None, "oxirgi qismda 'keyingi' yo'q")
    await db.close()
    print("\nImport testlari o'tdi.")
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
