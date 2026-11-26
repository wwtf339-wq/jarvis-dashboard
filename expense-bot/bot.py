"""Fast-fud biznesi uchun Telegram hisobchi-bot.

Rollar:
  owner   — xo'jayin (2-3 kishi): xarajat/Yandex kiritadi, xodim va kassir qo'shadi, hisobot oladi.
  cashier — tochka kassiri: har kuni naqd va kartaga tushgan savdoni kiritadi.
"""
import logging
import re
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import date, timedelta
from html import escape

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import ai
import db
import quick
import reports
from config import (SALARY_START, BACKUP_TIME, BACKUP_WEEKDAY, BOT_TOKEN, CATEGORIES, DB_PATH, DIGEST_TIME,
                    MAX_OWNERS, NOTIFY_OWNERS_ON_SALES, SHIFTS, ADMIN_REMINDER_TIME, OWNER_IDS, SALES_REMINDER_TIME, at,
                    business_today)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("expense-bot")

HTML = ParseMode.HTML
som = reports.som

# ---------- klaviaturalar ----------
O_TODAY, O_WEEK, O_MONTH = "📅 Bugun", "📆 Hafta", "🗓 Oy"
O_XLSX, O_STAFF, O_ADMIN = "📊 Excel", "👥 Xodimlar", "⚙️ Boshqaruv"
O_DEBT = "📒 Qarzlar"
B_EXP, B_INC = "💸 Xarajat", "💰 Kirim"
OWNER_KB = ReplyKeyboardMarkup([[B_EXP, B_INC], [O_TODAY, O_WEEK, O_MONTH], [O_XLSX, O_STAFF],
                                [O_DEBT, O_ADMIN]],
                               resize_keyboard=True)
CASHIER_KB = ReplyKeyboardMarkup([[B_EXP, B_INC]], resize_keyboard=True)
B_DAY = "📝 Kunlik hisobot"
W_IN, W_OFF, W_ME = "✅ Ishga chiqdim", "🏖 Dam oldim", "📊 Mening hisobim"
WORKER_KB = ReplyKeyboardMarkup([[W_IN, W_OFF], [W_ME]], resize_keyboard=True)
ADMIN_KB = ReplyKeyboardMarkup([[B_DAY]], resize_keyboard=True)

EXP_PROMPT = ("💸 Xarajatni <b>ovoz</b> yoki <b>matn</b> bilan yuboring. Bitta xabarda bir nechtasini aytish mumkin:\n"
              "<i>«Ibrat 100 ming o'ziga oldi, 50 ming benzin quydim, 10 kilo pomidor 100 ming»</i>")

OWNER_HELP = """<b>Xo'jayin buyruqlari</b>

💸 <b>Xarajat</b> — tugmani bosing yoki to'g'ridan-to'g'ri ovoz/matn yuboring:
<i>«10 kg pomidor 100 ming, tovuq go'shti 10 kg 350 ming, Ibrat 100 ming oldi»</i>
<i>«Yandexdan 2 million 400 ming tushdi»</i> — Yandex tushumi

📊 <b>Hisobot</b>: /bugun /kecha /hafta /oy (/oy 2026-10) /excel (/excel 2026-10)

🏪 <b>Tochkalar</b>
/nuqta_qosh Nomi — yangi tochka
/nuqtalar — ro'yxat

👤 <b>Foydalanuvchilar</b>
/admin_qosh — tochka admini (har kuni ertalab kechagi kun hisobotini yozadi)
/kassir_qosh — kassir uchun taklif havolasi
/hujayin_qosh — xo'jayin uchun taklif havolasi
/foydalanuvchilar — ro'yxat, o'chirib qo'yish

👥 <b>Xodimlar (kunlik ish haqi)</b>
/ishchilar — ro'yxat
/ishchi_qosh Ism — ishga olish (/ishchi_qosh Ibrat, Jahongir)
/oylik Ism Summa — kunlik stavka (/oylik Umid 200000)
/davomat — kim ishlaganini belgilash (/davomat bugun)
/ishchi_ulash — ishchini botga ulash (o'zi «Ishga chiqdim / Dam oldim» bosadi)
/boshat № — ishdan bo'shatish

💰 <b>Pul</b>
/yandex Summa [izoh] — Yandex tushumi (/yandex 2400000 3-9 noyabr)
💰 <b>Kirim</b> tugmasi — smena kirimi (smena → naqd → karta)
/savdo Naqd Karta — tezkor kirim (/savdo 2-smena 2500000 1800000)

✏️ <b>Tuzatish</b>
/oxirgi — oxirgi yozuvlar
/ochir № — xarajatni o'chirish
/yandex_ochir № — Yandex yozuvini o'chirish

📒 <b>Qarzlar</b> — «📒 Qarzlar» tugmasi yoki /qarzlar
/qarz_ochir № — xato yozilgan qarz/to'lovni o'chirish

📝 <b>Kunlik hisobotlar (adminlar)</b>
/kunlik — oxirgi hisobotlar
/kunlik_ochir № — hisobotni o'chirish (admin qayta yoza oladi)

🧹 /tozalash — barcha xarajat, kirim va Yandex yozuvlarini o'chirish (avval zahira nusxa yuboriladi)"""

ADMIN_HELP = """<b>Tochka admini: {point}</b>

Har kuni ertalab <b>📝 Kunlik hisobot</b> ni bosib, kechagi kunni yozasiz:
1. 💰 Jami savdo (1 va 2-smena birga)
2. 💸 Xarajatlar — matn yoki ovoz: <i>ishchilar 400000, non 120000, salfetka 30000</i>
3. 💳 Karta / schetga tushgani
4. 💵 Kassada qolgan naqd

Bot hisoblab, kassadagi naqd to'g'ri yoki farq borligini ko'rsatadi.
Saqlangan hisobotni o'zgartirib yoki o'chirib bo'lmaydi — xato bo'lsa, xo'jayinga ayting."""

WORKER_HELP = ("Salom, <b>{name}</b>!\n\n"
               "Har kuni bitta tugmani bosing:\n"
               "✅ <b>Ishga chiqdim</b> — bugun ishlayapman\n"
               "🏖 <b>Dam oldim</b> — bugun ishlamayman\n\n"
               "📊 <b>Mening hisobim</b> — bu oy necha kun ishladingiz, qancha hisoblandi, qancha oldingiz.\n"
               "Xato bossangiz, ikkinchisini bosing — almashadi.")

CASHIER_HELP = ("Salom! Siz <b>{point}</b> xodimisiz.\n\n"
                "💸 <b>Xarajat</b> — pul chiqsa (bozorlik, avans, benzin…) ovoz yoki matn bilan yozing.\n"
                "💰 <b>Kirim</b> — smena oxirida: smenani tanlang, keyin naqd va karta summasini yozing. "
                "Xato yozsangiz, qayta kiriting — eskisi almashadi.\n"
                "Kechasi 05:00 gacha kiritilgan kirim oldingi kunga yoziladi.")


# ---------- yordamchilar ----------

def current_user(update: Update):
    u = update.effective_user
    if not u:
        return None
    row = db.get_user(u.id)
    return row if row and row["active"] else None


def full_name(update: Update) -> str:
    u = update.effective_user
    return (u.full_name or u.username or str(u.id)).strip()


def stash(ctx: ContextTypes.DEFAULT_TYPE, item: dict) -> str:
    key = uuid.uuid4().hex[:10]
    ctx.bot_data.setdefault("pending", {})[key] = item
    return key


def confirm_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Saqlash", callback_data=f"ok:{key}"),
                                  InlineKeyboardButton("❌ Bekor", callback_data=f"no:{key}")]])


def points_kb(prefix: str, with_general: bool = False, with_all: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(p["name"], callback_data=f"{prefix}:{p['id']}")] for p in db.points()]
    if with_general:
        rows.append([InlineKeyboardButton("Umumiy (hamma tochkaga)", callback_data=f"{prefix}:0")])
    if with_all:
        rows.append([InlineKeyboardButton("Hammasi", callback_data=f"{prefix}:0")])
    return InlineKeyboardMarkup(rows)


def match_point(name):
    if not name:
        return None
    n = name.strip().lower()
    for p in db.points():
        pn = p["name"].lower()
        if pn == n or n in pn or pn in n:
            return p["id"]
    return None


async def send_parts(message, parts: list[str], reply_markup=None):
    """Telegram 4096 belgidan uzun xabarni qabul qilmaydi — bloklarga bo'lib yuboramiz."""
    chunks, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    for i, ch in enumerate(chunks):
        await message.reply_text(ch, parse_mode=HTML,
                                 reply_markup=reply_markup if i == len(chunks) - 1 else None)


async def deny(update: Update):
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            f"Sizga ruxsat berilmagan.\nSizning Telegram ID: <code>{update.effective_user.id}</code>\n"
            "Xo'jayindan taklif havolasini so'rang.", parse_mode=HTML)


def owner_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        u = current_user(update)
        if not u or u["role"] != "owner":
            return await deny(update)
        return await fn(update, ctx, u)
    wrapper.__name__ = fn.__name__
    return wrapper


MANAGERS = ("owner",)   # admin faqat kunlik hisobot yozadi


def manager_only(fn):
    """Xo'jayin yoki tochka admini."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        u = current_user(update)
        if not u or u["role"] not in MANAGERS:
            return await deny(update)
        return await fn(update, ctx, u)
    wrapper.__name__ = fn.__name__
    return wrapper


def scope(u):
    """Xo'jayin hamma tochkani ko'radi (None), admin — faqat o'z tochkasini."""
    return u["point_id"] if u["role"] == "admin" else None


def in_scope(u, point_id) -> bool:
    return u["role"] == "owner" or (point_id and point_id == u["point_id"])


def role_kb(u):
    return {"owner": OWNER_KB, "admin": ADMIN_KB, "worker": WORKER_KB}.get(u["role"], CASHIER_KB)


def role_help(u) -> str:
    if u["role"] == "owner":
        return OWNER_HELP
    if u["role"] == "admin":
        return ADMIN_HELP.format(point=escape(db.point_name(u["point_id"])))
    if u["role"] == "worker":
        e = db.get_employee(u["employee_id"]) if u["employee_id"] else None
        return WORKER_HELP.format(name=escape(e["name"] if e else (u["name"] or "")))
    return CASHIER_HELP.format(point=escape(db.point_name(u["point_id"])))


