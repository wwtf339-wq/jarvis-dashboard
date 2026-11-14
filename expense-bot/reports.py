"""Ҳисоботлар: Telegram учун матн (телефон экранига мос) ва Excel файл."""
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

MONTHS = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
          "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
W = 30  # <pre> блок кенглиги (телефонда синмаслиги учун)


def som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def k(n: int) -> str:
    """Қисқа кўриниш: 1 250 000 -> 1 250к"""
    return f"{som(round(n / 1000))}к" if n else "-"


def line(label: str, amount: int) -> str:
    val = som(amount)
    return f"{label[:W - len(val) - 1]:<{W - len(val)}}{val}"


def pre(lines: list[str]) -> str:
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


def parse_amount(text: str) -> int | None:
    """'2 500 000', '2.500.000', '2,5 млн', '2500к', '800 минг' -> бутун сўм."""
    t = text.lower().replace("сўм", "").replace("сум", "").replace("so'm", "").replace("som", "").strip()
    mult = 1
    for word, m in (("млн", 1_000_000), ("миллион", 1_000_000), ("mln", 1_000_000),
                    ("минг", 1000), ("ming", 1000), ("к", 1000), ("k", 1000)):
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


# ---------- даврлар ----------

def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def period_range(kind: str, ref: date) -> tuple[date, date, str]:
    if kind == "bugun":
        return ref, ref, f"Бугун, {ref:%d.%m.%Y}"
    if kind == "kecha":
        d = ref - timedelta(days=1)
        return d, d, f"Кеча, {d:%d.%m.%Y}"
    if kind == "hafta":
        s = ref - timedelta(days=ref.weekday())
        e = s + timedelta(days=6)
        return s, e, f"Ҳафта {s:%d.%m} – {e:%d.%m.%Y}"
    if kind == "oy":
        s, e = month_range(ref.year, ref.month)
        return s, e, f"{MONTHS[ref.month]} {ref.year}"
    raise ValueError(kind)


# ---------- маълумот йиғиш ----------

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


# ---------- матн блоклари ----------

def pnl_block(d: Data) -> str:
    cats = d.by_cat()
    lines = ["ТУШУМ",
             line("  Нақд", d.cash), line("  Карта", d.card), line("  Яндекс", d.ya),
             line("  Жами тушум", d.income), "",
             "ХАРАЖАТ"]
    for key, name in CATEGORIES.items():
        lines.append(line(f"  {name}", cats.get(key, 0)))
    lines += [line("  Жами харажат", d.spent), "-" * W]
    profit = d.income - d.spent
    lines.append(line("ФОЙДА" if profit >= 0 else "ЗАРАР", profit))
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
        lines += [p["name"][:W], line("  тушум", inc), line("  харажат", exp), line("  фарқ", inc - exp)]
    general = sum(r["amount"] for r in d.expenses if r["point_id"] is None)
    general_ya = sum(r["amount"] for r in d.yandex if r["point_id"] is None)
    if general or general_ya:
        lines += ["Умумий (точкага бўлинмаган)"]
        if general_ya:
            lines.append(line("  Яндекс", general_ya))
        if general:
            lines.append(line("  харажат", general))
    return "<b>Точкалар кесимида</b>\n" + pre(lines)


def missing_sales(d: Data) -> list[str]:
    """Кассир савдо киритмаган кунлар (бугунги очиқ кун ҳисобга олинмайди)."""
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
            out.append(f"⚠️ {escape(p['name'])}: {', '.join(miss)} — савдо киритилмаган")
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
    lines = [f"{'Сана':<6}{'Тушум':>8}{'Харажат':>8}{'Фарқ':>8}"]
    for day in days:
        diff = inc[day] - exp[day]
        sign = "+" if diff > 0 else ""
        lines.append(f"{day[8:]}.{day[5:7]} {k(inc[day]):>7} {k(exp[day]):>7} {sign + k(diff) if diff else '0':>7}")
    return pre(lines) + "\n<i>к = минг сўм</i>"


