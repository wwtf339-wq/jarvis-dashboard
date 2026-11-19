"""Fast-fud biznesi uchun Telegram hisobchi-bot.

Rollar:
  owner   — xo'jayin (2-3 kishi): xarajat/Yandex kiritadi, xodim va kassir qo'shadi, hisobot oladi.
  cashier — tochka kassiri: har kuni naqd va kartaga tushgan savdoni kiritadi.
"""
import logging
import os
import sqlite3
import tempfile
import uuid
from datetime import date, timedelta
from html import escape

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import ai
import db
import reports
from config import (BACKUP_TIME, BACKUP_WEEKDAY, BOT_TOKEN, CATEGORIES, DB_PATH, DIGEST_TIME,
                    MAX_OWNERS, NOTIFY_OWNERS_ON_SALES, OWNER_IDS, SALES_REMINDER_TIME, at,
                    business_today)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("expense-bot")

HTML = ParseMode.HTML
som = reports.som

# ---------- klaviaturalar ----------
O_TODAY, O_WEEK, O_MONTH = "📅 Bugun", "📆 Hafta", "🗓 Oy"
O_XLSX, O_STAFF, O_ADMIN = "📊 Excel", "👥 Xodimlar", "⚙️ Boshqaruv"
B_EXP, B_INC = "💸 Xarajat", "💰 Kirim"
OWNER_KB = ReplyKeyboardMarkup([[B_EXP, B_INC], [O_TODAY, O_WEEK, O_MONTH], [O_XLSX, O_STAFF, O_ADMIN]],
                               resize_keyboard=True)
CASHIER_KB = ReplyKeyboardMarkup([[B_EXP, B_INC]], resize_keyboard=True)

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
/kassir_qosh — kassir uchun taklif havolasi
/hujayin_qosh — xo'jayin uchun taklif havolasi
/foydalanuvchilar — ro'yxat, o'chirib qo'yish

👥 <b>Xodimlar (oylik hisobi)</b>
/ishchilar — ro'yxat
/ishchi_qosh Ism Oylik — ishga olish (/ishchi_qosh Ibrat 4000000)
/oylik № Summa — oylikni o'zgartirish
/boshat № — ishdan bo'shatish

💰 <b>Pul</b>
/yandex Summa [izoh] — Yandex tushumi (/yandex 2400000 3-9 noyabr)
💰 <b>Kirim</b> tugmasi — tochka kunlik kirimi (naqd/karta)
/savdo Naqd Karta — tezkor kirim (/savdo kecha 2500000 1800000)

✏️ <b>Tuzatish</b>
/oxirgi — oxirgi yozuvlar
/ochir № — xarajatni o'chirish
/yandex_ochir № — Yandex yozuvini o'chirish"""

CASHIER_HELP = ("Salom! Siz <b>{point}</b> xodimisiz.\n\n"
                "💸 <b>Xarajat</b> — pul chiqsa (bozorlik, avans, benzin…) ovoz yoki matn bilan yozing.\n"
                "💰 <b>Kirim</b> — smena oxirida naqd va kartaga tushgan summani yozing. "
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
        db.upsert_user(tg_id, name, inv["role"], inv["point_id"])
        db.audit(tg_id, "joined", f"{inv['role']} point={inv['point_id']} by={inv['created_by']}")
        role_txt = "xo'jayin" if inv["role"] == "owner" else f"«{db.point_name(inv['point_id'])}» kassiri"
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

    if u["role"] == "owner":
        await update.message.reply_text(OWNER_HELP, parse_mode=HTML, reply_markup=OWNER_KB)
        if not db.points():
            await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Chilonzor")
    else:
        await update.message.reply_text(CASHIER_HELP.format(point=escape(db.point_name(u["point_id"]))),
                                        parse_mode=HTML, reply_markup=CASHIER_KB)


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    if u["role"] == "owner":
        await update.message.reply_text(OWNER_HELP, parse_mode=HTML, reply_markup=OWNER_KB)
    else:
        await update.message.reply_text(CASHIER_HELP.format(point=escape(db.point_name(u["point_id"]))),
                                        parse_mode=HTML, reply_markup=CASHIER_KB)


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


@owner_only
async def add_cashier_cmd(update, ctx, u):
    if not db.points():
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    await update.message.reply_text("Kassir qaysi tochkada ishlaydi?", reply_markup=points_kb("inv"))


@owner_only
async def add_owner_cmd(update, ctx, u):
    if len(db.owner_ids()) >= MAX_OWNERS:
        return await update.message.reply_text(f"Xo'jayinlar soni chegarada ({MAX_OWNERS}). /foydalanuvchilar dan bittasini o'chiring.")
    await send_invite(update.message, ctx, u, "owner", None)


async def send_invite(message, ctx, u, role: str, point_id):
    code = db.create_invite(role, point_id, u["tg_id"])
    link = f"https://t.me/{ctx.bot.username}?start=inv_{code}"
    who = "xo'jayin" if role == "owner" else f"«{escape(db.point_name(point_id))}» kassiri"
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
        role = "👑 xo'jayin" if r["role"] == "owner" else f"🧾 {db.point_name(r['point_id'])}"
        status = "" if r["active"] else " — ❌ o'chirilgan"
        lines.append(f"{escape(r['name'] or str(r['tg_id']))} — {escape(role)}{status}")
        if r["tg_id"] != u["tg_id"] and r["tg_id"] not in OWNER_IDS:
            label = ("🚫 O'chirish: " if r["active"] else "✅ Yoqish: ") + (r["name"] or str(r["tg_id"]))
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"ua:{r['tg_id']}")])
    await update.message.reply_text("\n".join(lines), parse_mode=HTML,
                                    reply_markup=InlineKeyboardMarkup(kb) if kb else None)


