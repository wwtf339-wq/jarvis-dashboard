"""Hisobotlar: Telegram uchun matn (telefon ekraniga mos) va Excel fayl."""
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import db
from config import CATEGORIES, business_today

MONTHS = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
          "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]
W = 30  # <pre> blok kengligi (telefonda sinmasligi uchun)


def som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def k(n: int) -> str:
    """Qisqa ko'rinish: 1 250 000 -> 1 250k"""
    return f"{som(round(n / 1000))}k" if n else "-"


def line(label: str, amount: int) -> str:
    val = som(amount)
    return f"{label[:W - len(val) - 1]:<{W - len(val)}}{val}"


def pre(lines: list[str]) -> str:
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


def parse_amount(text: str) -> int | None:
    """'2 500 000', '2.500.000', '2,5 mln', '2500k', '800 ming' (lotin yoki kirill) -> butun so'm."""
    t = text.lower()
    for w in ("so'm", "so‘m", "som", "sum", "сўм", "сум"):
        t = t.replace(w, "")
    t = t.strip()
    mult = 1
    for word, m in (("million", 1_000_000), ("миллион", 1_000_000), ("mln", 1_000_000), ("млн", 1_000_000),
                    ("ming", 1000), ("минг", 1000), ("k", 1000), ("к", 1000)):
        if t.endswith(word):
            mult, t = m, t[: -len(word)].strip()
            break
    t = t.replace(" ", "")
    if mult > 1:
        t = t.replace(",", ".")
        try:
            return int(round(float(t) * mult))
        except ValueError:
            return None
    t = t.replace(".", "").replace(",", "")
    return int(t) if re.fullmatch(r"\d+", t) else None


# ---------- davrlar ----------

def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def period_range(kind: str, ref: date) -> tuple[date, date, str]:
    if kind == "bugun":
        return ref, ref, f"Bugun, {ref:%d.%m.%Y}"
    if kind == "kecha":
        d = ref - timedelta(days=1)
        return d, d, f"Kecha, {d:%d.%m.%Y}"
    if kind == "hafta":
        s = ref - timedelta(days=ref.weekday())
        e = s + timedelta(days=6)
        return s, e, f"Hafta {s:%d.%m} – {e:%d.%m.%Y}"
    if kind == "oy":
        s, e = month_range(ref.year, ref.month)
        return s, e, f"{MONTHS[ref.month]} {ref.year}"
    raise ValueError(kind)


# ---------- ma'lumot yig'ish ----------

@dataclass
class Data:
    start: date
    end: date
    point_id: int | None
    sales: list
    expenses: list
    yandex: list

    @property
    def cash(self): return sum(r["cash"] for r in self.sales)
    @property
    def card(self): return sum(r["card"] for r in self.sales)
    @property
    def ya(self): return sum(r["amount"] for r in self.yandex)
    @property
    def income(self): return self.cash + self.card + self.ya
    @property
    def spent(self): return sum(r["amount"] for r in self.expenses)

    def by_cat(self, rows=None):
        t = defaultdict(int)
        for r in (self.expenses if rows is None else rows):
            t[r["category"]] += r["amount"]
        return t


def collect(start: date, end: date, point_id=None) -> Data:
    return Data(start, end, point_id,
                db.sales_between(start, end, point_id),
                db.expenses_between(start, end, point_id),
                db.yandex_between(start, end, point_id))


# ---------- matn bloklari ----------

def pnl_block(d: Data) -> str:
    cats = d.by_cat()
    lines = ["TUSHUM",
             line("  Naqd", d.cash), line("  Karta", d.card), line("  Yandex", d.ya),
             line("  Jami tushum", d.income), "",
             "XARAJAT"]
    for key, name in CATEGORIES.items():
        lines.append(line(f"  {name}", cats.get(key, 0)))
    lines += [line("  Jami xarajat", d.spent), "-" * W]
    profit = d.income - d.spent
    lines.append(line("FOYDA" if profit >= 0 else "ZARAR", profit))
    return pre(lines)


