"""Kiddy TV bot sozlamalari (.env faylidan o'qiladi)."""
import os
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
WEBSITE_URL = os.getenv("WEBSITE_URL", "https://kiddy-tv.uz")  # o'yinlar shu saytda ochiladi
DB_PATH = os.getenv("DB_PATH", "kiddy_tv.db")
try:
    TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Tashkent"))
except Exception:  # Windows'da tzdata bo'lmasa — Toshkent vaqti (UTC+5)
    TZ = timezone(timedelta(hours=5), "Asia/Tashkent")

# Har bir ko'rilgan video / tinglangan ertak uchun yulduz
STARS_PER_VIEW = int(os.getenv("STARS_PER_VIEW", "5"))

# Yulduzni chegirmaga almashtirish: (foiz, kerakli yulduz)
REWARD_TIERS = [(5, 100), (10, 200), (15, 400)]

# Tug'ilgan kun kuponi (foiz) va kupon amal qilish muddati (kun)
BIRTHDAY_PERCENT = int(os.getenv("BIRTHDAY_PERCENT", "10"))
COUPON_DAYS = 30

# Haftalik hisobot: yakshanba (6), soat 19:00
REPORT_WEEKDAY = 6
REPORT_HOUR = 19
# Tug'ilgan kun tabrigi soati
BIRTHDAY_HOUR = 9

# Bo'limlar: kalit -> (tugma matni, emoji emas, oddiy nom)
KINDS = {
    "cartoon": "Multfilmlar",
    "film": "Kinolar",
    "video": "Videolar",
    "audio": "Ertaklar",
    "music": "Qo'shiqlar",
    "islamic": "Islomiy",
    "game": "O'yinlar",
}
