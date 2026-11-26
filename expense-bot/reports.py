"""Hisobotlar: Telegram uchun matn (telefon ekraniga mos) va Excel fayl."""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import db
from config import CATEGORIES, SALARY_START, business_today

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
    closings: list = field(default_factory=list)

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
                db.yandex_between(start, end, point_id),
                db.closings_between(start, end, point_id))


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


def shift_label(n: int) -> str:
    return "kunlik" if not n else f"{n}-smena"


def kassa_lines(c) -> list[str]:
    """Kunlik hisobot: hisob bo'yicha naqd va kassada sanalgan naqd farqi."""
    expected = c["total"] - c["card"] - c["spent"]
    diff = c["cash_left"] - expected
    out = [f"Kassa — {db.point_name(c['point_id'])}"[:W],
           line("  savdo", c["total"]), line("  karta/schet", c["card"]), line("  xarajat", c["spent"]),
           line("  naqd (hisob)", expected), line("  naqd (kassada)", c["cash_left"])]
    out.append(line("  ✅ farq yo'q", 0) if diff == 0 else
               line("  ⚠️ kam" if diff < 0 else "  ⚠️ ortiqcha", abs(diff)))
    return out


def detail_block(d: Data) -> str:
    """Kunlik batafsil: har bir tochka savdosi va har bir xarajat qatori."""
    parts = []
    if d.sales or d.yandex:
        lines = []
        for r in d.sales:
            lines += [f"{db.point_name(r['point_id'])}, {shift_label(r['shift'])}"[:W],
                      line("  naqd", r["cash"]), line("  karta", r["card"])]
        for r in d.yandex:
            lines.append(line(f"Yandex ({db.point_name(r['point_id'])})", r["amount"]))
        parts.append("<b>Tushum</b>\n" + pre(lines))
    if d.closings:
        lines = []
        for c in d.closings:
            lines += kassa_lines(c)
        parts.append("<b>Kassa</b>\n" + pre(lines))
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
            if who and who[1] in ("cashier", "admin"):
                lines.append(f"   ✍ {who[0]}"[:W])
        lines.append(line("Jami", sum(r["amount"] for r in rows)))
        parts.append(f"<b>{name}</b>\n" + pre(lines))
    return "\n".join(parts)


def employee_payments(start: date, end: date, point_id=None) -> list[dict]:
    """Har bir ishchi shu davrda: ishlagan kuni, kunlik stavka, hisoblangan, olgani, qoldiq.
    Hisob SALARY_START dan boshlanadi — undan oldingi kunlar va to'lovlar hisobga olinmaydi."""
    s0 = max(start, SALARY_START)
    paid_by_id, paid_by_name = defaultdict(int), defaultdict(int)
    days = db.attendance_days(s0, end) if s0 <= end else {}
    if s0 <= end:
        for r in db.expenses_between(s0, end, point_id):
            if r["category"] != "ishchilar":
                continue
            if r["employee_id"]:
                paid_by_id[r["employee_id"]] += r["amount"]
            else:
                paid_by_name[(r["person"] or "kunlik (umumiy)").strip().lower()] += r["amount"]
    out = []
    for e in db.employees(active_only=False, point_id=point_id):
        if not e["active"] and (not e["fired_on"] or e["fired_on"] < s0.isoformat()):
            continue
        paid = paid_by_id.pop(e["id"], 0) + paid_by_name.pop(e["name"].lower(), 0)
        n, rate = days.get(e["id"], 0), e["daily_rate"]
        row = dict(id=e["id"], name=e["name"], point=db.point_name(e["point_id"]), type=e["pay_type"], rate=rate,
                   days=n, earned=n * rate, paid=paid, active=bool(e["active"]))
        if e["pay_type"] == "chef":
            row.update(chef_pay(e, s0, end))
            row["rate"] = row["fixed"]  # "stavka bor" degan belgi sifatida
        row["left"] = row["earned"] - paid
        out.append(row)
    for name, paid in paid_by_name.items():  # ro'yxatda yo'q ismlar
        out.append(dict(id=None, name=name.title(), point="?", type="daily", rate=0, days=0, earned=0, paid=paid,
                        left=-paid, active=True))
    return out


