# Kiddy TV — Telegram bot va admin panel

Bolalar uchun bepul va reklamasiz multfilm, kino, video, ertak va o'yinlar boti
hamda do'kon xodimlari uchun boshqaruv paneli. Kiddy Toys Qo'qon loyihasi.
Python + aiogram 3 + FastAPI + SQLite. Bepul, kompyuterda ishlaydi.

## Ishga tushirish (bot + panel birga)

1. **Python 3.11 yoki yangisi:** https://www.python.org/downloads/
   (Windows'da «Add Python to PATH» belgisini qo'ying.)
2. **Bot tokeni:** Telegram'da @BotFather → `/newbot` → token (`123456:ABC...`).
   Bot rasmi: `/setuserpic` → `assets/logo.png`.
3. **Telegram ID:** @userinfobot → `Id: 123456789`.
4. Papkada terminal (cmd) oching:
   ```
   pip install -r requirements.txt
   ```
5. `.env.example` dan nusxa olib nomini `.env` qiling, `BOT_TOKEN` va `ADMIN_IDS` ni yozing.
6. Ishga tushiring:
   ```
   python run.py
   ```
7. Brauzerda **http://localhost:8080** ni oching → birinchi marta o'zingiz uchun
   admin login va parol yaratasiz.

`python bot.py` — faqat bot (panelsiz) ham ishlaydi.

## Admin panel bo'limlari

| Bo'lim | Nima qiladi |
|---|---|
| **Bosh sahifa** | Oilalar, bolalar, bugungi ko'rishlar, kuponlar; 14 kunlik grafik; hafta kontenti va hafta yulduzlari; tezkor kupon tekshirish |
| **Kontent** | Video joylash: YouTube havola yoki video/audio fayl yuklash (50 MB gacha). Bo'lim, yosh, davomiylik. Tahrirlash, yashirish/ochish, qidiruv, har birining ko'rish va «Yoqdi» soni |
| **Kuponlar** | Kassada kodni tekshirish → «Ishlatildi» (ota-onaga xabar boradi). Ro'yxat: faol / ishlatilgan / muddati o'tgan, qidiruv, kim ishlatgani |
| **Reytinglar** | Eng faol bolalar (yulduz), eng ko'p ko'rilgan kontent, bolalarga eng yoqqan kontent — 7 kun / 30 kun / hammasi |
| **Oilalar** | Ota-onalar, bolalar, yoshi, yulduzi, sozlamalari; istalgan bolaga qo'lda % kupon berish |
| **Ijod tanlovi** | Bolalar yuborgan rasmlar; «G'olib» → avtomatik kupon va tabrik xabari |
| **Xabar yuborish** | Barcha ota-onalarga xabar (yangi multfilm, aksiya) |
| **Sozlamalar** | Bir ko'rish uchun yulduz, chegirma tariflari (masalan 5% = 100 yulduz), kupon muddati, tug'ilgan kun va tanlov kuponi foizi, tanlov mavzusi, yangi oilalar uchun kunlik vaqt |
| **Xodimlar** | Xodim qo'shish: **Admin** (hamma narsa) yoki **Kassir** (faqat kuponlar). Parol almashtirish, o'chirish |

Paneldagi har bir o'zgarish botda **darhol** ishlaydi (bitta baza).

## Kassirlar boshqa kompyuterdan kirishi

Do'kondagi boshqa kompyuter yoki telefon panelga kirishi uchun `.env` da:
```
PANEL_HOST=0.0.0.0
```
Keyin ular brauzerda `http://<asosiy kompyuter IP>:8080` ni ochadi
(IP: Windows'da `ipconfig` → IPv4). Bu faqat bitta Wi-Fi/tarmoq ichida ishlaydi.
4 ta filial bir panelga kirishi uchun keyinroq server (VPS) olamiz.

## Bot imkoniyatlari (qisqacha)

- **Bolalar:** yoshiga mos Multfilmlar / Kinolar / Videolar / O'yinlar / Ertaklar;
  har bir ko'rish uchun yulduz; «Yoqdi» tugmasi; yulduzni chegirmaga almashtirish; ijod tanlovi.
- **Ota-ona nazorati (PIN):** kunlik vaqt, uxlash vaqti, kontentni yopish,
  bugungi va haftalik hisobot, kuponlar, bolalar.
- **Avtomatik:** har yakshanba 19:00 hisobot; tug'ilgan kunda 09:00 tabrik va kupon.
- **Botdagi admin buyruqlari** (panelsiz ham ishlaydi): `/add`, `/list`, `/del`, `/kupon`, `/stat`, `/xabar`.

## Muhim

- Video fayllar Telegram serverida saqlanadi (`STORAGE_CHAT_ID` chatiga yuboriladi) —
  kompyuter diskini to'ldirmaydi. Bitta fayl 50 MB gacha; kattasini YouTube'ga joylang.
- Faqat ruxsat etilgan kontent qo'ying: o'zingiz suratga olgan videolar, xalq ertaklari,
  rasmiy YouTube kanallar havolalari. Boshqalarning multfilmini ruxsatsiz yuklash mualliflik huquqini buzadi.
- Ko'rish vaqti video davomiyligi bo'yicha hisoblanadi (YouTube'da oxirigacha ko'rilganini bot bila olmaydi).
- `kiddy_tv.db` — butun baza. Haftada bir marta nusxasini saqlab qo'ying.
- `.env` va `.panel_secret` fayllarini hech kimga bermang.

## Sinov

```
python -m tests.test_flow    # bot: 35 ta tekshiruv
python -m tests.test_panel   # panel: 46 ta tekshiruv
```

## Fayllar

```
run.py              — bot + panel birga
bot.py              — faqat bot
config.py, db.py    — sozlamalar va baza
keyboards.py        — bot tugmalari
handlers/           — bot: user.py, parent.py, admin.py
scheduler.py        — haftalik hisobot, tug'ilgan kun
admin_panel/app.py  — panel
admin_panel/templates/ — panel sahifalari
tests/              — sinovlar
```
