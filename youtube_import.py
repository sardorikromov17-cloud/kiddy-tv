"""YouTube video / pleylist / kanal ro'yxatini olish (API kalitsiz, yt-dlp orqali).
Videolarning o'zi yuklab olinmaydi — faqat nomi, ID va davomiyligi."""
import asyncio
import re

MAX_ITEMS = 300
HANDLE_RE = re.compile(r"^https?://(www\.|m\.)?youtube\.com/(@[\w.-]+|c/[\w.-]+|channel/[\w-]+|user/[\w.-]+)/?$")


def _normalize(url: str) -> str:
    url = url.strip()
    if HANDLE_RE.match(url):  # kanalning bosh sahifasi -> videolar bo'limi
        url = url.rstrip("/") + "/videos"
    return url


_CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h"}


def cyr_to_lat(t: str) -> str:
    """O'zbek kirill -> lotin (nomlar uchun yetarli darajada)."""
    out = []
    for i, ch in enumerate(t):
        low = ch.lower()
        if low not in _CYR:
            out.append(ch)
            continue
        r = _CYR[low]
        if low == "е" and (i == 0 or not t[i - 1].isalpha()):
            r = "ye"  # so'z boshida: Ёқ/Е -> ye
        if ch.isupper() and r:
            nxt = t[i + 1] if i + 1 < len(t) else ""
            r = r.upper() if (nxt.isupper()) else r[0].upper() + r[1:]
        out.append(r)
    return "".join(out)


def clean_title(t: str) -> str:
    """'Bek va Lola - Shakllar (multfilm) | Бек ва Лола ... #kids' -> 'Bek va Lola - Shakllar'"""
    t = (t or "").split(" | ")[0]
    if re.search(r"[а-яёўқғҳА-ЯЁЎҚҒҲ]", t):
        t = cyr_to_lat(t)
    t = re.sub(r"#\S+", "", t)
    t = re.sub(r"\((?:[^)]*(?:multfilm|o'zbek tilida|o'zbekcha|bolalar uchun|cartoon)[^)]*)\)", "", t, flags=re.I)
    t = t.replace('"', "").replace("«", "").replace("»", "")
    return re.sub(r"\s{2,}", " ", t).strip(" -|")[:80]


def _fetch(url: str) -> dict:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
            "playlistend": MAX_ITEMS, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_normalize(url), download=False)
    entries = info.get("entries")
    items = []
    if entries is None:  # bitta video
        entries = [info]
    for e in entries:
        if not e:
            continue
        if e.get("_type") == "playlist" or (e.get("ie_key") or "").lower().startswith("youtubetab"):
            continue  # kanal ichidagi pleylistlar/shorts bo'limlari
        vid = e.get("id")
        if not vid or len(vid) != 11:
            continue
        items.append({"id": vid, "title": clean_title(e.get("title") or ""),
                      "minutes": max(1, round((e.get("duration") or 0) / 60)) if e.get("duration") else None})
    if _normalize(url).endswith("/videos"):
        items.reverse()  # kanal: eng eskisi 1-qism bo'lsin
    return {"title": (info.get("title") or "").replace(" - Videos", "").strip()[:80], "items": items}


async def fetch_list(url: str) -> dict:
    """{'title': pleylist nomi, 'items': [{'id','title','minutes'}]} — xato bo'lsa ValueError."""
    if not re.match(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", url.strip()):
        raise ValueError("Faqat YouTube havolasi (youtube.com yoki youtu.be).")
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch, url), timeout=90)
    except asyncio.TimeoutError:
        raise ValueError("YouTube javob bermadi (90 soniya). Internetni tekshiring.")
    except ImportError:
        raise ValueError("yt-dlp o'rnatilmagan: pip install yt-dlp")
    except Exception as e:
        raise ValueError(f"Ro'yxatni olib bo'lmadi: {str(e).splitlines()[0][:200]}")
