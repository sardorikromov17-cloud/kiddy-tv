"""Tanlangan o'zbekcha bolalar kanallaridan kontentni bazaga qo'shish.
Ishga tushirish: python seed_content.py   (qayta ishga tushirsa — faqat yangilari qo'shiladi)
Videolar yuklab olinmaydi: YouTube havolasi, nomi va davomiyligi saqlanadi."""
import asyncio
import re
import sys

from db import DB
from youtube_import import fetch_list

# (kanal, papka nomi, bo'lim, yoshdan, yoshgacha, ko'pi bilan nechta video)
CHANNELS = [
    # Multfilmlar (seriallar)
    ("https://www.youtube.com/@BekvaLola", "Bek va Lola", "cartoon", 2, 7, 80),
    ("https://www.youtube.com/channel/UCb6_tVrSpOGxG7on1e4gBzw", "Pomidor Do'ppi", "cartoon", 3, 10, 80),
    ("https://www.youtube.com/channel/UCm83I2CT3OYddr6snvQ8fhg", "Hanifa", "cartoon", 3, 8, 50),
    ("https://www.youtube.com/channel/UCQaFTylY4x5TR8ItU3lR3PA", "Dono va Momomo", "cartoon", 2, 6, 50),
    ("https://www.youtube.com/channel/UCTKIXsv9PijMNmUZ8iPC7Lg", "Yashil makon", "cartoon", 3, 9, 40),
    # Ertaklar
    ("https://www.youtube.com/channel/UCQDYd3ZqCZ7CVhhX02uTWkw", "Aqlvoy ertaklari", "audio", 3, 10, 80),
    ("https://www.youtube.com/channel/UCsgL4Kin_ClWZwmKPPevNkA", "Shirintoy ertaklari", "audio", 3, 9, 60),
    ("https://www.youtube.com/channel/UCNQpE5HXf-c3TqGR9n3ImHA", "Lulla — uxlash oldidan", "audio", 2, 8, 60),
    ("https://www.youtube.com/channel/UCUg4x_rlg5YX_2CETl4v5FQ", "Bir bor ekan", "audio", 3, 9, 40),
    ("https://www.youtube.com/channel/UCQs7_uXc7tO6mH0iIdiGFhQ", "Mitti mo'jiza", "audio", 3, 9, 40),
    # Qo'shiqlar
    ("https://www.youtube.com/channel/UC5O6UBf8OC0vEwCV0uwDxoQ", "Donocha", "music", 2, 8, 60),
    ("https://www.youtube.com/channel/UCDEqUZkXSK_Mj5DlzfAvK5A", "Navo bolalar qo'shiqlari", "music", 1, 7, 60),
    ("https://www.youtube.com/channel/UCkfLMWYx2kpgqlH-VHN1jfg", "O'zbek bolalar qo'shiqlari", "music", 1, 6, 60),
    ("https://www.youtube.com/channel/UCBgOpTP4xT8oijjKRqRRnZA", "PeekaBoo qo'shiqlari", "music", 1, 5, 60),
    ("https://www.youtube.com/channel/UCJlgbSin_UacAnOXuRNw69Q", "Kids TV qo'shiqlari", "music", 1, 5, 40),
    # Ta'limiy videolar
    ("https://www.youtube.com/channel/UCS0Tfvj0IFw0ShsWBUParbA", "Yusuf bilan o'rganamiz", "video", 3, 7, 50),
    ("https://www.youtube.com/channel/UC59AwMVrv8sYdutz8XCXl5A", "Dono TV — o'rganamiz", "video", 2, 6, 60),
    ("https://www.youtube.com/channel/UCGyV-Z0arrWwrD3HfwYYNvA", "Momiq va do'stlari", "video", 1, 5, 40),
]
# Islom.uz (O'zbekiston musulmonlari idorasi) rasmiy kanalidagi multfilm pleylistlari
PL = "https://www.youtube.com/playlist?list="
ISLAMIC = [
    (PL + "PLys356tU5j5QG5CAQT7_HJ_B8V3wpgEQb", "Allohning habibi Muhammad (1-fasl)", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5SSwpHO3p-rnFk9Q3x1R1nn", "Allohning habibi Muhammad (2-fasl)", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5SfVim_BxnblS6LlSLq9csQ", "Allohning habibi Muhammad (3-fasl)", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5R4f29lSEBX8DcgiulE4Rsl", "Yunus alayhissalom qissasi", "islamic", 5, 14, 60),
    (PL + "PLys356tU5j5TIafslEfY6z2qP3t64lESJ", "Islom qissalari", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5Tws9ExdY7zWS0KMB4rhxZJ", "Imom al-Buxoriy", "islamic", 5, 14, 60),
    (PL + "PLys356tU5j5QNH6dPE0PLANEPLK_iQ_Ok", "Qur'onda nomi kelgan jonzotlar", "islamic", 5, 14, 60),
    (PL + "PLys356tU5j5QchO_1AxfgGyLyPkJZMQna", "Qur'onda kelgan insonlar qissasi", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5RgNojOpMdOtFQbPDeIkBRA", "Qur'onda zikri kelgan ajoyibotlar", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5RowW8-r4PDJhigkPTjeYI_", "Qur'ondagi oyat-belgilar qissalari", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5SOA0BeHOmY4MWCM9YiKu6M", "Qur'onda zikri kelgan ayollar qissasi", "islamic", 6, 14, 60),
    (PL + "PLys356tU5j5QkpZjE8cI8UP4SsYYCX668", "Tobeinlar hayotidan qissalar", "islamic", 7, 14, 60),
    (PL + "PLys356tU5j5S7uvHRVmrr5YExYqAMltVE", "Payg'ambarlar qissasi: Ibrohim", "islamic", 5, 14, 60),
]
SKIP = re.compile(r"tizer|teaser|trailer|treyler|#shorts|anons|анонс|tez kunda|тез кунда|премьер|reklama", re.I)


async def main(only=None, lists=None):
    db = DB()
    await db.connect()
    total = 0
    for url, folder, kind, a, b, limit in (lists or CHANNELS):
        if only and only.lower() not in folder.lower():
            continue
        try:
            data = await fetch_list(url)
        except ValueError as e:
            print(f"[XATO] {folder}: {e}")
            continue
        have = await db.existing_youtube_ids()
        row = await db.one("SELECT COALESCE(MAX(episode),0) m FROM content WHERE series=?", folder)
        ep = row["m"]
        items = [i for i in data["items"] if not SKIP.search(i["title"] or "")]
        items = items[-limit:]  # eng yangi N ta (ro'yxat eskidan yangiga)
        if kind == "islamic":  # multseriallarda 2 daqiqadan qisqasi — e'lon/anons
            items = [i for i in items if (i["minutes"] or 0) >= 3]
        added = 0
        for it in items:
            if it["id"] in have:
                continue
            minutes = it["minutes"] or 5
            if minutes > 120:  # juda uzun jamlanmalar bolalar vaqti uchun mos emas
                continue
            ep += 1
            await db.add_content(kind, it["title"] or f"{folder} {ep}", "youtube",
                                 f"https://www.youtube.com/watch?v={it['id']}", None, a, b, minutes, folder, ep)
            added += 1
        total += added
        print(f"[OK] {folder}: {added} ta yangi (kanalda {len(data['items'])} ta)")
    await db.close()
    print(f"\nJami qo'shildi: {total} ta")
    return total


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "islom":
        asyncio.run(main(lists=ISLAMIC))
    else:
        asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