# ---------- xodimlar ----------

@owner_only
async def staff_cmd(update, ctx, u):
    emps = db.employees()
    if not emps:
        return await update.message.reply_text("Xodim yo'q. Ishga olish: /ishchi_qosh Ibrat 4000000")
    lines = [f"№{e['id']} <b>{escape(e['name'])}</b> — {escape(db.point_name(e['point_id']))}, "
             f"oylik {som(e['salary'])}" for e in emps]
    lines.append("\nOylikni o'zgartirish: /oylik № Summa\nBo'shatish: /boshat №")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


@owner_only
async def add_employee_cmd(update, ctx, u):
    if len(ctx.args) < 2:
        return await update.message.reply_text("Format: /ishchi_qosh Ibrat 4000000")
    salary = reports.parse_amount(ctx.args[-1])
    name = " ".join(ctx.args[:-1]).strip()
    if salary is None or not name:
        return await update.message.reply_text("Format: /ishchi_qosh Ibrat 4000000")
    if db.find_employee(name):
        return await update.message.reply_text("Bunday ismli xodim bor. Farqlash uchun familiyasini qo'shing.")
    item = dict(type="emp", name=name, salary=salary, by=u["tg_id"])
    pts = db.points()
    if len(pts) > 1:
        key = stash(ctx, item)
        return await update.message.reply_text(f"{name} qaysi tochkada ishlaydi?", reply_markup=points_kb(f"pt:{key}"))
    item["point"] = pts[0]["id"] if pts else None
    await finish_employee(update.message, item)


async def finish_employee(message, item):
    eid = db.add_employee(item["name"], item.get("point"), item["salary"], business_today())
    db.audit(item["by"], "employee_add", f"{eid} {item['name']} {item['salary']}")
    await message.reply_text(f"✅ {item['name']} ishga olindi (№{eid}), {db.point_name(item.get('point'))}, "
                             f"oylik {som(item['salary'])}")


@owner_only
async def salary_cmd(update, ctx, u):
    if len(ctx.args) != 2 or not ctx.args[0].isdigit() or reports.parse_amount(ctx.args[1]) is None:
        return await update.message.reply_text("Format: /oylik 3 4500000")
    eid, sal = int(ctx.args[0]), reports.parse_amount(ctx.args[1])
    if not db.set_salary(eid, sal):
        return await update.message.reply_text("Bunday № topilmadi. /ishchilar")
    db.audit(u["tg_id"], "salary_set", f"{eid} {sal}")
    await update.message.reply_text(f"✅ №{eid} oyligi: {som(sal)}")


@owner_only
async def fire_cmd(update, ctx, u):
    if len(ctx.args) != 1 or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /boshat 3")
    eid = int(ctx.args[0])
    e = db.get_employee(eid)
    if not e or not db.fire_employee(eid, business_today()):
        return await update.message.reply_text("Bunday faol xodim topilmadi. /ishchilar")
    db.audit(u["tg_id"], "employee_fire", f"{eid} {e['name']}")
    await update.message.reply_text(f"✅ {e['name']} bo'shatildi. Oylik hisobotida shu oygacha ko'rinib turadi.")


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


