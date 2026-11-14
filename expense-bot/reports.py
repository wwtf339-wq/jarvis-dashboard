"""Ҳисоботлар: Telegram учун матн жадвал ва Excel файл."""
from collections import defaultdict
from datetime import date, timedelta
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import CATEGORIES


def som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def period_range(kind: str, today: date) -> tuple[date, date, str]:
    if kind == "bugun":
        return today, today, f"Бугун ({today:%d.%m.%Y})"
    if kind == "kecha":
        d = today - timedelta(days=1)
        return d, d, f"Кеча ({d:%d.%m.%Y})"
    if kind == "hafta":
        start = today - timedelta(days=today.weekday())  # душанба
        return start, start + timedelta(days=6), f"Ҳафта ({start:%d.%m} – {start + timedelta(days=6):%d.%m.%Y})"
    if kind == "oy":
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1), f"Ой ({start:%m.%Y})"
    raise ValueError(kind)


def _totals(rows):
    by_cat = defaultdict(int)
    for r in rows:
        by_cat[r["category"]] += r["amount"]
    return by_cat


def text_report(rows, title: str, detailed: bool) -> str:
    """HTML (<pre>) кўринишидаги ҳисобот. detailed=True — ҳар бир қатор, акс ҳолда кунлар кесимида."""
    if not rows:
        return f"<b>{escape(title)}</b>\nМаълумот йўқ."

    out = [f"<b>{escape(title)}</b>"]
    by_cat = _totals(rows)

    if detailed:
        for key, name in CATEGORIES.items():
            cat_rows = [r for r in rows if r["category"] == key]
            if not cat_rows:
                continue
            lines = [f"{name}"]
            for r in cat_rows:
                label = r["item"]
                if r["person"]:
                    label = f"{r['person']} ({r['item']})" if key == "ishchilar" else f"{label} [{r['person']}]"
                if r["quantity"]:
                    label += f" {r['quantity']}"
                lines.append(f"  {label[:24]:<24} {som(r['amount']):>11}")
            lines.append(f"  {'Жами':<24} {som(by_cat[key]):>11}")
            out.append("<pre>" + escape("\n".join(lines)) + "</pre>")
    else:
        days = sorted({r["day"] for r in rows})
        head = f"{'Сана':<6}" + "".join(f"{n[:7]:>9}" for n in CATEGORIES.values()) + f"{'Жами':>11}"
        lines = [head]
        for d in days:
            dr = [r for r in rows if r["day"] == d]
            t = _totals(dr)
            lines.append(
                f"{d[8:]}.{d[5:7]}" + "".join(f"{t.get(k, 0)//1000:>8}к" if t.get(k) else f"{'-':>9}" for k in CATEGORIES)
                + f"{som(sum(t.values())):>11}"
            )
        out.append("<pre>" + escape("\n".join(lines)) + "</pre>")
        out.append("<i>(к = минг сўм)</i>")

    summary = [f"{CATEGORIES[k]:<12}{som(by_cat[k]):>13}" for k in CATEGORIES if k in by_cat]
    summary.append(f"{'ЖАМИ':<12}{som(sum(by_cat.values())):>13}")
    out.append("<pre>" + escape("\n".join(summary)) + "</pre>")
    return "\n".join(out)


def excel_report(rows, path: str, title: str) -> str:
    wb = Workbook()
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="DDEBF7")

    # 1-варақ: ҳамма қаторлар
    ws = wb.active
    ws.title = "Ҳамма харажатлар"
    ws.append(["Сана", "Категория", "Номи", "Миқдор", "Ишчи", "Сумма (сўм)"])
    for r in rows:
        ws.append([r["day"], CATEGORIES[r["category"]], r["item"], r["quantity"], r["person"], r["amount"]])
    ws.append([])
    ws.append(["", "", "", "", "ЖАМИ", sum(r["amount"] for r in rows)])

    # 2-варақ: кунлар × категориялар
    ws2 = wb.create_sheet("Кунлар кесимида")
    names = list(CATEGORIES.values())
    ws2.append(["Сана", *names, "Жами"])
    days = sorted({r["day"] for r in rows})
    for d in days:
        t = _totals([r for r in rows if r["day"] == d])
        ws2.append([d, *[t.get(k, 0) for k in CATEGORIES], sum(t.values())])
    tot = _totals(rows)
    ws2.append(["ЖАМИ", *[tot.get(k, 0) for k in CATEGORIES], sum(tot.values())])

    # 3-варақ: ишчилар бўйича
    ws3 = wb.create_sheet("Ишчилар")
    ws3.append(["Ишчи", "Тўланган жами (сўм)"])
    per = defaultdict(int)
    for r in rows:
        if r["category"] == "ishchilar":
            per[r["person"] or "—"] += r["amount"]
    for p, a in sorted(per.items()):
        ws3.append([p, a])

    for sheet in wb.worksheets:
        for c in sheet[1]:
            c.font, c.fill = bold, fill
        for i, col in enumerate(sheet.columns, 1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            sheet.column_dimensions[get_column_letter(i)].width = min(width + 3, 40)
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, int):
                    c.number_format = "#,##0"
                    c.alignment = Alignment(horizontal="right")
    for row in (ws[ws.max_row], ws2[ws2.max_row]):
        for c in row:
            c.font = bold

    wb.save(path)
    return path