# ---------- /start va takliflar ----------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    name = full_name(update)
    arg = ctx.args[0] if ctx.args else ""

    if arg.startswith("inv_"):
        inv = db.use_invite(arg[4:], tg_id)
        if not inv:
            return await update.message.reply_text("Havola eskirgan yoki ishlatib bo'lingan. Xo'jayindan yangisini so'rang.")
        if inv["role"] == "owner" and len(db.owner_ids()) >= MAX_OWNERS and tg_id not in db.owner_ids():
            return await update.message.reply_text(f"Xo'jayinlar soni chegaraga ({MAX_OWNERS}) yetgan.")
        db.upsert_user(tg_id, name, inv["role"], inv["point_id"], inv["employee_id"])
        db.audit(tg_id, "joined", f"{inv['role']} point={inv['point_id']} by={inv['created_by']}")
        emp = db.get_employee(inv["employee_id"]) if inv["employee_id"] else None
        role_txt = {"owner": "xo'jayin", "admin": f"«{db.point_name(inv['point_id'])}» admini",
                    "worker": f"ishchi ({emp['name'] if emp else '?'})"}.get(
            inv["role"], f"«{db.point_name(inv['point_id'])}» kassiri")
        for oid in db.owner_ids():
            if oid != tg_id:
                try:
                    await ctx.bot.send_message(oid, f"👤 {escape(name)} {role_txt} sifatida qo'shildi.", parse_mode=HTML)
                except Exception:
                    log.warning("owner %s notify failed", oid)

    u = current_user(update)
    if not u:
        return await deny(update)
    if u["name"] != name:
        db.set_user_name(tg_id, name)

    await update.message.reply_text(role_help(u), parse_mode=HTML,
                                    reply_markup=role_kb(u))
    if u["role"] == "owner" and not db.points():
        await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Chilonzor")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    await update.message.reply_text(role_help(u), parse_mode=HTML,
                                    reply_markup=role_kb(u))


@owner_only
async def add_point_cmd(update, ctx, u):
    name = " ".join(ctx.args).strip()
    if not name:
        return await update.message.reply_text("Format: /nuqta_qosh Chilonzor")
    try:
        pid = db.add_point(name)
    except sqlite3.IntegrityError:
        return await update.message.reply_text("Bunday nomli tochka bor.")
    db.audit(u["tg_id"], "point_add", name)
    await update.message.reply_text(f"🏪 «{name}» qo'shildi (№{pid}).\nEndi kassir qo'shing: /kassir_qosh")


@owner_only
async def points_cmd(update, ctx, u):
    pts = db.points()
    if not pts:
        return await update.message.reply_text("Tochka yo'q. /nuqta_qosh Nomi")
    lines = []
    for p in pts:
        cs = [db.get_user(c) for c in db.cashiers_of(p["id"])]
        names = ", ".join((c["name"] or str(c["tg_id"])) for c in cs) or "kassir yo'q"
        lines.append(f"№{p['id']} <b>{escape(p['name'])}</b> — {escape(names)}")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


@manager_only
async def add_cashier_cmd(update, ctx, u):
    if u["role"] == "admin":
        return await send_invite(update.message, ctx, u, "cashier", u["point_id"])
    if not db.points():
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    await update.message.reply_text("Kassir qaysi tochkada ishlaydi?", reply_markup=points_kb("inv"))


@owner_only
async def add_admin_cmd(update, ctx, u):
    if not db.points():
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    await update.message.reply_text("Admin qaysi tochkaga?", reply_markup=points_kb("ainv"))


@owner_only
async def add_owner_cmd(update, ctx, u):
    if len(db.owner_ids()) >= MAX_OWNERS:
        return await update.message.reply_text(f"Xo'jayinlar soni chegarada ({MAX_OWNERS}). /foydalanuvchilar dan bittasini o'chiring.")
    await send_invite(update.message, ctx, u, "owner", None)


async def send_invite(message, ctx, u, role: str, point_id, employee_id=None):
    code = db.create_invite(role, point_id, u["tg_id"], employee_id)
    link = f"https://t.me/{ctx.bot.username}?start=inv_{code}"
    emp = db.get_employee(employee_id) if employee_id else None
    who = {"owner": "xo'jayin", "admin": f"«{escape(db.point_name(point_id))}» admini",
           "worker": f"ishchi {escape(emp['name']) if emp else ''}"}.get(
        role, f"«{escape(db.point_name(point_id))}» kassiri")
    await message.reply_text(
        f"🔗 Shu havolani {who}ga yuboring (48 soat, bir marta ishlaydi):\n\n{link}",
        parse_mode=HTML, disable_web_page_preview=True)


@owner_only
async def users_cmd(update, ctx, u):
    rows = db.users()
    if not rows:
        return await update.message.reply_text("Hech kim yo'q.")
    lines, kb = [], []
    for r in rows:
        emp = db.get_employee(r["employee_id"]) if r["employee_id"] else None
        role = {"owner": "👑 xo'jayin", "admin": f"🛡 admin — {db.point_name(r['point_id'])}",
                "worker": f"👷 ishchi — {emp['name'] if emp else '?'}"}.get(
            r["role"], f"🧾 kassir — {db.point_name(r['point_id'])}")
        status = "" if r["active"] else " — ❌ o'chirilgan"
        lines.append(f"{escape(r['name'] or str(r['tg_id']))} — {escape(role)}{status}")
        if r["tg_id"] != u["tg_id"] and r["tg_id"] not in OWNER_IDS:
            label = ("🚫 O'chirish: " if r["active"] else "✅ Yoqish: ") + (r["name"] or str(r["tg_id"]))
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"ua:{r['tg_id']}")])
    await update.message.reply_text("\n".join(lines), parse_mode=HTML,
                                    reply_markup=InlineKeyboardMarkup(kb) if kb else None)


# ---------- xodimlar ----------

def month_period(today: date) -> tuple[date, date]:
    """Joriy oy, lekin SALARY_START dan oldin emas."""
    start, _ = reports.month_range(today.year, today.month)
    return max(start, SALARY_START), today


@manager_only
async def staff_cmd(update, ctx, u):
    emps = db.employees(point_id=scope(u))
    if not emps:
        return await update.message.reply_text("Xodim yo'q.\n" + ADD_EMP_HELP)
    today = business_today()
    start, end = month_period(today)
    wages = {r["id"]: r for r in reports.employee_payments(start, end, scope(u))}
    status = db.day_status(today)
    icon = {1: "✅ ishda", 0: "🏖 dam"}
    lines = [f"👥 <b>Xodimlar — {reports.MONTHS[today.month]}</b> ({start:%d.%m} – {end:%d.%m})\n"]
    total_left = 0
    for e in emps:
        w = wages.get(e["id"]) or dict(days=0, rate=e["daily_rate"], earned=0, paid=0, left=0)
        phone = "📱" if db.worker_user_of(e["id"]) else ""
        line = (f"№{e['id']} <b>{escape(e['name'])}</b> {phone} — bugun: "
                f"{icon.get(status.get(e['id']), '⏳ belgilanmagan')}\n")
        if w["rate"]:
            rest = (f"qoldi <b>{som(w['left'])}</b>" if w["left"] >= 0
                    else f"⚠️ ortiqcha olgan <b>{som(-w['left'])}</b>")
            line += (f"   {w['days']} kun × {som(w['rate'])} = {som(w['earned'])}\n"
                     f"   oldi {som(w['paid'])} · {rest}")
            total_left += max(w["left"], 0)
        else:
            line += f"   ⚠️ kunlik summa yo'q · {w['days']} kun ishlagan · oldi {som(w['paid'])}"
        lines.append(line)
    lines.append(f"\n<b>Bu oy ishchilarga jami berilishi kerak: {som(total_left)}</b>")
    lines.append("\nKunlik summa: /oylik Ism Summa · Bo'shatish: /boshat №\n📱 — botga ulangan")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Davomat (kecha)", callback_data="dv:1"),
                                InlineKeyboardButton("✅ Davomat (bugun)", callback_data="dv:0")],
                               [InlineKeyboardButton("🔗 Ishchini botga ulash", callback_data="wl")]])
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=kb)


ADD_EMP_HELP = ("Ishchi qo'shish: /ishchi_qosh Ibrat\n"
                "Bir nechtasini birdan: /ishchi_qosh Ibrat, Jahongir, Otabek\n"
                "Kunlik stavkani keyin qo'yish mumkin: /oylik Ism summa")


def _split_employee(part: str):
    """'Ibrat' -> ('Ibrat', 0);  'Ibrat 4000000' -> ('Ibrat', 4000000)."""
    words = part.split()
    salary = reports.parse_amount(words[-1]) if len(words) > 1 else None
    if salary:
        words = words[:-1]
    name = " ".join(words).strip()
    return (name[:1].upper() + name[1:], salary or 0) if name else None


@manager_only
async def add_employee_cmd(update, ctx, u):
    raw = " ".join(ctx.args)
    people, skipped = [], []
    for part in raw.split(","):
        got = _split_employee(part)
        if not got:
            continue
        if db.find_employee(got[0]) or any(p[0].lower() == got[0].lower() for p in people):
            skipped.append(got[0])
        else:
            people.append(got)
    note = ""
    if skipped:
        note = ("Bu ismlar ro'yxatda allaqachon bor: " + ", ".join(skipped)
                + ". Farqlash uchun familiyasini qo'shing (masalan Ibrat Karimov).\n")
    if not people:
        return await update.message.reply_text(note + ADD_EMP_HELP)
    item = dict(type="emp", people=people, note=note, by=u["tg_id"], point=None)  # ishchilar tochkaga bog'lanmaydi
    await finish_employee(update.message, item)


async def finish_employee(message, item):
    lines = []
    for name, rate in item["people"]:
        eid = db.add_employee(name, item.get("point"), rate, business_today())
        db.audit(item["by"], "employee_add", f"{eid} {name} {rate}")
        pay = f"kuniga {som(rate)}" if rate else "kunlik stavka belgilanmagan"
        lines.append(f"✅ №{eid} {name} — {pay}")
    head = "Ishga olindi:\n"
    tail = ("\n\nKunlik stavka qo'yish: /oylik Ism summa  (masalan /oylik Jahongir 200000)\n"
            "Ishchini botga ulash (o'zi «Ishga chiqdim» bosishi uchun): /ishchi_ulash")
    await message.reply_text(item.get("note", "") + head + "\n".join(lines) + tail)


