"""Фаст-фуд нуқтаси учун Telegram ҳисобчи-бот.

Овоз ёки матн юборилади -> Gemini харажатларни ажратади -> тасдиқлангач базага ёзилади.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import ai
import db
import reports
from config import ALLOWED_USER_IDS, BOT_TOKEN, CATEGORIES, TZ

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("expense-bot")

BTN_TODAY, BTN_WEEK, BTN_MONTH, BTN_XLSX = "📅 Бугун", "📆 Ҳафта", "🗓 Ой", "📊 Excel (ой)"
KEYBOARD = ReplyKeyboardMarkup([[BTN_TODAY, BTN_WEEK], [BTN_MONTH, BTN_XLSX]], resize_keyboard=True)

HELP = (
    "Салом! Мен ҳисобчи ботман.\n\n"
    "🎤 Овозли ёки матнли хабар юборинг, масалан:\n"
    "<i>«10 кг помидор 100 минг, товуқ гўшти 10 кг 350 минг, Ибрат 100 минг олди»</i>\n"
    "Мен ажратиб кўрсатаман, сиз «Сақлаш» ни босасиз.\n\n"
    "Ҳисобот: тугмалар ёки /bugun /kecha /hafta /oy /excel\n"
    "Хато ёзилганини ўчириш: /oxirgi — рўйхат, /ochir &lt;рақам&gt;\n"
    "Ойни танлаш: /oy 2025-10"
)


def allowed(update: Update) -> bool:
    return not ALLOWED_USER_IDS or (update.effective_user and update.effective_user.id in ALLOWED_USER_IDS)


def today():
    return datetime.now(TZ).date()


async def guard(update: Update) -> bool:
    if allowed(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text(f"Рухсат йўқ. Сизнинг ID: {update.effective_user.id}")
    return False


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML, reply_markup=KEYBOARD)


# ---------- харажат қабул қилиш ----------

def preview_text(parsed: ai.Parsed, day) -> str:
    lines = [f"📝 <i>{parsed.transcript}</i>", f"📅 Сана: <b>{day:%d.%m.%Y}</b>", ""]
    total = 0
    for e in parsed.entries:
        who = f" — {e.person}" if e.person else ""
        qty = f" {e.quantity}" if e.quantity else ""
        lines.append(f"• [{CATEGORIES[e.category]}] {e.item}{qty}{who}: <b>{reports.som(e.amount)}</b>")
        total += e.amount
    lines += ["", f"Жами: <b>{reports.som(total)}</b> сўм"]
    return "\n".join(lines)


async def propose(update: Update, ctx: ContextTypes.DEFAULT_TYPE, parsed: ai.Parsed):
    entries = [e for e in parsed.entries if e.amount > 0]
    if not entries:
        await update.message.reply_text("Харажат топилмади. Яна бир бор, суммаси билан айтинг.")
        return
    parsed.entries = entries
    day = today() + timedelta(days=min(0, parsed.day_offset))
    key = uuid.uuid4().hex[:8]
    ctx.bot_data.setdefault("pending", {})[key] = (update.effective_chat.id, day, parsed)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сақлаш", callback_data=f"ok:{key}"),
        InlineKeyboardButton("❌ Бекор", callback_data=f"no:{key}"),
    ]])
    await update.message.reply_text(preview_text(parsed, day), parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    msg = update.message
    media = msg.voice or msg.audio
    if media.duration and media.duration > 180:
        await msg.reply_text("Овоз 3 дақиқадан қисқа бўлсин.")
        return
    await msg.chat.send_action("typing")
    try:
        f = await media.get_file()
        data = bytes(await f.download_as_bytearray())
        mime = "audio/ogg" if msg.voice else (media.mime_type or "audio/mpeg")
        parsed = await ai.parse_voice(data, mime)
    except Exception:
        log.exception("voice parse failed")
        await msg.reply_text("Овозни ўқий олмадим (Gemini хато берди ёки лимит тугади). Бироздан сўнг қайта юборинг ёки матн қилиб ёзинг.")
        return
    await propose(update, ctx, parsed)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    text = update.message.text.strip()
    shortcuts = {BTN_TODAY: "bugun", BTN_WEEK: "hafta", BTN_MONTH: "oy"}
    if text in shortcuts:
        return await send_report(update, shortcuts[text])
    if text == BTN_XLSX:
        return await send_excel(update, ctx, "oy")
    await update.message.chat.send_action("typing")
    try:
        parsed = await ai.parse_text(text)
    except Exception:
        log.exception("text parse failed")
        await update.message.reply_text("Тушунмадим, қайта ёзиб кўринг.")
        return
    await propose(update, ctx, parsed)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not allowed(update):
        return await q.answer("Рухсат йўқ", show_alert=True)
    action, key = q.data.split(":", 1)
    item = ctx.bot_data.get("pending", {}).pop(key, None)
    if not item:
        await q.answer("Бу хабар эскирган", show_alert=True)
        return await q.edit_message_reply_markup(None)
    chat_id, day, parsed = item
    if action == "no":
        await q.answer("Бекор қилинди")
        return await q.edit_message_text("❌ Бекор қилинди")
    ids = db.add_many(chat_id, day, [e.model_dump() for e in parsed.entries])
    await q.answer("Сақланди")
    await q.edit_message_text(
        preview_text(parsed, day) + f"\n\n✅ Сақланди (№ {ids[0]}–{ids[-1]})", parse_mode=ParseMode.HTML
    )


# ---------- ҳисоботлар ----------

def resolve_period(kind: str, args: list[str]):
    if kind == "oy" and args:  # /oy 2025-10
        y, m = args[0].split("-")
        from datetime import date
        return reports.period_range("oy", date(int(y), int(m), 1))
    return reports.period_range(kind, today())


async def send_report(update: Update, kind: str, args: list[str] | None = None):
    try:
        start_d, end_d, title = resolve_period(kind, args or [])
    except Exception:
        return await update.message.reply_text("Формат: /oy 2025-10")
    rows = db.between(update.effective_chat.id, start_d, end_d)
    text = reports.text_report(rows, title, detailed=(kind in ("bugun", "kecha")))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def report_cmd(kind: str):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if await guard(update):
            await send_report(update, kind, ctx.args)
    return handler


async def send_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, kind: str = "oy"):
    try:
        start_d, end_d, title = resolve_period(kind, ctx.args or [])
    except Exception:
        return await update.message.reply_text("Формат: /excel 2025-10")
    rows = db.between(update.effective_chat.id, start_d, end_d)
    if not rows:
        return await update.message.reply_text("Бу давр учун маълумот йўқ.")
    os.makedirs("exports", exist_ok=True)
    path = f"exports/hisobot_{start_d:%Y-%m}.xlsx"
    reports.excel_report(rows, path, title)
    with open(path, "rb") as fh:
        await update.message.reply_document(fh, caption=title)


async def excel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        await send_excel(update, ctx, "oy")


# ---------- тузатиш ----------

async def last_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    rows = db.last(update.effective_chat.id, 10)
    if not rows:
        return await update.message.reply_text("Ҳали ёзув йўқ.")
    lines = [f"№{r['id']} {r['day'][5:]} [{CATEGORIES[r['category']]}] {r['item']}"
             f"{' — ' + r['person'] if r['person'] else ''}: {reports.som(r['amount'])}" for r in rows]
    await update.message.reply_text("Охирги ёзувлар:\n" + "\n".join(lines) + "\n\nЎчириш: /ochir <рақам>")


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("Формат: /ochir 15")
    ok = db.delete(update.effective_chat.id, int(ctx.args[0]))
    await update.message.reply_text("🗑 Ўчирилди" if ok else "Бундай рақам топилмади")


def main():
    db.init()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    for kind in ("bugun", "kecha", "hafta", "oy"):
        app.add_handler(CommandHandler(kind, report_cmd(kind)))
    app.add_handler(CommandHandler("excel", excel_cmd))
    app.add_handler(CommandHandler("oxirgi", last_cmd))
    app.add_handler(CommandHandler("ochir", delete_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Бот ишга тушди")
    app.run_polling()


if __name__ == "__main__":
    main()