def detail_block(d: Data) -> str:
    """Кунлик батафсил: ҳар бир точка савдоси ва ҳар бир харажат қатори."""
    parts = []
    if d.sales or d.yandex:
        lines = []
        for r in d.sales:
            lines += [db.point_name(r["point_id"])[:W], line("  нақд", r["cash"]), line("  карта", r["card"])]
        for r in d.yandex:
            lines.append(line(f"Яндекс ({db.point_name(r['point_id'])})", r["amount"]))
        parts.append("<b>Тушум</b>\n" + pre(lines))
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
        lines.append(line("Жами", sum(r["amount"] for r in rows)))
        parts.append(f"<b>{name}</b>\n" + pre(lines))
    return "\n".join(parts)


def employee_payments(start: date, end: date) -> list[dict]:
    """Ҳар бир ходим: ойлиги, шу даврда олгани, қолдиқ."""
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
    for name, paid in paid_by_name.items():  # рўйхатда йўқ исмлар
        out.append(dict(name=name.title(), point="?", salary=0, paid=paid, left=-paid, active=True))
    return out


def salary_block(start: date, end: date) -> str | None:
    rows = employee_payments(start, end)
    if not rows:
        return None
    lines = []
    for r in rows:
        tag = " (бўшаган)" if not r["active"] else (" (рўйхатда йўқ)" if r["point"] == "?" else "")
        lines.append((r["name"] + tag)[:W])
        lines.append(f"  {k(r['salary'])} ойлик, {k(r['paid'])} олди")
        if r["salary"]:
            lines.append(f"  қолди: {k(r['left'])}" if r["left"] >= 0 else f"  ортиқча: {k(-r['left'])}")
    return "<b>Ишчилар ойлиги</b>\n" + pre(lines)


def owner_report(kind: str, ref: date, point_id=None) -> list[str]:
    start, end, title = period_range(kind, ref)
    d = collect(start, end, point_id)
    scope = "ҳамма точкалар" if point_id is None else db.point_name(point_id)
    out = [f"📊 <b>{escape(title)}</b> — {escape(scope)}"]
    if not (d.sales or d.expenses or d.yandex):
        out.append("Маълумот йўқ.")
        return out
    out.append(pnl_block(d))
    if kind in ("bugun", "kecha"):
        out.append(detail_block(d))
    else:
        pp = per_point_block(d)
        if pp:
            out.append(pp)
        out.append("<b>Кунма-кун</b>\n" + daily_block(d))
        if kind == "oy" and point_id is None:
            sb = salary_block(start, end)
            if sb:
                out.append(sb)
    out += missing_sales(d)
    return out


def digest(day: date) -> str:
    """Эрталабки хулоса: кечаги кун + ой бошидан буён."""
    d = collect(day, day)
    ms, me = month_range(day.year, day.month)
    m = collect(ms, day)
    lines = [f"☀️ <b>Кечаги кун, {day:%d.%m}</b>",
             pre([line("Тушум", d.income), line("Харажат", d.spent), line("Фарқ", d.income - d.spent)]),
             f"<b>{MONTHS[day.month]} бошидан</b>",
             pre([line("Тушум", m.income), line("Харажат", m.spent), line("Фарқ", m.income - m.spent)])]
    lines += missing_sales(collect(ms, me))
    return "\n".join(lines)


# ---------- Excel ----------