SALARY_HELP = ("Kunlik stavka belgilash:\n"
               "• /oylik Jahongir 200000\n"
               "• yoki /oylik ni bosib, ro'yxatdan ishchini tanlang")


async def apply_salary(message, u, emp, sal: int):
    db.set_rate(emp["id"], sal)
    db.audit(u["tg_id"], "rate_set", f"{emp['id']} {sal}")
    await message.reply_text(f"✅ {emp['name']} — kuniga {som(sal)}\n"
                             "Ish haqi = ishlagan kunlar × stavka. Hisob 👥 Xodimlar da ko'rinadi.")


@manager_only
async def salary_cmd(update, ctx, u):
    words = ctx.args
    if not words:  # ro'yxatdan tanlash
        emps = db.employees(point_id=scope(u))
        if not emps:
            return await update.message.reply_text("Avval ishchi qo'shing: /ishchi_qosh Ibrat")
        kb = [[InlineKeyboardButton(f"{e['name']} — " + (f"kuniga {som(e['daily_rate'])}" if e["daily_rate"]
                                                          else "stavka yo'q"),
                                    callback_data=f"sal:{e['id']}")] for e in emps]
        return await update.message.reply_text("Kimning kunlik stavkasini belgilaysiz?",
                                               reply_markup=InlineKeyboardMarkup(kb))
    # "/oylik 3 4500000" (raqam bilan) yoki "/oylik Jahongir 6 000 000" (ism bilan)
    i = next((n for n, w in enumerate(words) if w[:1].isdigit() and n > 0), None)
    if words[0].isdigit() and len(words[0]) <= 4 and len(words) > 1:
        emp, amount = db.get_employee(int(words[0])), " ".join(words[1:])
    elif i is not None:
        emp, amount = db.find_employee(" ".join(words[:i])), " ".join(words[i:])
    else:
        return await update.message.reply_text(SALARY_HELP)
    sal = reports.parse_amount(amount)
    if emp and not in_scope(u, emp["point_id"]):
        emp = None
    if not emp:
        return await update.message.reply_text("Bunday ishchi topilmadi. Ro'yxat: /ishchilar\n\n" + SALARY_HELP)
    if sal is None:
        return await update.message.reply_text(SALARY_HELP)
    await apply_salary(update.message, u, emp, sal)


@manager_only
async def fire_cmd(update, ctx, u):
    if len(ctx.args) != 1 or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /boshat 3")
    eid = int(ctx.args[0])
    e = db.get_employee(eid)
    if not e or not in_scope(u, e["point_id"]) or not db.fire_employee(eid, business_today()):
        return await update.message.reply_text("Bunday faol xodim topilmadi. /ishchilar")
    db.audit(u["tg_id"], "employee_fire", f"{eid} {e['name']}")
    await update.message.reply_text(f"✅ {e['name']} bo'shatildi. Ishlagan kunlari hisobotda ko'rinib turadi.")


# ---------- xarajat va Yandex (xo'jayin) ----------

def exp_preview(item: dict) -> str:
    lines = []
    if item.get("transcript"):
        lines.append(f"📝 <i>{escape(item['transcript'])}</i>")
    day = date.fromisoformat(item["day"])
    pt = f"   🏪 {escape(db.point_name(item['point']))}" if "point" in item else ""
    lines.append(f"📅 {day:%d.%m.%Y}{pt}")
    lines.append("")
    total = 0
    for e in item["expenses"]:
        who = f" — {escape(e['person'])}" if e.get("person") else ""
        qty = f" {escape(e['quantity'])}" if e.get("quantity") else ""
        warn = " ⚠️ ro'yxatda yo'q" if e["category"] == "ishchilar" and e.get("person") and not e.get("employee_id") else ""
        lines.append(f"• [{CATEGORIES[e['category']]}] {escape(e['item'])}{qty}{who}: <b>{som(e['amount'])}</b>{warn}")
        total += e["amount"]
    if item["expenses"]:
        lines.append(f"Xarajat jami: <b>{som(total)}</b>")
    for y in item["yandex"]:
        note = f" ({escape(y['note'])})" if y.get("note") else ""
        lines.append(f"🚚 Yandex tushumi{note}: <b>{som(y['amount'])}</b>")
    return "\n".join(lines)


