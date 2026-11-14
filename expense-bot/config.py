"""Созламалар. Ҳамма қиймат .env файлидан ўқилади."""
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
# "gemini-flash-latest" — Google ўзи энг янги Flash моделига улаб туради.
# Аниқ версияда қотириш учун AI Studio'даги рўйхатдан номини ёзинг.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
DB_PATH = os.getenv("DB_PATH", "expenses.db")

# Хўжайинлар (2-3 киши). Биринчиси — асосий: заҳира нусха унга юборилади.
OWNER_IDS = _ids("OWNER_IDS")
MAX_OWNERS = int(os.getenv("MAX_OWNERS", "3"))

# Иш куни соат нечада бошланади. Нуқта кечаси 3 да ёпилса, 03:00 даги савдо
# ҳали "кечаги" кунга ёзилади. 5 = эрталаб 05:00 гача олдинги кун ҳисобланади.
DAY_START_HOUR = int(os.getenv("DAY_START_HOUR", "5"))

SALES_REMINDER_TIME = _time("SALES_REMINDER_TIME", "23:30")  # кассирга эслатма
DIGEST_TIME = _time("DIGEST_TIME", "09:00")                  # хўжайинларга кечаги хулоса
BACKUP_WEEKDAY = int(os.getenv("BACKUP_WEEKDAY", "6"))       # 0=душанба … 6=якшанба
BACKUP_TIME = _time("BACKUP_TIME", "10:00")
NOTIFY_OWNERS_ON_SALES = os.getenv("NOTIFY_OWNERS_ON_SALES", "1") == "1"

INVITE_TTL_HOURS = 48

# ички код -> кўринадиган номи
CATEGORIES = {
    "bozorlik": "Бозорлик",
    "ishchilar": "Ишчилар",
    "ijara": "Ижара",
    "prochee": "Прочее",
}


def business_today() -> date:
    """Иш кунини қайтаради (DAY_START_HOUR гача — ҳали кечаги кун)."""
    now = datetime.now(TZ)
    return (now - timedelta(hours=DAY_START_HOUR)).date()


def at(hm: tuple[int, int]) -> time:
    return time(hm[0], hm[1], tzinfo=TZ)