def chef_pay(e, start: date, end: date) -> dict:
    """Oshpaz: fiks oylik (oy o'rtasidan boshlagan bo'lsa — qismi) + limitdan oshgan har kg uchun bonus."""
    m_start, m_end = month_range(start.year, start.month)
    hired = date.fromisoformat(e["hired_on"]) if e["hired_on"] else m_start
    work_from = max(m_start, SALARY_START, hired)
    frac = max(0, (m_end - work_from).days + 1) / ((m_end - m_start).days + 1)
    fixed = int(round(e["monthly_fixed"] * frac, -3))
    kg = db.kg_total(e["id"], start, end)
    over = max(0.0, kg - e["kg_limit"])
    bonus = int(round(over * e["kg_bonus"]))
    return dict(product=e["product"] or "", fixed=fixed, full_fixed=e["monthly_fixed"], kg=kg,
                limit=e["kg_limit"], over=over, kg_bonus=e["kg_bonus"], bonus=bonus, earned=fixed + bonus)


def kgf(x: float) -> str:
    return f"{x:,.1f}".replace(",", " ").replace(".0", "")


def wage_lines(r) -> list[str]:
    """Bitta ishchi uchun qisqa satrlar (hisobot <pre> bloki uchun)."""
    out = []
    if r.get("type") == "chef":
        out.append(f"  {kgf(r['kg'])}/{kgf(r['limit'])} kg, +{kgf(r['over'])} kg")
        out.append(f"  fiks {k(r['fixed'])} + bonus {k(r['bonus']) if r['bonus'] else '0'}")
        out.append(f"  oldi {k(r['paid']) if r['paid'] else '0'}, " + (f"qoldi {k(r['left'])}" if r["left"] >= 0
                                                                     else f"ortiqcha {k(-r['left'])}"))
        return out
    if r["rate"]:
        out.append(f"  {r['days']} kun × {k(r['rate'])} = {k(r['earned']) if r['earned'] else '0'}")
        out.append(f"  oldi {k(r['paid']) if r['paid'] else '0'}, "
                   + (f"qoldi {k(r['left']) if r['left'] else '0'}" if r["left"] >= 0 else f"ortiqcha {k(-r['left'])}"))
    else:
        out.append(f"  stavka yo'q, {r['days']} kun, oldi {k(r['paid']) if r['paid'] else '0'}")
    return out


def salary_block(start: date, end: date, point_id=None) -> str | None:
    rows = [r for r in employee_payments(start, end, point_id) if r["days"] or r["paid"] or r["rate"]]
    if not rows:
        return None
    lines = []
    for r in rows:
        tag = " (bo'shagan)" if not r["active"] else (" (ro'yxatda yo'q)" if r["point"] == "?" else "")
        lines.append((r["name"] + tag)[:W])
        lines += [x[:W] for x in wage_lines(r)]
    since = f" ({SALARY_START:%d.%m} dan)" if start < SALARY_START <= end else ""
    return f"<b>Ishchilar ish haqi{since}</b>\n" + pre(lines)


def owner_report(kind: str, ref: date, point_id=None) -> list[str]:
    start, end, title = period_range(kind, ref)
    d = collect(start, end, point_id)
    scope = "hamma tochkalar" if point_id is None else db.point_name(point_id)
    out = [f"📊 <b>{escape(title)}</b> — {escape(scope)}"]
    if not (d.sales or d.expenses or d.yandex):
        out.append("Ma'lumot yo'q.")
        sb = salary_block(start, end, point_id) if kind == "oy" else None
        if sb:
            out.append(sb)
        return out
    out.append(pnl_block(d))
    if kind in ("bugun", "kecha"):
        out.append(detail_block(d))
    else:
        pp = per_point_block(d)
        if pp:
            out.append(pp)
        out.append("<b>Kunma-kun</b>\n" + daily_block(d))
        if kind == "oy":
            sb = salary_block(start, end, point_id)
            if sb:
                out.append(sb)
    out += missing_sales(d)
    return out


