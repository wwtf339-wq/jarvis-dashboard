# Hisobchi Telegram bot (fast-fud tochkalari)

- **Xo'jayinlar** (2-3 kishi) ovoz yoki matn bilan xarajat va Yandex tushumini yozadi, xodim va kassir qo'shadi, hisobot va Excel oladi.
- **Kassirlar** har kuni naqd va kartaga tushgan savdoni kiritadi.
- Oy oxirida hamma narsa bir joyda ko'rinadi: tushum (naqd, karta, Yandex), xarajat (bozorlik, ishchilar, ijara, prochee), foyda, tochkalar kesimi, ishchilar oyligi.

LLM: Gemini (`gemini-flash-latest`). Ovozni to'g'ridan-to'g'ri tushunadi, bepul tarifi bu hajmga yetadi.

**To'liq yo'riqnoma va reja: [ROADMAP.md](ROADMAP.md)**

## Tez ishga tushirish
```bash
pip install -r requirements.txt
cp .env.example .env     # TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, OWNER_IDS
python bot.py
```

## Fayllar
| Fayl | Vazifasi |
|---|---|
| `bot.py` | Telegram buyruqlari, rollar, kassir oqimi, avtomatik eslatmalar |
| `ai.py` | Gemini: ovoz va matndan xarajat va Yandex tushumini ajratish |
| `reports.py` | Hisobot matnlari va Excel |
| `db.py` | SQLite baza |
| `config.py` | `.env` sozlamalari |
| `Dockerfile`, `expense-bot.service` | Serverga qo'yish uchun |