async def handle_parsed(message, ctx, u, parsed: ai.Parsed):
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
    yandex = [y.model_dump() for y in parsed.yandex if y.amount > 0] if u["role"] == "owner" else []
    if not expenses and not yandex:
        return await message.reply_text("Summa topilmadi. Narsasi va summasi bilan qayta ayting.")
    offset = max(-7, min(0, parsed.day_offset))
    item = dict(type="exp", day=(business_today() + timedelta(days=offset)).isoformat(),
                transcript=parsed.transcript, expenses=expenses, yandex=yandex, by=u["tg_id"])
    if u["role"] == "cashier":
        item["point"] = u["point_id"]
        key = stash(ctx, item)
        return await message.reply_text(exp_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    await ask_point_or_confirm(message, ctx, item, parsed.point)


def ai_context():
    return [p["name"] for p in db.points()], [e["name"] for e in db.employees()]


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
    except Exception:
        log.exception("voice parse failed")
        await _drop(wait)
        return await msg.reply_text("Ovozni o'qiy olmadim (Gemini xatosi yoki kunlik limit tugadi). "
                                    "Birozdan so'ng qayta yuboring yoki matn qilib yozing.")
    await _drop(wait)
    await handle_parsed(msg, ctx, u, parsed)


async def expense_text(update: Update, ctx, u, text: str):
    wait = await update.message.reply_text("⏳ O'qiyapman...")
    try:
        parsed = await ai.parse_text(text, *ai_context())
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
    nums = [reports.parse_amount(a) for a in args]
    if len(nums) != 2 or None in nums:
        return await update.message.reply_text("Format: /savdo 2500000 1800000  yoki  /savdo kecha 2500000 1800000")
    item = dict(type="sale", day=day.isoformat(), cash=nums[0], card=nums[1], by=u["tg_id"])
    pts = db.points()
    if not pts:
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    if len(pts) == 1:
        item["point"] = pts[0]["id"]
        key = stash(ctx, item)
        return await update.message.reply_text(sale_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))
    key = stash(ctx, item)
    await update.message.reply_text("Qaysi tochka savdosi?", reply_markup=points_kb(f"pt:{key}"))


@owner_only
async def last_cmd(update, ctx, u):
    rows = db.last_expenses(10)
    ya = db.last_yandex(5)
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
    lines.append("\nO'chirish: /ochir № yoki /yandex_ochir №")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


@owner_only
async def delete_cmd(update, ctx, u):
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Format: /ochir 15")
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
    @owner_only
    async def handler(update, ctx, u):
        ref = parse_month_arg(ctx.args) if kind == "oy" else business_today()
        if ref is None:
            return await update.message.reply_text("Format: /oy 2026-10")
        await send_report(update.message, kind, ref)
    handler.__name__ = f"report_{kind}"
    return handler


@owner_only
async def excel_cmd(update, ctx, u):
    ref = parse_month_arg(ctx.args)
    if ref is None:
        return await update.message.reply_text("Format: /excel 2026-10")
    await send_excel(update.message, ref)


async def send_excel(message, ref: date):
    start, end = reports.month_range(ref.year, ref.month)
    os.makedirs("exports", exist_ok=True)
    path = f"exports/hisobot_{start:%Y-%m}.xlsx"
    reports.excel_report(start, end, path)
    with open(path, "rb") as fh:
        await message.reply_document(fh, caption=f"{reports.MONTHS[ref.month]} {ref.year} — to'liq hisobot")


# ---------- kassir ----------

def sale_preview(item: dict) -> str:
    day = date.fromisoformat(item["day"])
    lines = [f"🏪 {escape(db.point_name(item['point']))}   📅 {day:%d.%m.%Y}",
             f"💵 Naqd: <b>{som(item['cash'])}</b>",
             f"💳 Karta: <b>{som(item['card'])}</b>",
             f"Jami: <b>{som(item['cash'] + item['card'])}</b>"]
    old = db.get_sale(day, item["point"])
    if old:
        lines.append(f"\n⚠️ Bu kunga oldin yozilgan: naqd {som(old['cash'])}, karta {som(old['card'])} — almashtiriladi.")
    return "\n".join(lines)


def yesterday_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📆 Kechagi kun uchun", callback_data="ky")]])


async def start_income(message, ctx, u, point_id, day: date):
    ctx.user_data["sale"] = dict(day=day.isoformat(), step="cash", point=point_id)
    await message.reply_text(
        f"💰 Kirim — 🏪 {escape(db.point_name(point_id))}, 📅 {day:%d.%m.%Y}\n\n"
        "💵 Naqd qancha tushdi? (masalan: 2 500 000)\n\nBekor qilish: /bekor",
        parse_mode=HTML, reply_markup=yesterday_kb() if day == business_today() else None)


async def income_button(update: Update, ctx, u):
    if u["role"] == "cashier":
        return await start_income(update.message, ctx, u, u["point_id"], business_today())
    pts = db.points()
    if not pts:
        return await update.message.reply_text("Avval tochka qo'shing: /nuqta_qosh Nomi")
    if len(pts) == 1:
        return await start_income(update.message, ctx, u, pts[0]["id"], business_today())
    await update.message.reply_text("💰 Qaysi tochka kirimi?", reply_markup=points_kb("kp"))