def excel_report(start: date, end: date, path: str) -> str:
    d = collect(start, end)
    pts = {p["id"]: p["name"] for p in db.points(active_only=False)}
    wb = Workbook()
    bold = Font(bold=True)
    head = PatternFill("solid", fgColor="DDEBF7")

    # 1. Хулоса
    ws = wb.active
    ws.title = "Хулоса"
    cats = d.by_cat()
    ws.append([f"Давр: {start:%d.%m.%Y} – {end:%d.%m.%Y}", ""])
    ws.append(["Кўрсаткич", "Сумма"])
    for label, val in [("Нақд", d.cash), ("Карта", d.card), ("Яндекс", d.ya), ("ЖАМИ ТУШУМ", d.income), ("", None)]:
        ws.append([label, val])
    for key, name in CATEGORIES.items():
        ws.append([name, cats.get(key, 0)])
    ws.append(["ЖАМИ ХАРАЖАТ", d.spent])
    ws.append([])
    ws.append(["ФОЙДА", d.income - d.spent])
    ws.append([])
    ws.append(["Точка", "Тушум", "Харажат", "Фарқ"])
    for pid, name in pts.items():
        inc = sum(r["cash"] + r["card"] for r in d.sales if r["point_id"] == pid) \
            + sum(r["amount"] for r in d.yandex if r["point_id"] == pid)
        exp = sum(r["amount"] for r in d.expenses if r["point_id"] == pid)
        ws.append([name, inc, exp, inc - exp])
    ws.append(["Умумий", sum(r["amount"] for r in d.yandex if r["point_id"] is None),
               sum(r["amount"] for r in d.expenses if r["point_id"] is None), None])

    # 2. Кунма-кун
    ws2 = wb.create_sheet("Кунма-кун")
    ws2.append(["Сана", "Нақд", "Карта", "Яндекс", "Жами тушум", *CATEGORIES.values(), "Жами харажат", "Фарқ"])
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
    ws2.append(["ЖАМИ", d.cash, d.card, d.ya, d.income, *[cats.get(x, 0) for x in CATEGORIES], d.spent,
                d.income - d.spent])

    # 3. Савдо (кассирлар)
    ws3 = wb.create_sheet("Савдо")
    ws3.append(["Сана", "Точка", "Нақд", "Карта", "Жами"])
    for r in d.sales:
        ws3.append([r["day"], pts.get(r["point_id"], "?"), r["cash"], r["card"], r["cash"] + r["card"]])

    # 4. Харажатлар
    ws4 = wb.create_sheet("Харажатлар")
    ws4.append(["№", "Сана", "Точка", "Категория", "Номи", "Миқдор", "Ишчи", "Сумма"])
    for r in d.expenses:
        ws4.append([r["id"], r["day"], pts.get(r["point_id"], "Умумий"), CATEGORIES[r["category"]],
                    r["item"], r["quantity"], r["person"], r["amount"]])

    # 5. Яндекс
    ws5 = wb.create_sheet("Яндекс")
    ws5.append(["Тушган кун", "Точка", "Сумма", "Изоҳ"])
    for r in d.yandex:
        ws5.append([r["day"], pts.get(r["point_id"], "Умумий"), r["amount"], r["note"]])

    # 6. Ишчилар
    ws6 = wb.create_sheet("Ишчилар")
    ws6.append(["Ишчи", "Точка", "Ойлик", "Олди", "Қолди", "Ҳолати"])
    for r in employee_payments(start, end):
        ws6.append([r["name"], r["point"], r["salary"], r["paid"], r["left"], "ишлайди" if r["active"] else "бўшаган"])

    for sheet in wb.worksheets:
        hdr = 2 if sheet.title == "Хулоса" else 1
        for c in sheet[hdr]:
            c.font, c.fill = bold, head
        for i, col in enumerate(sheet.columns, 1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            sheet.column_dimensions[get_column_letter(i)].width = min(width + 3, 40)
        for row in sheet.iter_rows(min_row=hdr + 1):
            first = row[0].value
            for c in row:
                if isinstance(c.value, int) and not (sheet.title == "Харажатлар" and c.column == 1):
                    c.number_format = "#,##0"
                    c.alignment = Alignment(horizontal="right")
                if isinstance(first, str) and (first.isupper() and len(first) > 2):
                    c.font = bold
    wb.save(path)
    return path