async def ask_point_or_confirm(message, ctx, item: dict, point_hint=None):
    pts = db.points()
    pid = match_point(point_hint)
    if pid or len(pts) <= 1:
        item["point"] = pid or (pts[0]["id"] if pts else None)
        key = stash(ctx, item)
        return await message.reply_text(exp_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    key = stash(ctx, item)
    await message.reply_text(exp_preview(item) + "\n\n🏪 Qaysi tochka uchun?", parse_mode=HTML,
                             reply_markup=points_kb(f"pt:{key}", with_general=True))


def parsed_expenses(parsed: ai.Parsed) -> list[dict]:
    expenses = []
    for e in parsed.expenses:
        if e.amount <= 0:
            continue
        d = e.model_dump()
        if d["category"] == "ishchilar" and d.get("person"):
            emp = db.find_employee(d["person"])
            if emp:
                d["employee_id"], d["person"] = emp["id"], emp["name"]
        expenses.append(d)
    return expenses


async def handle_parsed(message, ctx, u, parsed: ai.Parsed):
    expenses = parsed_expenses(parsed)
    yandex = [y.model_dump() for y in parsed.yandex if y.amount > 0] if u["role"] == "owner" else []
    if not expenses and not yandex:
        return await message.reply_text("Summa topilmadi. Narsasi va summasi bilan qayta ayting.")
    offset = max(-7, min(0, parsed.day_offset))
    item = dict(type="exp", day=(business_today() + timedelta(days=offset)).isoformat(),
                transcript=parsed.transcript, expenses=expenses, yandex=yandex, by=u["tg_id"])
    if u["role"] in ("cashier", "admin"):
        item["point"] = u["point_id"]
        key = stash(ctx, item)
        return await message.reply_text(exp_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    await ask_point_or_confirm(message, ctx, item, parsed.point)


def ai_context():
    return [p["name"] for p in db.points()], [e["name"] for e in db.employees()]


async def paid_notice(ctx):
    """Pullik Gemini kaliti ishlatilgan kuni xo'jayinlarga bir marta xabar beradi."""
    day = time.strftime("%Y-%m-%d")
    if ai.paid_calls.get(day) and ctx.bot_data.get("paid_noticed") != day:
        ctx.bot_data["paid_noticed"] = day
        await notify_owners(ctx, "ℹ️ Bugun matnlar uchun bepul Gemini limiti tugadi — bot avtomatik pullik kalitga o'tdi. "
                                 "Har bir xabar uchun juda kichik summa yechiladi.")


async def _drop(msg):
    """"⏳" xabarini o'chiradi (o'chmasa — muhim emas)."""
    try:
        await msg.delete()
    except Exception:
        pass


async def expense_voice(update: Update, ctx, u):
    msg = update.message
    media = msg.voice or msg.audio
    if media.duration and media.duration > 300:
        return await msg.reply_text("Ovoz 5 daqiqadan qisqa bo'lsin.")
    wait = await msg.reply_text("⏳ Eshityapman...")
    try:
        f = await media.get_file()
        data = bytes(await f.download_as_bytearray())
        mime = "audio/ogg" if msg.voice else (media.mime_type or "audio/mpeg")
        parsed = await ai.parse_voice(data, mime, *ai_context())
        await paid_notice(ctx)
    except Exception:
        log.exception("voice parse failed")
        await _drop(wait)
        return await msg.reply_text("Ovozni o'qiy olmadim (Gemini xatosi yoki kunlik limit tugadi). "
                                    "Birozdan so'ng qayta yuboring yoki matn qilib yozing.")
    await _drop(wait)
    await handle_parsed(msg, ctx, u, parsed)


async def expense_text(update: Update, ctx, u, text: str):
    try:  # oddiy matnni Gemini'siz, bir zumda tushunamiz
        parsed = quick.parse(text, ai_context()[1])
    except Exception:
        log.exception("quick parse failed")
        parsed = None
    if parsed:
        return await handle_parsed(update.message, ctx, u, parsed)
    wait = await update.message.reply_text("⏳ O'qiyapman...")
    try:
        parsed = await ai.parse_text(text, *ai_context())
        await paid_notice(ctx)
    except Exception:
        log.exception("text parse failed")
        await _drop(wait)
        return await update.message.reply_text("Tushunmadim yoki Gemini javob bermadi. Qayta yozib ko'ring.")
    await _drop(wait)
    await handle_parsed(update.message, ctx, u, parsed)


@owner_only
async def yandex_cmd(update, ctx, u):
    amount = reports.parse_amount(ctx.args[0]) if ctx.args else None
    if not amount:
        return await update.message.reply_text("Format: /yandex 2400000 3-9 noyabr")
    note = " ".join(ctx.args[1:]) or None
    item = dict(type="exp", day=business_today().isoformat(), transcript=None, expenses=[],
                yandex=[dict(amount=amount, note=note)], by=u["tg_id"])
    await ask_point_or_confirm(update.message, ctx, item)


@owner_only
async def owner_sale_cmd(update, ctx, u):
    args = list(ctx.args)
    day = business_today()
    if args and args[0].lower() in ("kecha", "кеча"):
        day -= timedelta(days=1)
        args = args[1:]
    shift = 1
    if args and re.fullmatch(r"(\d)-?smena", args[0].lower()):
        shift = int(args[0][0])
        args = args[1:]
    nums = [reports.parse_amount(a) for a in args]
    if len(nums) != 2 or None in nums or not 1 <= shift <= SHIFTS:
        return await update.message.reply_text("Format: /savdo 2500000 1800000\n"
                                               "Smena bilan: /savdo 2-smena 2500000 1800000\n"
                                               "Kecha uchun: /savdo kecha 1-smena 2500000 1800000")
    item = dict(type="sale", day=day.isoformat(), shift=shift, cash=nums[0], card=nums[1], by=u["tg_id"])
    pts = db.points()
    if not pts:
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    if len(pts) == 1:
        item["point"] = pts[0]["id"]
        key = stash(ctx, item)
        return await update.message.reply_text(sale_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    key = stash(ctx, item)
    await update.message.reply_text("Qaysi tochka savdosi?", reply_markup=points_kb(f"pt:{key}"))


@manager_only
async def last_cmd(update, ctx, u):
    rows = db.last_expenses(10, scope(u))
    ya = db.last_yandex(5) if u["role"] == "owner" else []
    if not rows and not ya:
        return await update.message.reply_text("Hali yozuv yo'q.")
    lines = ["<b>Oxirgi xarajatlar</b>"]
    for r in rows:
        who = f" — {escape(r['person'])}" if r["person"] else ""
        lines.append(f"№{r['id']} {r['day'][8:]}.{r['day'][5:7]} [{CATEGORIES[r['category']]}] "
                     f"{escape(r['item'])}{who}: {som(r['amount'])}")
    if ya:
        lines.append("\n<b>Yandex</b>")
        lines += [f"№{r['id']} {r['day'][8:]}.{r['day'][5:7]} {escape(db.point_name(r['point_id']))}: {som(r['amount'])}"
                  for r in ya]
    lines.append("\nO'chirish: /ochir №" + (" yoki /yandex_ochir №" if u["role"] == "owner" else ""))
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


@manager_only
async def delete_cmd(update, ctx, u):
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /ochir 15")
    old = db.get_expense(int(ctx.args[0]))
    if not old or not in_scope(u, old["point_id"]):
        return await update.message.reply_text("Bunday № topilmadi")
    row = db.delete_expense(int(ctx.args[0]))
    if not row:
        return await update.message.reply_text("Bunday № topilmadi")
    db.audit(u["tg_id"], "expense_delete", f"{row['id']} {row['item']} {row['amount']} {row['day']}")
    await update.message.reply_text(f"🗑 O'chirildi: {row['item']} {som(row['amount'])}")


@owner_only
async def delete_yandex_cmd(update, ctx, u):
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /yandex_ochir 3")
    row = db.delete_yandex(int(ctx.args[0]))
    if not row:
        return await update.message.reply_text("Bunday № topilmadi")
    db.audit(u["tg_id"], "yandex_delete", f"{row['id']} {row['amount']} {row['day']}")
    await update.message.reply_text(f"🗑 O'chirildi: Yandex {som(row['amount'])}")


# ---------- hisobotlar ----------

def report_kb(kind: str, ref: date):
    if len(db.points()) < 2:
        return None
    return points_kb(f"rp:{kind}:{ref.isoformat()}", with_all=True)


def parse_month_arg(args) -> date | None:
    if not args:
        return business_today()
    try:
        y, m = args[0].split("-")
        return date(int(y), int(m), 1)
    except ValueError:
        return None


async def send_report(message, kind: str, ref: date, point_id=None):
    parts = reports.owner_report(kind, ref, point_id)
    await send_parts(message, parts, reply_markup=report_kb(kind, ref) if point_id is None else None)


def report_cmd(kind: str):
    @manager_only
    async def handler(update, ctx, u):
        ref = parse_month_arg(ctx.args) if kind == "oy" else business_today()
        if ref is None:
            return await update.message.reply_text("Format: /oy 2026-10")
        await send_report(update.message, kind, ref, scope(u))
    handler.__name__ = f"report_{kind}"
    return handler


@manager_only
async def excel_cmd(update, ctx, u):
    ref = parse_month_arg(ctx.args)
    if ref is None:
        return await update.message.reply_text("Format: /excel 2026-10")
    await send_excel(update.message, ref, scope(u))


async def send_excel(message, ref: date, point_id=None):
    start, end = reports.month_range(ref.year, ref.month)
    os.makedirs("exports", exist_ok=True)
    suffix = f"_{point_id}" if point_id else ""
    path = f"exports/hisobot_{start:%Y-%m}{suffix}.xlsx"
    reports.excel_report(start, end, path, point_id)
    where = f" — {db.point_name(point_id)}" if point_id else ""
    with open(path, "rb") as fh:
        await message.reply_document(fh, caption=f"{reports.MONTHS[ref.month]} {ref.year}{where} — to'liq hisobot")


# ---------- kassir ----------

def sale_preview(item: dict) -> str:
    day = date.fromisoformat(item["day"])
    shift = item.get("shift", 1)
    lines = [f"🏪 {escape(db.point_name(item['point']))}   🕐 {shift}-smena   📅 {day:%d.%m.%Y}",
             f"💵 Naqd: <b>{som(item['cash'])}</b>",
             f"💳 Karta: <b>{som(item['card'])}</b>",
             f"Jami: <b>{som(item['cash'] + item['card'])}</b>"]
    old = db.get_sale(day, item["point"], shift)
    if old:
        lines.append(f"\n⚠️ Bu smenaga oldin yozilgan: naqd {som(old['cash'])}, karta {som(old['card'])} — almashtiriladi.")
    return "\n".join(lines)


def shift_kb(day: date, point_id: int):
    rows = [[InlineKeyboardButton(f"{n}-smena" + (" ✅" if db.get_sale(day, point_id, n) else ""),
                                  callback_data=f"sh:{n}") for n in range(1, SHIFTS + 1)]]
    if day == business_today():
        rows.append([InlineKeyboardButton("📆 Kechagi kun uchun", callback_data="ky")])
    return InlineKeyboardMarkup(rows)


async def start_income(message, ctx, u, point_id, day: date):
    head = f"💰 Kirim — 🏪 {escape(db.point_name(point_id))}, 📅 {day:%d.%m.%Y}"
    if SHIFTS == 1:
        ctx.user_data["sale"] = dict(day=day.isoformat(), step="cash", point=point_id, shift=1)
        return await message.reply_text(f"{head}\n\n💵 Naqd:\n(masalan: 3456000)\n\nBekor qilish: /bekor",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                             "📆 Kechagi kun uchun", callback_data="ky")]])
                                         if day == business_today() else None)
    ctx.user_data["sale"] = dict(day=day.isoformat(), step="shift", point=point_id)
    await message.reply_text(f"{head}\n\n🕐 Smenani tanlang:", reply_markup=shift_kb(day, point_id))


async def ask_cash(message, st: dict):
    day = date.fromisoformat(st["day"])
    await message.reply_text(
        f"💰 {escape(db.point_name(st['point']))}, {st['shift']}-smena, 📅 {day:%d.%m.%Y}\n\n"
        "💵 Naqd:\n(masalan: 3456000)\n\nBekor qilish: /bekor")


async def income_button(update: Update, ctx, u):
    if u["role"] in ("cashier", "admin"):
        return await start_income(update.message, ctx, u, u["point_id"], business_today())
    pts = db.points()
    if not pts:
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    if len(pts) == 1:
        return await start_income(update.message, ctx, u, pts[0]["id"], business_today())
    await update.message.reply_text("💰 Qaysi tochka kirimi?", reply_markup=points_kb("kp"))


