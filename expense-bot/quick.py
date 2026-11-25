"""Oddiy matnli xarajatlarni Gemini'siz, bir zumda tushunish.

Faqat aniq holatlarni o'zi hal qiladi, masalan:
    "benzin 50000"
    "pomidor 100 ming, bodring 45000"
    "Umid 700 ming oldi"
Bir narsa noaniq bo'lsa (kirill yozuv, "kecha", miqdor "10 kg", noma'lum so'z va h.k.)
None qaytaradi — unda xabar odatdagidek Gemini'ga yuboriladi.
"""
import re

import ai
import db
import reports

# Kategoriyani bilish uchun boshlang'ich lug'at. Bot ishlagan sari bazadagi oldingi
# xarajatlardan ham o'rganadi (bir marta "kolbasa" bozorlik bo'lgan bo'lsa, keyin ham shunday).
KEYWORDS = {
    "bozorlik": """pomidor bodring piyoz kartoshka sabzi karam kapusta qalampir sarimsoq ko'kat ukrop petrushka
        kashnich limon olma banan go'sht gosht mol qo'y tovuq kurinniy kolbasa sosiska pishloq sir sut qaymoq
        tuxum yog' yog moy un guruch makaron non lavash bulochka shakar tuz murch ziravor ketchup mayonez sous
        sardelka fri muz choy kofe ichimlik cola kola pepsi fanta sprite suv salfetka paket stakan idish
        qopqoq trubochka folga plyonka gaz-suv""".split(),
    "ijara": "ijara arenda svet elektr gaz kommunal chiqindi musor internet".split(),
    "prochee": """benzin propan metan yoqilg'i taksi yandex-taksi stoyanka parkovka remont ta'mir usta reklama
        soliq nalog jarima shtraf bank komissiya telefon aloqa dori moyka transport dostavka yo'lkira""".split(),
}
WORD2CAT = {w: c for c, words in KEYWORDS.items() for w in words}

WORKERS_DAILY = {"ishchilar", "ishchi", "ishchilarga", "ishchilar kunligi", "kunlik", "ish haqi",
                 "ishchilar puli", "kunlik pul"}
WORKER_VERBS = ("o'ziga oldi", "oziga oldi", "oldi", "berildi", "berdim", "avans", "oylik")
AMOUNT_RE = re.compile(
    r"^(?P<name>[a-z'ʻ’` \-]+?)\s+(?P<amount>\d[\d\s.,]*(?:\s*(?:ming|mln|million|k))?)"
    r"(?:\s*(?:so'm|som|sum))?(?P<tail>(?:\s+[a-z'ʻ’` ]+)?)$")


def _category_from_history(item: str):
    with db.conn() as c:
        r = c.execute("SELECT category FROM expenses WHERE lower(item)=? AND category!='ishchilar' "
                      "ORDER BY id DESC LIMIT 1", (item.lower(),)).fetchone()
    return r["category"] if r else None


def _one(segment: str, employees: dict):
    m = AMOUNT_RE.match(segment)
    if not m:
        return None
    name = " ".join(m["name"].replace("’", "'").replace("ʻ", "'").split())
    tail = " ".join(m["tail"].split())
    amount = reports.parse_amount(m["amount"])
    if not name or not amount or amount < 100:
        return None
    first = name.split()[0]
    emp = employees.get(name) or employees.get(first)
    if emp:  # "Umid 700 ming oldi" — ishchiga to'lov
        rest = name[len(emp.lower()):].strip() if name.startswith(emp.lower()) else ""
        if (rest and rest not in WORKER_VERBS) or (tail and tail not in WORKER_VERBS):
            return None
        item = "Oylik" if "oylik" in (rest, tail) else "Avans"
        return ai.Expense(category="ishchilar", item=item, amount=amount, person=emp)
    if name in WORKERS_DAILY and not tail:  # "ishchilar 400000" — ishchilarning kunlik puli
        return ai.Expense(category="ishchilar", item="Kunlik ish haqi", amount=amount)
    if tail:  # "benzin 50000 quydim" kabi qo'shimcha so'zlar — Gemini hal qilsin
        return None
    if any(re.search(r"(dim|dik|di|ldi|ydi|ing|man)$", w) for w in name.split()[1:]):
        return None  # "benzin quydim", "pomidor oldim" — fe'l bor, Gemini aniqroq ajratadi
    cat = _category_from_history(name) or WORD2CAT.get(name) or (
        WORD2CAT.get(first) if len(name.split()) <= 2 else None)
    if not cat:
        return None
    return ai.Expense(category=cat, item=name[:1].upper() + name[1:], amount=amount)


def parse(text: str, employee_names: list[str]):
    """Matnni o'zi tushunsa ai.Parsed qaytaradi, aks holda None."""
    raw = text.strip().lower()
    if not raw or len(raw) > 300 or re.search(r"[а-яёўқғҳ]", raw):
        return None  # kirill yoki juda uzun matn — Gemini
    if re.search(r"\b(kecha|oldingi|o'tgan|yandex|kg|kilo|dona|ta|litr|bugun)\b", raw):
        return None  # sana, miqdor, Yandex — Gemini yaxshiroq ajratadi
    employees = {e.lower(): e for e in employee_names}
    parts = [p.strip() for p in re.split(r"[,;\n]+|\s+va\s+", raw) if p.strip()]
    out = []
    for p in parts:
        e = _one(p, employees)
        if e is None:
            return None
        out.append(e)
    return ai.Parsed(transcript=text.strip(), expenses=out) if out else None
