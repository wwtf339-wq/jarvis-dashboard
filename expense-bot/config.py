"""Sozlamalar. Hamma qiymat .env faylidan o'qiladi."""
import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _ids(name: str) -> list[int]:
    raw = os.getenv(name, "").replace(" ", "")
    return [int(x) for x in raw.split(",") if x]


def _time(name: str, default: str) -> tuple[int, int]:
    h, m = os.getenv(name, default).split(":")
    return int(h), int(m)


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# Asosiy model. AI Studio'dagi ro'yxatdan istalgan Flash modelini yozish mumkin.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Bepul kalit: asosiy model band bo'lsa (503/429) yoki javob bermasa, navbat bilan shular sinab ko'riladi.
# Faqat tez modellar qoldirilgan (3.8/3.7/3.5-flash/2.5-flash sekin yoki tez-tez band bo'ldi).
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS",
    "gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-3.6-flash").split(",") if m.strip()]

# Pullik kalit (ixtiyoriy). Bepul modellarning hammasi limitga tushsa yoki band bo'lsa,
# bot avtomatik shu kalit bilan ishlaydi. Bo'sh qolsa — faqat bepul rejim.
GEMINI_PAID_API_KEY = os.getenv("GEMINI_PAID_API_KEY", "").strip()
GEMINI_PAID_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_PAID_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
DB_PATH = os.getenv("DB_PATH", "expenses.db")

# Xo'jayinlar (2-3 kishi). Birinchisi — asosiy: zahira nusxa unga yuboriladi.
OWNER_IDS = _ids("OWNER_IDS")
MAX_OWNERS = int(os.getenv("MAX_OWNERS", "3"))

# Ish kuni soat nechada boshlanadi. Nuqta kechasi 3 da yopilsa, 03:00 dagi savdo
# hali "kechagi" kunga yoziladi. 5 = ertalab 05:00 gacha oldingi kun hisoblanadi.
DAY_START_HOUR = int(os.getenv("DAY_START_HOUR", "5"))

SALES_REMINDER_TIME = _time("SALES_REMINDER_TIME", "23:30")  # kassirga eslatma
DIGEST_TIME = _time("DIGEST_TIME", "09:00")                  # xo'jayinlarga kechagi xulosa
BACKUP_WEEKDAY = int(os.getenv("BACKUP_WEEKDAY", "6"))       # 0=dushanba … 6=yakshanba
BACKUP_TIME = _time("BACKUP_TIME", "10:00")
NOTIFY_OWNERS_ON_SALES = os.getenv("NOTIFY_OWNERS_ON_SALES", "1") == "1"
# Kuniga nechta smena (kirim smena bo'yicha yoziladi)
SHIFTS = max(1, int(os.getenv("SHIFTS", "2")))

INVITE_TTL_HOURS = 48

# ichki kod -> ko'rinadigan nomi
CATEGORIES = {
    "bozorlik": "Bozorlik",
    "ishchilar": "Ishchilar",
    "ijara": "Ijara",
    "prochee": "Prochee",
}


def business_today() -> date:
    """Ish kunini qaytaradi (DAY_START_HOUR gacha — hali kechagi kun)."""
    now = datetime.now(TZ)
    return (now - timedelta(hours=DAY_START_HOUR)).date()


def at(hm: tuple[int, int]) -> time:
    return time(hm[0], hm[1], tzinfo=TZ)