async def income_step(update: Update, ctx, u, st: dict, text: str):
    if st["step"] == "shift":
        return await update.message.reply_text("Avval smenani tanlang — yuqoridagi tugmalardan birini bosing.\n"
                                               "Bekor qilish: /bekor")
    amount = reports.parse_amount(text)
    if amount is None:
        return await update.message.reply_text("Faqat raqam yozing, masalan: 3456000  (bekor: /bekor)")
    if st["step"] == "cash":
        st.update(cash=amount, step="card")
        return await update.message.reply_text("💳 Karta:\n(terminal/Click/Payme, masalan: 870000)")
    ctx.user_data.pop("sale", None)
    item = dict(type="sale", day=st["day"], point=st["point"], shift=st["shift"], cash=st["cash"], card=amount,
                by=u["tg_id"])
    key = stash(ctx, item)
    await update.message.reply_text(sale_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("sale", None)
    ctx.user_data.pop("salary_for", None)
    ctx.user_data.pop("close", None)
    ctx.user_data.pop("debt", None)
    await update.message.reply_text("Bekor qilindi.")


async def save_sale(ctx, item: dict):
    day = date.fromisoformat(item["day"])
    shift = item.get("shift", 1)
    db.upsert_sale(day, item["point"], item["cash"], item["card"], item["by"], shift)
    db.audit(item["by"], "sale", f"{item['point']} {item['day']} s{shift} {item['cash']} {item['card']}")
    if NOTIFY_OWNERS_ON_SALES:
        by = db.get_user(item["by"])
        text = (f"💰 Kirim: {escape(db.point_name(item['point']))}, {shift}-smena, {day:%d.%m}: naqd {som(item['cash'])}, "
                f"karta {som(item['card'])}, jami <b>{som(item['cash'] + item['card'])}</b>"
                f"\n<i>kiritdi: {escape((by['name'] if by else None) or str(item['by']))}</i>")
        await notify_owners(ctx, text, skip=item["by"], point_id=item["point"])


async def notify_owners(ctx, text: str, skip=None, point_id=None):
    """Xo'jayinlarga xabar."""
    for oid in db.owner_ids():
        if oid == skip:
            continue
        try:
            await ctx.bot.send_message(oid, text, parse_mode=HTML)
        except Exception:
            log.warning("owner %s notify failed", oid)


# ---------- davomat ----------

def att_kb(st: dict) -> InlineKeyboardMarkup:
    rows, row = [], []
    for e in db.staff_for_point(st["point"]):
        row.append(InlineKeyboardButton(("✅ " if e["id"] in st["ids"] else "⬜ ") + e["name"],
                                        callback_data=f"at:{e['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(f"✔️ Tayyor ({len(st['ids'])} kishi)", callback_data="at:done")])
    return InlineKeyboardMarkup(rows)


def att_text(st: dict) -> str:
    day = date.fromisoformat(st["day"])
    where = f" — 🏪 {escape(db.point_name(st['point']))}" if st["point"] else ""
    return (f"👥 <b>{day:%d.%m.%Y} kuni kimlar ishladi?</b>{where}\n"
            "Ishlaganlarni bosib belgilang, keyin «Tayyor».")


def att_names(ids) -> str:
    ids = set(ids)
    names = [e["name"] for e in db.employees(active_only=False) if e["id"] in ids]
    return f"{', '.join(names)} ({len(names)} kishi)" if names else "hech kim"


@owner_only
async def attendance_cmd(update, ctx, u):
    back = 0 if ctx.args and ctx.args[0].lower() in ("bugun", "бугун") else 1
    await attendance_start(update.message, ctx, u, back)


async def attendance_start(message, ctx, u, back: int):
    day = business_today() - timedelta(days=back)
    await attendance_open(message, ctx, None, day)   # ishchilar tochkaga bog'lanmagan — hammasi bitta ro'yxat


async def attendance_open(message, ctx, point_id: int, day: date):
    if not db.staff_for_point(point_id):
        return await message.reply_text("Ishchi yo'q. Qo'shish: /ishchi_qosh Ism")
    st = dict(day=day.isoformat(), point=point_id, ids=sorted(db.attendance_of(day, point_id)), mode="owner")
    ctx.user_data["att"] = st
    await message.reply_text(att_text(st), parse_mode=HTML, reply_markup=att_kb(st))


async def attendance_button(q, ctx, u, arg: str):
    st = ctx.user_data.get("att")
    if not st:
        await q.answer("Bu xabar eskirgan", show_alert=True)
        return await q.edit_message_reply_markup(None)
    if arg != "done":
        st["ids"] = sorted(set(st["ids"]) ^ {int(arg)})
        await q.answer()
        return await q.edit_message_reply_markup(att_kb(st))
    await q.answer()
    ctx.user_data.pop("att", None)
    await q.edit_message_text(att_text(st).split("\n")[0] + f"\n✅ {escape(att_names(st['ids']))}", parse_mode=HTML)
    if st["mode"] == "close":  # admin kunlik hisobotining davomi
        close = ctx.user_data.get("close")
        if not close:
            return await q.message.reply_text("Bu xabar eskirgan. «📝 Kunlik hisobot» ni qayta bosing.")
        close.update(att=st["ids"], step="exp")
        return await q.message.reply_text(CLOSE_EXP_PROMPT, parse_mode=HTML, reply_markup=close_exp_kb(False))
    db.set_attendance(date.fromisoformat(st["day"]), st["point"], st["ids"], u["tg_id"])
    db.audit(u["tg_id"], "attendance", f"{st['point']} {st['day']} {st['ids']}")


# ---------- ishchi: kunlik belgi ----------

def worker_summary(emp, today: date) -> str:
    start, end = month_period(today)
    w = next((r for r in reports.employee_payments(start, end) if r["id"] == emp["id"]), None)
    days = db.worked_days(emp["id"], start, end)
    dates = ", ".join(d[8:] for d in days) or "—"
    lines = [f"📊 <b>{escape(emp['name'])} — {reports.MONTHS[today.month]}</b>",
             f"Ishlagan kunlar: <b>{len(days)}</b> ({dates})"]
    if w and w["rate"]:
        lines += [f"Kunlik: {som(w['rate'])}",
                  f"Hisoblandi: {len(days)} × {som(w['rate'])} = <b>{som(w['earned'])}</b>",
                  f"Oldingiz: {som(w['paid'])}",
                  f"Qoldi: <b>{som(w['left'])}</b>" if w["left"] >= 0 else f"Ortiqcha olgansiz: {som(-w['left'])}"]
    else:
        lines.append("Kunlik summangiz hali belgilanmagan — xo'jayinga ayting.")
    return "\n".join(lines)


async def worker_text(update, ctx, u, text: str):
    emp = db.get_employee(u["employee_id"]) if u["employee_id"] else None
    if not emp or not emp["active"]:
        return await update.message.reply_text("Siz ishchilar ro'yxatida yo'qsiz. Xo'jayinga murojaat qiling.")
    today = business_today()
    if text in (W_IN, W_OFF):
        worked = text == W_IN
        db.mark_day(today, emp["id"], worked, u["tg_id"])
        n = len(db.worked_days(emp["id"], *month_period(today)))
        msg = "✅ Belgilandi: bugun ishga chiqdingiz." if worked else "🏖 Belgilandi: bugun dam olasiz."
        return await update.message.reply_text(f"{msg} ({today:%d.%m})\nBu oy ishlagan kunlar: {n}",
                                               reply_markup=WORKER_KB)
    if text == W_ME:
        return await update.message.reply_text(worker_summary(emp, today), parse_mode=HTML, reply_markup=WORKER_KB)
    await update.message.reply_text("Pastdagi tugmalardan birini bosing.", reply_markup=WORKER_KB)


@owner_only
async def worker_link_cmd(update, ctx, u):
    await worker_link_list(update.message)


async def worker_link_list(message):
    emps = db.employees()
    if not emps:
        return await message.reply_text("Avval ishchi qo'shing: /ishchi_qosh Ism")
    kb = [[InlineKeyboardButton(e["name"] + (" (📱 ulangan)" if db.worker_user_of(e["id"]) else ""),
                                callback_data=f"wi:{e['id']}")] for e in emps]
    await message.reply_text("🔗 Qaysi ishchini botga ulaymiz? Bot havola beradi, uni o'sha ishchiga yuborasiz.",
                             reply_markup=InlineKeyboardMarkup(kb))


async def job_worker_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    today = business_today()
    status = db.day_status(today)
    for e in db.employees():
        w = db.worker_user_of(e["id"])
        if not w or e["id"] in status:
            continue
        try:
            await ctx.bot.send_message(w["tg_id"], "Bugun ishga chiqdingizmi? Tugmani bosing 👇", reply_markup=WORKER_KB)
        except Exception:
            log.warning("worker %s reminder failed", w["tg_id"])


# ---------- qarzlar (xo'jayin) ----------

DEBT_RE = re.compile(r"^(?P<name>.+?)\s+(?P<amount>\d[\d\s.,]*(?:\s*(?:ming|mln|million|k))?)"
                     r"(?:\s*(?:so'm|som|sum))?(?:\s+(?P<note>.+))?$", re.IGNORECASE)


def debts_text() -> str:
    rows = db.debt_balances()
    if not rows:
        return "📒 <b>Qarzlar</b>\n\nHozir hech kimga qarzimiz yo'q ✅"
    lines = ["📒 <b>Qarzlarimiz</b>\n"]
    for r in rows:
        last = f" · oxirgi: {r['last_day'][8:]}.{r['last_day'][5:7]}" if r["last_day"] else ""
        if r["balance"] > 0:
            lines.append(f"• <b>{escape(r['name'])}</b> — {som(r['balance'])}{last}")
        else:
            lines.append(f"• <b>{escape(r['name'])}</b> — ortiqcha to'langan {som(-r['balance'])}{last}")
    total = sum(r["balance"] for r in rows if r["balance"] > 0)
    lines.append(f"\n<b>Jami qarz: {som(total)}</b>")
    return "\n".join(lines)


def debts_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Qarz yozish", callback_data="qz:add"),
         InlineKeyboardButton("💵 Qarz to'lash", callback_data="qz:pay")],
        [InlineKeyboardButton("📜 Tarix", callback_data="qz:hist")]])


@owner_only
async def debts_cmd(update, ctx, u):
    ctx.user_data.pop("debt", None)
    await update.message.reply_text(debts_text(), parse_mode=HTML, reply_markup=debts_kb())


def creditors_kb(prefix: str, only_open: bool):
    rows = db.debt_balances(only_open=only_open)
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        f"{r['name']} — {som(r['balance'])}"[:60], callback_data=f"{prefix}:{r['id']}")] for r in rows[:30]])


async def debt_text(update, ctx, u, st: dict, text: str):
    msg = update.message
    if st["step"] == "add":
        m = DEBT_RE.match(text.strip())
        amount = reports.parse_amount(m["amount"]) if m else None
        if not m or not amount:
            return await msg.reply_text("Masalan: <i>Go'shtchi Akmal 2500000 mol go'shti 20 kg</i>\n"
                                        "(kim — summa — izoh). Bekor qilish: /bekor", parse_mode=HTML)
        ctx.user_data.pop("debt", None)
        name = " ".join(m["name"].split())
        with db.conn() as c:  # oldin yozilgan bo'lsa — ro'yxatdagi nomi bilan
            known = c.execute("SELECT name FROM creditors WHERE name=?", (name,)).fetchone()
        name = known["name"] if known else name[:1].upper() + name[1:]
        item = dict(type="debt", name=name, amount=amount, note=(m["note"] or "").strip() or None,
                    day=business_today().isoformat(), by=u["tg_id"])
        key = stash(ctx, item)
        return await msg.reply_text(debt_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    if st["step"] == "pay":
        amount = reports.parse_amount(text)
        if not amount:
            return await msg.reply_text("Faqat summani yozing, masalan 1000000. Bekor qilish: /bekor")
        ctx.user_data.pop("debt", None)
        return await debt_pay_preview(msg, ctx, u, st["cid"], amount)


def debt_preview(item: dict) -> str:
    if item["type"] == "debt":
        old = 0
        with db.conn() as c:
            r = c.execute("SELECT id FROM creditors WHERE name=?", (item["name"],)).fetchone()
        if r:
            old = db.debt_balance(r["id"])
        note = f"\n📝 {escape(item['note'])}" if item.get("note") else ""
        return (f"➕ <b>Qarz yozish</b>\n\n👤 {escape(item['name'])}\n💰 <b>{som(item['amount'])}</b>{note}\n\n"
                f"Qarz: {som(old)} → <b>{som(old + item['amount'])}</b>")
    cr = db.get_creditor(item["cid"])
    old = db.debt_balance(item["cid"])
    return (f"💵 <b>Qarz to'lash</b>\n\n👤 {escape(cr['name'])}\n💰 <b>{som(item['amount'])}</b>\n\n"
            f"Qarz: {som(old)} → <b>{som(old - item['amount'])}</b>")


async def debt_pay_preview(message, ctx, u, cid: int, amount: int):
    bal = db.debt_balance(cid)
    if amount > bal:
        return await message.reply_text(f"Qarz {som(bal)}, siz {som(amount)} yozdingiz — qarzdan ko'p. "
                                         "To'g'ri summani yozing: «💵 Qarz to'lash».")
    item = dict(type="debtpay", cid=cid, amount=amount, day=business_today().isoformat(), by=u["tg_id"])
    key = stash(ctx, item)
    await message.reply_text(debt_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))