def per_point_block(d: Data) -> str | None:
    pts = db.points()
    if d.point_id is not None or len(pts) < 2:
        return None
    lines = []
    for p in pts:
        inc = sum(r["cash"] + r["card"] for r in d.sales if r["point_id"] == p["id"]) \
            + sum(r["amount"] for r in d.yandex if r["point_id"] == p["id"])
        exp = sum(r["amount"] for r in d.expenses if r["point_id"] == p["id"])
        lines += [p["name"][:W], line("  tushum", inc), line("  xarajat", exp), line("  farq", inc - exp)]
    general = sum(r["amount"] for r in d.expenses if r["point_id"] is None)
    general_ya = sum(r["amount"] for r in d.yandex if r["point_id"] is None)
    if general or general_ya:
        lines += ["Umumiy (tochkaga bo'linmagan)"]
        if general_ya:
            lines.append(line("  Yandex", general_ya))
        if general:
            lines.append(line("  xarajat", general))
    return "<b>Tochkalar kesimida</b>\n" + pre(lines)


def missing_sales(d: Data) -> list[str]:
    """Kassir savdo kiritmagan kunlar (bugungi ochiq kun hisobga olinmaydi)."""
    last = min(d.end, business_today() - timedelta(days=1))
    have = {(r["point_id"], r["day"]) for r in d.sales}
    pts = db.points() if d.point_id is None else [p for p in db.points() if p["id"] == d.point_id]
    out = []
    for p in pts:
        first = db.first_sale_day(p["id"])
        if not first:
            continue
        day, miss = max(d.start, first), []
        while day <= last:
            if (p["id"], day.isoformat()) not in have:
                miss.append(f"{day:%d.%m}")
            day += timedelta(days=1)
        if miss:
            out.append(f"⚠️ {escape(p['name'])}: {', '.join(miss)} — savdo kiritilmagan")
    return out


def daily_block(d: Data) -> str:
    inc, exp = defaultdict(int), defaultdict(int)
    for r in d.sales:
        inc[r["day"]] += r["cash"] + r["card"]
    for r in d.yandex:
        inc[r["day"]] += r["amount"]
    for r in d.expenses:
        exp[r["day"]] += r["amount"]
    days = sorted(set(inc) | set(exp))
    lines = [f"{'Sana':<6}{'Tushum':>8}{'Xarajat':>8}{'Farq':>8}"]
    for day in days:
        diff = inc[day] - exp[day]
        sign = "+" if diff > 0 else ""
        lines.append(f"{day[8:]}.{day[5:7]} {k(inc[day]):>7} {k(exp[day]):>7} {sign + k(diff) if diff else '0':>7}")
    return pre(lines) + "\n<i>k = ming so'm</i>"


def detail_block(d: Data) -> str:
    """Kunlik batafsil: har bir tochka savdosi va har bir xarajat qatori."""
    parts = []
    if d.sales or d.yandex:
        lines = []
        for r in d.sales:
            lines += [f"{db.point_name(r['point_id'])}, {r['shift']}-smena"[:W],
                      line("  naqd", r["cash"]), line("  karta", r["card"])]
        for r in d.yandex:
            lines.append(line(f"Yandex ({db.point_name(r['point_id'])})", r["amount"]))
        parts.append("<b>Tushum</b>\n" + pre(lines))
    names = db.user_names()
    for key, name in CATEGORIES.items():
        rows = [r for r in d.expenses if r["category"] == key]
        if not rows:
            continue
        lines = []
        for r in rows:
            label = f"{r['person']} ({r['item']})" if r["person"] else r["item"]
            if r["quantity"]:
                label += f" {r['quantity']}"
            lines.append(line(f"#{r['id']} {label}", r["amount"]))
            who = names.get(r["created_by"])
            if who and who[1] == "cashier":
                lines.append(f"   ✍ {who[0]}"[:W])
        lines.append(line("Jami", sum(r["amount"] for r in rows)))
        parts.append(f"<b>{name}</b>\n" + pre(lines))
    return "\n".join(parts)


def employee_payments(start: date, end: date) -> list[dict]:
    """Har bir xodim: oyligi, shu davrda olgani, qoldiq."""
    paid_by_id, paid_by_name = defaultdict(int), defaultdict(int)
    for r in db.expenses_between(start, end):
        if r["category"] != "ishchilar":
            continue
        if r["employee_id"]:
            paid_by_id[r["employee_id"]] += r["amount"]
        else:
            paid_by_name[(r["person"] or "—").strip().lower()] += r["amount"]
    out = []
    for e in db.employees(active_only=False):
        if not e["active"] and (not e["fired_on"] or e["fired_on"] < start.isoformat()):
            continue
        paid = paid_by_id.pop(e["id"], 0) + paid_by_name.pop(e["name"].lower(), 0)
        out.append(dict(name=e["name"], point=db.point_name(e["point_id"]), salary=e["salary"],
                        paid=paid, left=e["salary"] - paid, active=bool(e["active"])))
    for name, paid in paid_by_name.items():  # ro'yxatda yo'q ismlar
        out.append(dict(name=name.title(), point="?", salary=0, paid=paid, left=-paid, active=True))
    return out