def kitchen_lines(day: date) -> list[str]:
    """Oshpazlar: pishirildi → tayyor → tochkalarga berildi."""
    names = {p["id"]: p["name"] for p in db.points(active_only=False)}
    out = []
    for r in db.kg_rows(day, day):
        if not r["kg"]:
            continue
        out.append(f"{r['name']} ({r['product'] or ''})"[:W])
        out.append(f"  pishirildi {kgf(r['kg'])} kg"[:W])
        if r["ready_kg"] is not None:
            out.append(f"  tayyor {kgf(r['ready_kg'])} kg ({r['ready_kg'] / r['kg'] * 100:.0f}%)"[:W])
        for pid, kg in db.deliveries_of(day, r["employee_id"]).items():
            out.append(f"  → {names.get(pid, '?')} {kgf(kg)} kg"[:W])
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
    if d.closings:
        k = []
        for c in d.closings:
            k += kassa_lines(c)
        lines += ["<b>Kassa</b>", pre(k)]
    kitchen = kitchen_lines(day)
    if kitchen:
        lines += ["<b>Oshxona</b>", pre(kitchen)]
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


def excel_report(start: date, end: date, path: str, point_id=None) -> str:
    """point_id berilsa — faqat o'sha tochka (admin uchun)."""
    d = collect(start, end, point_id)
    pts = {p["id"]: p["name"] for p in db.points(active_only=False) if not point_id or p["id"] == point_id}
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
    wages = {r["name"].lower(): r for r in employee_payments(start, end, point_id)}
    paid_raw = defaultdict(int)  # shu davrdagi to'lovlar ism bo'yicha (kategoriya jamiga mos)
    for r in d.expenses:
        if r["category"] == "ishchilar":
            paid_raw[(r["person"] or r["item"] or "—").strip()] += r["amount"]
    for key, name in CATEGORIES.items():
        ws.append([name, cats.get(key, 0)])
        if key != "ishchilar":  # bozorlik, ijara, prochee — har bir xarajat nomi bilan
            for nm, total, times in items_breakdown(d.expenses, key):
                ws.append([f"   {nm}", total, f"{times} marta" if times > 1 else ""])
        if key == "ishchilar":  # ishchilar summasini ism bo'yicha ochib ko'rsatamiz
            for nm, paid in sorted(paid_raw.items(), key=lambda x: -x[1]):
                w = wages.get(nm.lower())
                if w and w["type"] == "chef":
                    note = (f"fiks {som(w['fixed'])} + bonus {som(w['bonus'])} ({kgf(w['kg'])} kg), "
                            f"qoldi {som(w['left'])}")
                else:
                    note = (f"{w['days']} kun × {som(w['rate'])} = {som(w['earned'])}, qoldi {som(w['left'])}"
                            if w and w["rate"] else "")
                ws.append([f"   {nm}", paid, note])
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
    if not point_id:
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
        ws3.append([r["day"], pts.get(r["point_id"], "?"), shift_label(r["shift"]), r["cash"], r["card"],
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

    # 6. Kassa (admin kunlik hisobotlari)
    ws7 = wb.create_sheet("Kassa")
    ws7.append(["Sana", "Tochka", "Savdo", "Karta/schet", "Xarajat", "Naqd (hisob)", "Naqd (kassada)",
                "Farq", "Kim yozdi"])
    names = db.user_names()
    for c in d.closings:
        expected = c["total"] - c["card"] - c["spent"]
        ws7.append([c["day"], pts.get(c["point_id"], "?"), c["total"], c["card"], c["spent"], expected,
                    c["cash_left"], c["cash_left"] - expected, names.get(c["created_by"], ("?",))[0]])

    # Qarzlar (faqat xo'jayin hisobotida)
    if not point_id:
        ws8 = wb.create_sheet("Qarzlar")
        ws8.append(["Kimga", "Jami olingan", "Jami to'langan", "Qoldiq qarz", "Oxirgi sana"])
        for r in db.debt_balances(only_open=False):
            ws8.append([r["name"], r["taken"], r["paid"], r["balance"], r["last_day"]])
        ws8.append(["JAMI QARZ", None, None, sum(r["balance"] for r in db.debt_balances() if r["balance"] > 0), None])
        ws8.append([])
        ws8.append(["Shu oydagi harakatlar"])
        ws8.append(["Sana", "Kimga", "Qarz olindi", "To'landi", "Izoh"])
        for m in db.debt_moves_between(start, end):
            ws8.append([m["day"], m["name"], m["amount"] if m["amount"] > 0 else None,
                        -m["amount"] if m["amount"] < 0 else None, m["note"]])

    # 7. Ishchilar
    ws6 = wb.create_sheet("Ishchilar")
    ws6.append(["Ishchi", "Turi", "Kunlik stavka", "Ishlagan kun", "Fiks oylik", "Pishirgan kg", "Limit kg",
                "Limitdan oshgan kg", "Bonus", "Hisoblangan", "Oldi", "Qoldi", "Holati"])
    for r in employee_payments(start, end, point_id):
        if r["type"] == "chef":
            ws6.append([r["name"], f"Oshpaz ({r['product']})", None, r["days"], r["fixed"], r["kg"], r["limit"],
                        r["over"], r["bonus"], r["earned"], r["paid"], r["left"],
                        "ishlaydi" if r["active"] else "bo'shagan"])
        else:
            ws6.append([r["name"], "Kunlik", r["rate"], r["days"], None, None, None, None, None, r["earned"],
                        r["paid"], r["left"], "ishlaydi" if r["active"] else "bo'shagan"])
    kg_list = db.kg_rows(max(start, SALARY_START), end) if not point_id else []
    if kg_list:
        ws9 = wb.create_sheet("Oshpazlar")
        all_pts = db.points(active_only=False)
        dl = defaultdict(float)
        for r in db.deliveries_between(max(start, SALARY_START), end):
            dl[(r["day"], r["employee_id"], r["point_id"])] += r["kg"]
        ws9.append(["Sana", "Oshpaz", "Mahsulot", "Skladda (ertalab)", "Pishirildi (xom)", "Tayyor chiqdi",
                    "Chiqish %", *[p["name"] for p in all_pts], "Tayyor qoldiq"])
        tot = defaultdict(float)
        for r in kg_list:
            given = [dl.get((r["day"], r["employee_id"], p["id"]), 0) for p in all_pts]
            ready = r["ready_kg"]
            pct = round(ready / r["kg"] * 100, 1) if ready and r["kg"] else None
            ws9.append([r["day"], r["name"], r["product"], r["stock_kg"], r["kg"] or None, ready, pct, *given,
                        (ready - sum(given)) if ready is not None else None])
            tot["raw"] += r["kg"] or 0
            tot["ready"] += ready or 0
            for p, g in zip(all_pts, given):
                tot[p["id"]] += g
        ws9.append(["JAMI", None, None, None, tot["raw"], tot["ready"],
                    round(tot["ready"] / tot["raw"] * 100, 1) if tot["raw"] else None,
                    *[tot[p["id"]] for p in all_pts], None])
    if start < SALARY_START <= end:
        ws6.append([])
        ws6.append([f"Ish haqi hisobi {SALARY_START:%d.%m.%Y} dan boshlangan"])

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
    # Xulosa: kategoriya sarlavhalari (Bozorlik, Ishchilar...) qalin va kattaroq — ajralib tursin
    cat_font = Font(bold=True, size=12)
    for row in wb["Xulosa"].iter_rows():
        if row[0].value in CATEGORIES.values():
            for c in row[:2]:
                c.font = cat_font
    wb.save(path)
    return path