async def save_debt(u, item: dict) -> str:
    day = date.fromisoformat(item["day"])
    if item["type"] == "debt":
        cid = db.creditor_id(item["name"])
        mid = db.add_debt_move(cid, day, item["amount"], item.get("note"), u["tg_id"])
    else:
        cid = item["cid"]
        mid = db.add_debt_move(cid, day, -item["amount"], "to'lov", u["tg_id"])
    db.audit(u["tg_id"], item["type"], f"{mid} {cid} {item['amount']}")
    return f"✅ Saqlandi (№{mid}). {db.get_creditor(cid)['name']} — qolgan qarz: <b>{som(db.debt_balance(cid))}</b>"


@owner_only
async def debt_delete_cmd(update, ctx, u):
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /qarz_ochir 12   (№ ni «📜 Tarix» da ko'rasiz)")
    row = db.delete_debt_move(int(ctx.args[0]))
    if not row:
        return await update.message.reply_text("Bunday № topilmadi.")
    db.audit(u["tg_id"], "debt_delete", f"{row['id']} {row['name']} {row['amount']}")
    kind = "qarz" if row["amount"] > 0 else "to'lov"
    await update.message.reply_text(f"🗑 O'chirildi: {row['name']} — {kind} {som(abs(row['amount']))}. "
                                    f"Qolgan qarz: {som(db.debt_balance(row['creditor_id']))}")


# ---------- admin: kunlik hisobot ----------

CLOSE_EXP_PROMPT = ("💸 <b>Xarajatlar</b> — matn yoki ovoz bilan yozing:\n"
                    "<i>ishchilar 400000, non 120000, salfetka 30000</i>\n\n"
                    "Bir nechta xabar yuborsangiz ham bo'ladi — hammasi qo'shiladi.")


def open_days(point_id: int) -> list[date]:
    """Hisoboti hali yozilmagan oxirgi 3 kun (kechadan boshlab)."""
    today = business_today()
    days = [today - timedelta(days=i) for i in (1, 2, 3)]
    return [d for d in days if not db.get_closing(d, point_id)]


async def close_start(message, ctx, u):
    ctx.user_data.pop("close", None)
    days = open_days(u["point_id"])
    if not days:
        return await message.reply_text("✅ Kechagi hisobot allaqachon yozilgan.\n"
                                        "Xato bo'lsa, xo'jayinga ayting — u o'chirib beradi, keyin qayta yozasiz.")
    if len(days) == 1:
        return await close_begin(message, ctx, u, days[0])
    kb = [[InlineKeyboardButton(("Kecha, " if d == business_today() - timedelta(days=1) else "") + f"{d:%d.%m.%Y}",
                                callback_data=f"cd:{d.isoformat()}")] for d in days]
    await message.reply_text("Qaysi kun hisobotini yozasiz? (yozilmagan kunlar)", reply_markup=InlineKeyboardMarkup(kb))


async def close_begin(message, ctx, u, day: date):
    ctx.user_data["close"] = dict(day=day.isoformat(), point=u["point_id"], step="total", expenses=[])
    await message.reply_text(
        f"📝 <b>Kunlik hisobot</b> — 🏪 {escape(db.point_name(u['point_id']))}, 📅 {day:%d.%m.%Y}\n\n"
        "💰 <b>Jami savdo</b> (1 va 2-smena birga):\n(masalan: 12500000)\n\nBekor qilish: /bekor",
        parse_mode=HTML)


def close_exp_kb(has_items: bool):
    rows = [[InlineKeyboardButton("➡️ Davom etish" if has_items else "Xarajat yo'q ➡️", callback_data="cx:next")]]
    if has_items:
        rows.append([InlineKeyboardButton("🗑 Ro'yxatni tozalab, qayta yozish", callback_data="cx:clear")])
    return InlineKeyboardMarkup(rows)


def close_exp_list(st: dict) -> str:
    if not st["expenses"]:
        return "Xarajat yo'q."
    lines = [f"• [{CATEGORIES[e['category']]}] {escape(e['item'])}"
             + (f" — {escape(e['person'])}" if e.get("person") else "") + f": <b>{som(e['amount'])}</b>"
             for e in st["expenses"]]
    lines.append(f"Xarajat jami: <b>{som(sum(e['amount'] for e in st['expenses']))}</b>")
    return "\n".join(lines)


def close_preview(st: dict) -> str:
    day = date.fromisoformat(st["day"])
    spent = sum(e["amount"] for e in st["expenses"])
    expected = st["total"] - st["card"] - spent
    diff = st["cash"] - expected
    check = ("✅ Kassa to'g'ri — farq yo'q" if diff == 0 else
             f"⚠️ Kassada <b>{som(-diff)}</b> kam" if diff < 0 else f"⚠️ Kassada <b>{som(diff)}</b> ortiqcha")
    return (f"📝 <b>Kunlik hisobot</b> — 🏪 {escape(db.point_name(st['point']))}, 📅 {day:%d.%m.%Y}\n\n"
            f"💰 Jami savdo: <b>{som(st['total'])}</b>\n"
            + (f"👥 Ishladi: {escape(att_names(st['att']))}\n" if "att" in st else "") + "\n"
            f"💸 Xarajatlar:\n{close_exp_list(st)}\n\n"
            f"💳 Karta / schet: <b>{som(st['card'])}</b>\n"
            f"💵 Kassada naqd: <b>{som(st['cash'])}</b>\n\n"
            f"Hisob bo'yicha naqd: {som(st['total'])} − {som(st['card'])} − {som(spent)} = <b>{som(expected)}</b>\n"
            f"{check}")


async def close_add_expenses(message, ctx, u, st: dict, parsed):
    added = parsed_expenses(parsed) if parsed else []
    if not added:
        return await message.reply_text("Summa topilmadi. Masalan: <i>non 120000, salfetka 30000</i>",
                                        parse_mode=HTML, reply_markup=close_exp_kb(bool(st["expenses"])))
    st["expenses"] += added
    await message.reply_text(close_exp_list(st) + "\n\nYana bo'lsa yozing, bo'lmasa «Davom etish» ni bosing.",
                             parse_mode=HTML, reply_markup=close_exp_kb(True))


async def close_text(update, ctx, u, st: dict, text: str):
    msg = update.message
    if st["step"] == "att":
        return await msg.reply_text("Avval yuqoridagi ro'yxatdan kimlar ishlaganini belgilab, «Tayyor» ni bosing.")
    if st["step"] == "exp":
        parsed = quick.parse(text, ai_context()[1])
        if not parsed:
            wait = await msg.reply_text("⏳ O'qiyapman...")
            try:
                parsed = await ai.parse_text(text, *ai_context())
            except Exception:
                log.exception("close text parse failed")
                parsed = None
            await _drop(wait)
        return await close_add_expenses(msg, ctx, u, st, parsed)
    amount = reports.parse_amount(text)
    if amount is None:
        return await msg.reply_text("Faqat raqam yozing, masalan: 12500000  (bekor: /bekor)")
    if st["step"] == "total":
        st["total"] = amount
        if db.staff_for_point(st["point"]):  # avval davomat, keyin xarajatlar
            st["step"] = "att"
            att = dict(day=st["day"], point=st["point"], ids=[], mode="close")
            ctx.user_data["att"] = att
            return await msg.reply_text(att_text(att), parse_mode=HTML, reply_markup=att_kb(att))
        st["step"] = "exp"
        return await msg.reply_text(CLOSE_EXP_PROMPT, parse_mode=HTML, reply_markup=close_exp_kb(False))
    if st["step"] == "card":
        st.update(card=amount, step="cash")
        return await msg.reply_text("💵 <b>Kassada qolgan naqd</b>:\n(masalan: 7350000)", parse_mode=HTML)
    if st["step"] == "cash":
        st["cash"] = amount
        ctx.user_data.pop("close", None)
        item = dict(type="close", by=u["tg_id"], **st)
        key = stash(ctx, item)
        return await msg.reply_text(close_preview(item) + "\n\nSaqlangandan keyin o'zgartirib bo'lmaydi.",
                                    parse_mode=HTML, reply_markup=confirm_kb(key))


async def close_voice(update, ctx, u, st: dict):
    msg = update.message
    if st["step"] != "exp":
        return await msg.reply_text("Bu bosqichda faqat raqam yozing.")
    media = msg.voice or msg.audio
    wait = await msg.reply_text("⏳ Eshityapman...")
    try:
        f = await media.get_file()
        data = bytes(await f.download_as_bytearray())
        parsed = await ai.parse_voice(data, "audio/ogg" if msg.voice else (media.mime_type or "audio/mpeg"),
                                      *ai_context())
    except Exception:
        log.exception("close voice parse failed")
        parsed = None
    await _drop(wait)
    await close_add_expenses(msg, ctx, u, st, parsed)


async def save_close(ctx, u, item: dict) -> str:
    day = date.fromisoformat(item["day"])
    if db.get_closing(day, item["point"]):
        return "⚠️ Bu kun hisoboti allaqachon yozilgan. O'zgartirish uchun xo'jayinga ayting."
    cid = db.save_closing(day, item["point"], item["total"], item["card"], item["cash"], item["expenses"], u["tg_id"])
    if "att" in item:
        db.set_attendance(day, item["point"], item["att"], u["tg_id"])
    db.audit(u["tg_id"], "closing", f"{cid} {item['point']} {item['day']} {item['total']} {item['card']} {item['cash']}")
    await notify_owners(ctx, f"📝 <b>{escape(u['name'] or str(u['tg_id']))}</b> kunlik hisobot yozdi (№{cid}):\n\n"
                        + close_preview(item), skip=u["tg_id"])
    return f"✅ Saqlandi (№{cid}). Rahmat!"


@owner_only
async def closings_cmd(update, ctx, u):
    rows = db.last_closings(10)
    if not rows:
        return await update.message.reply_text("Hali kunlik hisobot yo'q. Admin qo'shish: /admin_qosh")
    lines = ["<b>Oxirgi kunlik hisobotlar</b>"]
    for c in rows:
        diff = c["cash_left"] - (c["total"] - c["card"] - c["spent"])
        mark = "✅" if diff == 0 else f"⚠️ {'kam' if diff < 0 else 'ortiq'} {som(abs(diff))}"
        lines.append(f"№{c['id']} {c['day'][8:]}.{c['day'][5:7]} {escape(db.point_name(c['point_id']))}: "
                     f"savdo {som(c['total'])}, naqd {som(c['cash_left'])} {mark}")
    lines.append("\nO'chirish (admin qayta yozadi): /kunlik_ochir №")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


@owner_only
async def closing_delete_cmd(update, ctx, u):
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /kunlik_ochir 3   (ro'yxat: /kunlik)")
    row = db.delete_closing(int(ctx.args[0]))
    if not row:
        return await update.message.reply_text("Bunday № topilmadi. /kunlik")
    db.audit(u["tg_id"], "closing_delete", f"{row['id']} {row['point_id']} {row['day']}")
    await update.message.reply_text(f"🗑 {row['day']} — {db.point_name(row['point_id'])} hisoboti o'chirildi "
                                    "(savdo va xarajatlari bilan). Admin endi qayta yoza oladi.")


async def job_admin_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    day = business_today() - timedelta(days=1)
    for p in db.points():
        if db.get_closing(day, p["id"]):
            continue
        for aid in db.admins_of(p["id"]):
            try:
                await ctx.bot.send_message(aid, f"⏰ Kechagi ({day:%d.%m}) hisobot hali yozilmagan: «📝 Kunlik hisobot»")
            except Exception:
                log.warning("admin %s reminder failed", aid)


# ---------- umumiy xabar marshrutlari ----------

async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    if u["role"] == "worker":
        return await update.message.reply_text("Pastdagi tugmalardan birini bosing.", reply_markup=WORKER_KB)
    if u["role"] == "admin":
        st = ctx.user_data.get("close")
        if st:
            return await close_voice(update, ctx, u, st)
        return await update.message.reply_text("Avval «📝 Kunlik hisobot» ni bosing.", reply_markup=ADMIN_KB)
    ctx.user_data.pop("sale", None)
    await expense_voice(update, ctx, u)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    text = update.message.text.strip()
    if u["role"] == "worker":
        return await worker_text(update, ctx, u, text)
    if u["role"] == "admin":
        if text == B_DAY:
            return await close_start(update.message, ctx, u)
        st = ctx.user_data.get("close")
        if st:
            return await close_text(update, ctx, u, st, text)
        return await update.message.reply_text("Kechagi kun hisobotini yozish uchun «📝 Kunlik hisobot» ni bosing.",
                                               reply_markup=ADMIN_KB)
    if text in (B_EXP, B_INC):
        ctx.user_data.pop("salary_for", None)
    if text == B_EXP:
        ctx.user_data.pop("sale", None)
        return await update.message.reply_text(EXP_PROMPT, parse_mode=HTML)
    if text == B_INC:
        ctx.user_data.pop("sale", None)
        return await income_button(update, ctx, u)
    st = ctx.user_data.get("sale")
    if st:
        return await income_step(update, ctx, u, st, text)
    if text in (O_TODAY, O_WEEK, O_MONTH, O_XLSX, O_STAFF, O_ADMIN, O_DEBT, B_EXP, B_INC):
        ctx.user_data.pop("salary_for", None)
        ctx.user_data.pop("debt", None)
    if u["role"] == "owner" and ctx.user_data.get("debt"):
        return await debt_text(update, ctx, u, ctx.user_data["debt"], text)
    if u["role"] in MANAGERS and ctx.user_data.get("salary_for"):
        eid = ctx.user_data["salary_for"]
        sal = reports.parse_amount(text)
        emp = db.get_employee(eid)
        if sal is None or not emp:
            return await update.message.reply_text("Faqat summani yozing, masalan 200000. Bekor qilish: /bekor")
        ctx.user_data.pop("salary_for", None)
        return await apply_salary(update.message, u, emp, sal)
    if u["role"] == "cashier":
        if reports.parse_amount(text) is not None:
            return await update.message.reply_text(
                "Kirim yozish uchun «💰 Kirim» ni, xarajat uchun «💸 Xarajat» ni bosing.", reply_markup=CASHIER_KB)
        return await expense_text(update, ctx, u, text)

    ref, pid = business_today(), scope(u)
    if text == O_TODAY:
        return await send_report(update.message, "bugun", ref, pid)
    if text == O_WEEK:
        return await send_report(update.message, "hafta", ref, pid)
    if text == O_MONTH:
        return await send_report(update.message, "oy", ref, pid)
    if text == O_XLSX:
        return await send_excel(update.message, ref, pid)
    if text == O_STAFF:
        return await staff_cmd(update, ctx)
    if text == O_ADMIN:
        return await update.message.reply_text(role_help(u), parse_mode=HTML)
    if text == O_DEBT:
        return await debts_cmd(update, ctx)
    await expense_text(update, ctx, u, text)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = current_user(update)
    if not u:
        return await q.answer("Ruxsat yo'q", show_alert=True)
    parts = q.data.split(":")
    action = parts[0]
    pending = ctx.bot_data.setdefault("pending", {})

    if action in ("ok", "no"):
        item = pending.pop(parts[1], None)
        if not item or item["by"] != u["tg_id"]:
            await q.answer("Bu xabar eskirgan", show_alert=True)
            return await q.edit_message_reply_markup(None)
        if action == "no":
            await q.answer("Bekor qilindi")
            return await q.edit_message_text("❌ Bekor qilindi")
        if item["type"] == "exp":
            day = date.fromisoformat(item["day"])
            ids = db.add_expenses(day, item["point"], item["expenses"], u["tg_id"]) if item["expenses"] else []
            for y in item["yandex"]:
                db.add_yandex(day, item["point"], y["amount"], y.get("note"), u["tg_id"])
            suffix = f"\n\n✅ Saqlandi" + (f" (№{ids[0]}–{ids[-1]})" if ids else "")
            await q.edit_message_text(exp_preview(item) + suffix, parse_mode=HTML)
            if u["role"] in ("cashier", "admin") and NOTIFY_OWNERS_ON_SALES:
                note = f"💸 <b>{escape(u['name'] or str(u['tg_id']))}</b> xarajat yozdi:\n" + exp_preview(item)
                await notify_owners(ctx, note, skip=u["tg_id"], point_id=item.get("point"))
        elif item["type"] == "sale":
            text = sale_preview(item)
            await save_sale(ctx, item)
            await q.edit_message_text(text.split("\n\n⚠️")[0] + "\n\n✅ Saqlandi", parse_mode=HTML)
        elif item["type"] in ("debt", "debtpay"):
            result = await save_debt(u, item)
            await q.edit_message_text(debt_preview(item).split("\n\nQarz:")[0] + "\n\n" + result, parse_mode=HTML)
        elif item["type"] == "close":
            result = await save_close(ctx, u, item)
            await q.edit_message_text(close_preview(item) + "\n\n" + result, parse_mode=HTML)
        return await q.answer("Saqlandi")

    if action == "pt":  # pt:<key>:<point_id>
        item = pending.get(parts[1])
        if not item or item["by"] != u["tg_id"]:
            await q.answer("Bu xabar eskirgan", show_alert=True)
            return await q.edit_message_reply_markup(None)
        item["point"] = int(parts[2]) or None
        await q.answer()
        if item["type"] == "emp":
            pending.pop(parts[1], None)
            await q.edit_message_reply_markup(None)
            return await finish_employee(q.message, item)
        preview = exp_preview(item) if item["type"] == "exp" else sale_preview(item)
        return await q.edit_message_text(preview, parse_mode=HTML, reply_markup=confirm_kb(parts[1]))

    if action == "at":  # at:<employee_id> / at:done — davomat belgilash
        return await attendance_button(q, ctx, u, parts[1])

    if action == "cd" and u["role"] == "admin":  # cd:<sana> — kunlik hisobot kuni tanlandi
        await q.answer()
        await q.edit_message_reply_markup(None)
        day = date.fromisoformat(parts[1])
        if day not in open_days(u["point_id"]):
            return await q.message.reply_text("Bu kun hisoboti allaqachon yozilgan.")
        return await close_begin(q.message, ctx, u, day)

    if action == "cx" and u["role"] == "admin":  # cx:next / cx:clear — xarajatlar bosqichi
        st = ctx.user_data.get("close")
        await q.answer()
        await q.edit_message_reply_markup(None)
        if not st or st["step"] != "exp":
            return await q.message.reply_text("Bu xabar eskirgan. «📝 Kunlik hisobot» ni qayta bosing.")
        if parts[1] == "clear":
            st["expenses"] = []
            return await q.message.reply_text("Ro'yxat tozalandi.\n\n" + CLOSE_EXP_PROMPT, parse_mode=HTML,
                                              reply_markup=close_exp_kb(False))
        st["step"] = "card"
        return await q.message.reply_text("💳 <b>Karta / schetga tushgani</b>:\n(masalan: 4000000)", parse_mode=HTML)

    if action == "sh":  # sh:<smena> — kirim uchun smena tanlandi
        st = ctx.user_data.get("sale")
        await q.answer()
        await q.edit_message_reply_markup(None)
        if not st:
            return await q.message.reply_text("Bu xabar eskirgan. «💰 Kirim» ni qayta bosing.")
        st.update(shift=int(parts[1]), step="cash")
        return await ask_cash(q.message, st)

    if action == "ky":  # kirim: kechagi kun uchun
        st = ctx.user_data.get("sale")
        await q.answer()
        await q.edit_message_reply_markup(None)
        if not st:
            return
        return await start_income(q.message, ctx, u, st["point"], business_today() - timedelta(days=1))

    if u["role"] not in MANAGERS:
        return await q.answer("Ruxsat yo'q", show_alert=True)

    if action == "sal":  # sal:<employee_id> — oylik summasini kutamiz
        emp = db.get_employee(int(parts[1]))
        await q.answer()
        await q.edit_message_reply_markup(None)
        if not emp or not in_scope(u, emp["point_id"]):
            return await q.message.reply_text("Ishchi topilmadi.")
        ctx.user_data.pop("sale", None)
        ctx.user_data["salary_for"] = emp["id"]
        return await q.message.reply_text(f"{emp['name']} kunlik stavkasini yozing (masalan 200000):")

    if action == "rp":  # rp:<kind>:<ref>:<point_id>
        await q.answer()
        pid = scope(u) or (int(parts[3]) or None)
        return await send_report(q.message, parts[1], date.fromisoformat(parts[2]), pid)

    # quyidagilar — faqat xo'jayin
    if u["role"] != "owner":
        return await q.answer("Ruxsat yo'q", show_alert=True)

    if action == "tz":  # tz:yes / tz:no — hamma yozuvlarni o'chirish
        await q.answer()
        await q.edit_message_reply_markup(None)
        if parts[1] != "yes" or u["tg_id"] not in OWNER_IDS:
            return await q.message.reply_text("Bekor qilindi. Hech narsa o'chirilmadi.")
        n = db.wipe_records()
        db.audit(u["tg_id"], "wipe_records", str(n))
        return await q.message.reply_text(
            f"🧹 O'chirildi: {n['expenses']} ta xarajat, {n['sales']} ta kirim, {n['yandex']} ta Yandex, "
            f"{n['closings']} ta kunlik hisobot.\n"
            "Tochkalar, ishchilar va foydalanuvchilar joyida qoldi.")

    if action == "wl":  # ishchini botga ulash — ro'yxat
        await q.answer()
        return await worker_link_list(q.message)

    if action == "wi":  # wi:<employee_id> — ishchi uchun taklif havolasi
        await q.answer()
        await q.edit_message_reply_markup(None)
        return await send_invite(q.message, ctx, u, "worker", None, int(parts[1]))

    if action == "dv":  # dv:<necha kun oldin> — davomat (Xodimlar ichidan)
        await q.answer()
        return await attendance_start(q.message, ctx, u, int(parts[1]))

    if action == "dp":  # dp:<point_id>:<sana>
        await q.answer()
        await q.edit_message_reply_markup(None)
        return await attendance_open(q.message, ctx, int(parts[1]), date.fromisoformat(parts[2]))

    if action == "qz":  # qz:add / qz:pay / qz:hist — qarzlar menyusi
        await q.answer()
        ctx.user_data.pop("sale", None)
        ctx.user_data.pop("salary_for", None)
        if parts[1] == "add":
            ctx.user_data["debt"] = dict(step="add")
            return await q.message.reply_text(
                "➕ Kimga va qancha qarz bo'ldik? Bitta xabarda yozing:\n"
                "<i>Go'shtchi Akmal 2500000 mol go'shti 20 kg</i>\n<i>Bozor Sardor 800 ming sabzavot</i>\n\n"
                "Avval yozilgan odam bo'lsa, xuddi o'sha nom bilan yozing — summasi qo'shiladi.\nBekor qilish: /bekor",
                parse_mode=HTML)
        if not db.debt_balances(only_open=parts[1] == "pay"):
            return await q.message.reply_text("Hali qarz yozilmagan." if parts[1] == "hist" else "To'lanadigan qarz yo'q ✅")
        if parts[1] == "pay":
            return await q.message.reply_text("💵 Kimga to'ladingiz?", reply_markup=creditors_kb("qp", True))
        return await q.message.reply_text("📜 Kimning tarixini ko'rasiz?", reply_markup=creditors_kb("qh", False))

    if action == "qp":  # qp:<creditor_id> — to'lov summasini so'raymiz
        await q.answer()
        await q.edit_message_reply_markup(None)
        cid, bal = int(parts[1]), db.debt_balance(int(parts[1]))
        ctx.user_data["debt"] = dict(step="pay", cid=cid)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"To'liq to'lash — {som(bal)}", callback_data=f"qf:{cid}")]])
        return await q.message.reply_text(
            f"👤 {escape(db.get_creditor(cid)['name'])} — qarz <b>{som(bal)}</b>\n\n"
            "Qancha to'ladingiz? Summani yozing yoki pastdagi tugmani bosing.", parse_mode=HTML, reply_markup=kb)

    if action == "qf":  # qf:<creditor_id> — to'liq to'lash
        await q.answer()
        await q.edit_message_reply_markup(None)
        ctx.user_data.pop("debt", None)
        cid = int(parts[1])
        return await debt_pay_preview(q.message, ctx, u, cid, db.debt_balance(cid))

    if action == "qh":  # qh:<creditor_id> — tarix
        await q.answer()
        cid = int(parts[1])
        rows = db.debt_history(cid)
        lines = [f"📜 <b>{escape(db.get_creditor(cid)['name'])}</b> — qarz {som(db.debt_balance(cid))}\n"]
        for r in rows:
            sign = "➕ qarz" if r["amount"] > 0 else "💵 to'landi"
            note = f" — {escape(r['note'])}" if r["note"] and r["amount"] > 0 else ""
            lines.append(f"№{r['id']} {r['day'][8:]}.{r['day'][5:7]} {sign} {som(abs(r['amount']))}{note}")
        lines.append("\nXato yozuvni o'chirish: /qarz_ochir №")
        return await q.message.reply_text("\n".join(lines), parse_mode=HTML)

    if action == "ainv":  # ainv:<point_id> — tochka admini taklifi
        await q.answer()
        await q.edit_message_reply_markup(None)
        return await send_invite(q.message, ctx, u, "admin", int(parts[1]))

    if action == "kp":  # kp:<point_id> — xo'jayin kirim uchun tochka tanladi
        await q.answer()
        await q.edit_message_reply_markup(None)
        return await start_income(q.message, ctx, u, int(parts[1]), business_today())

    if action == "inv":  # inv:<point_id>
        await q.answer()
        await q.edit_message_reply_markup(None)
        return await send_invite(q.message, ctx, u, "cashier", int(parts[1]))

    if action == "ua":  # ua:<tg_id>
        target = db.get_user(int(parts[1]))
        if not target or target["tg_id"] in OWNER_IDS or target["tg_id"] == u["tg_id"]:
            return await q.answer("Mumkin emas", show_alert=True)
        db.set_user_active(target["tg_id"], not target["active"])
        db.audit(u["tg_id"], "user_toggle", f"{target['tg_id']} -> {not target['active']}")
        await q.answer("O'zgartirildi")
        return await q.edit_message_reply_markup(None)