def salary_block(start: date, end: date) -> str | None:
    rows = employee_payments(start, end)
    if not rows:
        return None
    lines = []
    for r in rows:
        tag = " (bo'shagan)" if not r["active"] else (" (ro'yxatda yo'q)" if r["point"] == "?" else "")
        lines.append((r["name"] + tag)[:W])
        if r["salary"]:
            lines.append(f"  {k(r['salary'])} oylik, {k(r['paid'])} oldi")
        else:
            lines.append(f"  oylik yo'q, {k(r['paid'])} oldi" if r["paid"] else "  oylik yo'q, olmagan")
        if r["salary"]:
            lines.append(f"  qoldi: {k(r['left'])}" if r["left"] >= 0 else f"  ortiqcha: {k(-r['left'])}")
    return "<b>Ishchilar oyligi</b>\n" + pre(lines)


def owner_report(kind: str, ref: date, point_id=None) -> list[str]:
    start, end, title = period_range(kind, ref)
    d = collect(start, end, point_id)
    scope = "hamma tochkalar" if point_id is None else db.point_name(point_id)
    out = [f"📊 <b>{escape(title)}</b> — {escape(scope)}"]
    if not (d.sales or d.expenses or d.yandex):
        out.append("Ma'lumot yo'q.")
        return out
    out.append(pnl_block(d))
    if kind in ("bugun", "kecha"):
        out.append(detail_block(d))
    else:
        pp = per_point_block(d)
        if pp:
            out.append(pp)
        out.append("<b>Kunma-kun</b>\n" + daily_block(d))
        if kind == "oy" and point_id is None:
            sb = salary_block(start, end)
            if sb:
                out.append(sb)
    out += missing_sales(d)
    return out


def digest(day: date) -> str:
    """Ertalabki xulosa: kechagi kun + oy boshidan buyon."""
    d = collect(day, day)
    ms, me = month_range(day.year, day.month)
    m = collect(ms, day)
    lines = [f"☀️ <b>Kechagi kun, {day:%d.%m}</b>",
             pre([line("Tushum", d.income), line("Xarajat", d.spent), line("Farq", d.income - d.spent)]),
             f"<b>{MONTHS[day.month]} boshidan</b>",
             pre([line("Tushum", m.income), line("Xarajat", m.spent), line("Farq", m.income - m.spent)])]
    lines += missing_sales(collect(ms, me))
    return "\n".join(lines)


# ---------- Excel ----------

def items_breakdown(rows, category: str) -> list[tuple[str, int, int]]:
    """Bir xil nomli xaridlarni birlashtiradi: (nomi, jami summa, necha marta), kattasidan kichigiga."""
    total, times, label = defaultdict(int), defaultdict(int), {}
    for r in rows:
        if r["category"] != category:
            continue
        key = (r["item"] or "—").strip().lower()
        label.setdefault(key, (r["item"] or "—").strip())
        total[key] += r["amount"]
        times[key] += 1
    return sorted(((label[k], total[k], times[k]) for k in total), key=lambda x: -x[1])