async def income_step(update: Update, ctx, u, st: dict, text: str):
    amount = reports.parse_amount(text)
    if amount is None:
        return await update.message.reply_text("Faqat raqam yozing, masalan: 2 500 000  (bekor: /bekor)")
    if st["step"] == "cash":
        st.update(cash=amount, step="card")
        return await update.message.reply_text("💳 Kartaga (terminal/Click/Payme) qancha tushdi?")
    ctx.user_data.pop("sale", None)
    item = dict(type="sale", day=st["day"], point=st["point"], cash=st["cash"], card=amount, by=u["tg_id"])
    key = stash(ctx, item)
    await update.message.reply_text(sale_preview(item), parse_mode=HTML, reply_markup=confirm_kb(key))


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("sale", None)
    await update.message.reply_text("Bekor qilindi.")


async def save_sale(ctx, item: dict):
    day = date.fromisoformat(item["day"])
    db.upsert_sale(day, item["point"], item["cash"], item["card"], item["by"])
    db.audit(item["by"], "sale", f"{item['point']} {item['day']} {item['cash']} {item['card']}")
    if NOTIFY_OWNERS_ON_SALES:
        by = db.get_user(item["by"])
        text = (f"💰 Kirim: {escape(db.point_name(item['point']))}, {day:%d.%m}: naqd {som(item['cash'])}, "
                f"karta {som(item['card'])}, jami <b>{som(item['cash'] + item['card'])}</b>"
                f"\n<i>kiritdi: {escape((by['name'] if by else None) or str(item['by']))}</i>")
        await notify_owners(ctx, text, skip=item["by"])


async def notify_owners(ctx, text: str, skip=None):
    for oid in db.owner_ids():
        if oid == skip:
            continue
        try:
            await ctx.bot.send_message(oid, text, parse_mode=HTML)
        except Exception:
            log.warning("owner %s notify failed", oid)


# ---------- umumiy xabar marshrutlari ----------

async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    ctx.user_data.pop("sale", None)
    await expense_voice(update, ctx, u)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = current_user(update)
    if not u:
        return await deny(update)
    text = update.message.text.strip()
    if text == B_EXP:
        ctx.user_data.pop("sale", None)
        return await update.message.reply_text(EXP_PROMPT, parse_mode=HTML)
    if text == B_INC:
        ctx.user_data.pop("sale", None)
        return await income_button(update, ctx, u)
    st = ctx.user_data.get("sale")
    if st:
        return await income_step(update, ctx, u, st, text)
    if u["role"] == "cashier":
        if reports.parse_amount(text) is not None:
            return await update.message.reply_text(
                "Kirim yozish uchun «💰 Kirim» ni, xarajat uchun «💸 Xarajat» ni bosing.", reply_markup=CASHIER_KB)
        return await expense_text(update, ctx, u, text)

    ref = business_today()
    if text == O_TODAY:
        return await send_report(update.message, "bugun", ref)
    if text == O_WEEK:
        return await send_report(update.message, "hafta", ref)
    if text == O_MONTH:
        return await send_report(update.message, "oy", ref)
    if text == O_XLSX:
        return await send_excel(update.message, ref)
    if text == O_STAFF:
        return await staff_cmd(update, ctx)
    if text == O_ADMIN:
        return await update.message.reply_text(OWNER_HELP, parse_mode=HTML)
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
            if u["role"] == "cashier" and NOTIFY_OWNERS_ON_SALES:
                note = f"💸 <b>{escape(u['name'] or str(u['tg_id']))}</b> xarajat yozdi:\n" + exp_preview(item)
                await notify_owners(ctx, note, skip=u["tg_id"])
        elif item["type"] == "sale":
            text = sale_preview(item)
            await save_sale(ctx, item)
            await q.edit_message_text(text.split("\n\n⚠️")[0] + "\n\n✅ Saqlandi", parse_mode=HTML)
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

    if action == "ky":  # kirim: kechagi kun uchun
        st = ctx.user_data.get("sale")
        await q.answer()
        await q.edit_message_reply_markup(None)
        if not st:
            return
        return await start_income(q.message, ctx, u, st["point"], business_today() - timedelta(days=1))

    if u["role"] != "owner":
        return await q.answer("Ruxsat yo'q", show_alert=True)

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

    if action == "rp":  # rp:<kind>:<ref>:<point_id>
        await q.answer()
        pid = int(parts[3]) or None
        return await send_report(q.message, parts[1], date.fromisoformat(parts[2]), pid)


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
    jq.run_daily(job_digest, at(DIGEST_TIME), name="digest")
    # PTB da 0 = yakshanba, bizning sozlamada 0 = dushanba
    jq.run_daily(job_backup, at(BACKUP_TIME), days=((BACKUP_WEEKDAY + 1) % 7,), name="backup")

    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