# ---------- avtomatik vazifalar ----------

async def job_sales_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    day = business_today()
    for p in db.points():
        if db.get_sale(day, p["id"]):
            continue
        for cid in db.cashiers_of(p["id"]):
            try:
                await ctx.bot.send_message(cid, f"⏰ Bugungi ({day:%d.%m}) kirimni yozishni unutmang: «💰 Kirim»")
            except Exception:
                log.warning("cashier %s reminder failed", cid)


async def job_digest(ctx: ContextTypes.DEFAULT_TYPE):
    text = reports.digest(business_today() - timedelta(days=1))
    for oid in db.owner_ids():
        try:
            await ctx.bot.send_message(oid, text, parse_mode=HTML)
        except Exception:
            log.warning("owner %s digest failed", oid)


async def job_backup(ctx: ContextTypes.DEFAULT_TYPE):
    """Bazaning nusxasini asosiy xo'jayinga Telegram orqali yuboradi."""
    if not OWNER_IDS:
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"backup_{business_today():%Y-%m-%d}.db")
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with open(path, "rb") as fh:
            await ctx.bot.send_document(OWNER_IDS[0], fh, caption="💾 Haftalik zahira nusxa. Saqlab qo'ying.")


async def send_backup(bot, chat_id: int, caption: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"backup_{business_today():%Y-%m-%d}.db")
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with open(path, "rb") as fh:
            await bot.send_document(chat_id, fh, caption=caption)


