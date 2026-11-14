import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
DB_PATH = os.getenv("DB_PATH", "expenses.db")
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
}

# ички код -> кўринадиган номи
CATEGORIES = {
    "bozorlik": "Бозорлик",
    "ishchilar": "Ишчилар",
    "ijara": "Ижара",
    "prochee": "Прочее",
}