def excel_report(start: date, end: date, path: str) -> str:
    d = collect(start, end)
    pts = {p["id"]: p["name"] for p in db.points(active_only=False)}
    wb = Workbook()
    bold = Font(bold=True)
    head = PatternFill("solid", fgColor="DDEBF7")

    # 1. Xulosa
    ws = wb.active
    ws.title = "Xulosa"
    cats = d.by_cat()
    ws.append([f"Davr: {start:%d.%m.%Y} – {end:%d.%m.%Y}", ""])
    ws.append(["Ko'rsatkich", "Summa"])
    for label, val in [("Naqd", d.cash), ("Karta", d.card), ("Yandex", d.ya), ("JAMI TUSHUM", d.income), ("", None)]:
        ws.append([label, val])
    workers = [r for r in employee_payments(start, end) if r["paid"] or r["salary"]]
    for key, name in CATEGORIES.items():
        ws.append([name, cats.get(key, 0)])
        if key != "ishchilar":  # bozorlik, ijara, prochee — har bir xarajat nomi bilan
            for nm, total, times in items_breakdown(d.expenses, key):
                ws.append([f"   {nm}", total, f"{times} marta" if times > 1 else ""])
        if key == "ishchilar":  # ishchilar summasini ism bo'yicha ochib ko'rsatamiz
            for r in sorted(workers, key=lambda r: -r["paid"]):
                left = f"qoldi {r['left']:,}".replace(",", " ") if r["salary"] else ""
                ws.append([f"   {r['name']}", r["paid"], left])
    ws.append(["JAMI XARAJAT", d.spent])
    ws.append([])
    ws.append(["FOYDA", d.income - d.spent])
    ws.append([])
    ws.append(["Tochka", "Tushum", "Xarajat", "Farq"])
    for pid, name in pts.items():
        inc = sum(r["cash"] + r["card"] for r in d.sales if r["point_id"] == pid) \
            + sum(r["amount"] for r in d.yandex if r["point_id"] == pid)
        exp = sum(r["amount"] for r in d.expenses if r["point_id"] == pid)
        ws.append([name, inc, exp, inc - exp])
    ws.append(["Umumiy", sum(r["amount"] for r in d.yandex if r["point_id"] is None),
               sum(r["amount"] for r in d.expenses if r["point_id"] is None), None])

    # 2. Kunma-kun
    ws2 = wb.create_sheet("Kunma-kun")
    ws2.append(["Sana", "Naqd", "Karta", "Yandex", "Jami tushum", *CATEGORIES.values(), "Jami xarajat", "Farq"])
    day = start
    while day <= end:
        iso = day.isoformat()
        cash = sum(r["cash"] for r in d.sales if r["day"] == iso)
        card = sum(r["card"] for r in d.sales if r["day"] == iso)
        ya = sum(r["amount"] for r in d.yandex if r["day"] == iso)
        c = d.by_cat([r for r in d.expenses if r["day"] == iso])
        spent = sum(c.values())
        if cash or card or ya or spent:
            ws2.append([iso, cash, card, ya, cash + card + ya, *[c.get(x, 0) for x in CATEGORIES], spent,
                        cash + card + ya - spent])
        day += timedelta(days=1)
    ws2.append(["JAMI", d.cash, d.card, d.ya, d.income, *[cats.get(x, 0) for x in CATEGORIES], d.spent,
                d.income - d.spent])

    # 3. Savdo (kassirlar)
    ws3 = wb.create_sheet("Kirim")
    ws3.append(["Sana", "Tochka", "Smena", "Naqd", "Karta", "Jami", "Kim yozdi"])
    for r in d.sales:
        ws3.append([r["day"], pts.get(r["point_id"], "?"), f"{r['shift']}-smena", r["cash"], r["card"],
                    r["cash"] + r["card"],
                    db.user_names().get(r["created_by"], ("?",))[0]])

    # 4. Xarajatlar
    ws4 = wb.create_sheet("Xarajatlar")
    names = db.user_names()
    ws4.append(["№", "Sana", "Tochka", "Kategoriya", "Nomi", "Miqdor", "Ishchi", "Summa", "Kim yozdi"])
    for r in d.expenses:
        ws4.append([r["id"], r["day"], pts.get(r["point_id"], "Umumiy"), CATEGORIES[r["category"]],
                    r["item"], r["quantity"], r["person"], r["amount"],
                    names.get(r["created_by"], ("?",))[0]])

    # 5. Yandex
    ws5 = wb.create_sheet("Yandex")
    ws5.append(["Tushgan kun", "Tochka", "Summa", "Izoh"])
    for r in d.yandex:
        ws5.append([r["day"], pts.get(r["point_id"], "Umumiy"), r["amount"], r["note"]])

    # 6. Ishchilar
    ws6 = wb.create_sheet("Ishchilar")
    ws6.append(["Ishchi", "Tochka", "Oylik", "Oldi", "Qoldi", "Holati"])
    for r in employee_payments(start, end):
        ws6.append([r["name"], r["point"], r["salary"], r["paid"], r["left"], "ishlaydi" if r["active"] else "bo'shagan"])

    for sheet in wb.worksheets:
        hdr = 2 if sheet.title == "Xulosa" else 1
        for c in sheet[hdr]:
            c.font, c.fill = bold, head
        for i, col in enumerate(sheet.columns, 1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            sheet.column_dimensions[get_column_letter(i)].width = min(width + 3, 40)
        for row in sheet.iter_rows(min_row=hdr + 1):
            first = row[0].value
            for c in row:
                if isinstance(c.value, int) and not (sheet.title == "Xarajatlar" and c.column == 1):
                    c.number_format = "#,##0"
                    c.alignment = Alignment(horizontal="right")
                if isinstance(first, str) and (first.isupper() and len(first) > 2):
                    c.font = bold
    wb.save(path)
    return path