@owner_only
async def wipe_cmd(update, ctx, u):
    if u["tg_id"] not in OWNER_IDS:
        return await update.message.reply_text("Buni faqat asosiy xo'jayin qila oladi.")
    await send_backup(ctx.bot, u["tg_id"], "💾 O'chirishdan oldingi to'liq nusxa. Saqlab qo'ying.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Ha, hammasini o'chir", callback_data="tz:yes")],
                               [InlineKeyboardButton("❌ Yo'q, bekor", callback_data="tz:no")]])
    await update.message.reply_text(
        "⚠️ <b>Barcha xarajat, kirim, Yandex yozuvlari va kunlik hisobotlar o'chiriladi.</b>\n"
        "Tochkalar, ishchilar ro'yxati, kassir va adminlar qoladi.\n"
        "Yuqoridagi nusxa fayl bilan keyin hammasini tiklash mumkin.\n\nRostdan o'chiraymi?",
        parse_mode=HTML, reply_markup=kb)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Xatolik yuz berdi, qayta urinib ko'ring.")
        except Exception:
            pass


def main():
    db.init()
    for oid in OWNER_IDS:
        db.ensure_owner(oid)
    if not OWNER_IDS:
        log.warning("OWNER_IDS bo'sh — hech kim xo'jayin emas! .env ni to'ldiring.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("bekor", cancel_cmd))
    for kind in ("bugun", "kecha", "hafta", "oy"):
        app.add_handler(CommandHandler(kind, report_cmd(kind)))
    for name, fn in [("excel", excel_cmd), ("nuqta_qosh", add_point_cmd), ("nuqtalar", points_cmd),
                     ("kassir_qosh", add_cashier_cmd), ("hujayin_qosh", add_owner_cmd),
                     ("admin_qosh", add_admin_cmd), ("tozalash", wipe_cmd),
                     ("kunlik", closings_cmd), ("kunlik_ochir", closing_delete_cmd),
                     ("qarzlar", debts_cmd), ("qarz_ochir", debt_delete_cmd),
                     ("davomat", attendance_cmd), ("ishchi_ulash", worker_link_cmd),
                     ("foydalanuvchilar", users_cmd), ("ishchilar", staff_cmd),
                     ("ishchi_qosh", add_employee_cmd), ("oylik", salary_cmd), ("boshat", fire_cmd),
                     ("yandex", yandex_cmd), ("savdo", owner_sale_cmd), ("oxirgi", last_cmd),
                     ("ochir", delete_cmd), ("yandex_ochir", delete_yandex_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    jq = app.job_queue
    jq.run_daily(job_sales_reminder, at(SALES_REMINDER_TIME), name="sales_reminder")
    jq.run_daily(job_admin_reminder, at(ADMIN_REMINDER_TIME), name="admin_reminder")
    jq.run_daily(job_worker_reminder, at(ADMIN_REMINDER_TIME), name="worker_reminder")
    jq.run_daily(job_digest, at(DIGEST_TIME), name="digest")
    # PTB da 0 = yakshanba, bizning sozlamada 0 = dushanba
    jq.run_daily(job_backup, at(BACKUP_TIME), days=((BACKUP_WEEKDAY + 1) % 7,), name="backup")

    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
