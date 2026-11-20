# Hisobchi-bot: yo'l xaritasi

Maqsad: oyda qancha savdo bo'ldi (naqd, karta, Yandex), qancha xarajat qilindi (bozorlik, ishchilar, ijara, prochee) va qancha foyda qoldi, hammasi bir ekranda, har bir tochka bo'yicha alohida ko'rinsin.

---

## 0. Hozir, telefondan: kodni saqlab qo'yish ⚠️

Kod sizning kompyuteringizda emas. U hozir shu Claude sessiyasining bulutdagi vaqtinchalik serverida turibdi. Sessiya yopilsa, o'chib ketadi. Uni GitHub'ga yuklash kerak, bunga kompyuter shart emas:

1. Telefon brauzerida https://github.com/apps/claude/installations/select_target ni oching.
2. `wwtf339-wq` akkauntini tanlang va **jarvis-dashboard** reposiga ruxsat bering.
3. Shu chatga «push qil» deb yozing.

Shundan keyin kod GitHub'da, `claude/telegram-expense-tracking-bot-kmd0y7` branchida, `expense-bot/` papkasida saqlanadi.

---

## 1. Kim nima qila oladi

| | Xo'jayin (2-3 kishi) | Xodim / kassir (har tochkada) | Begona odam |
|---|---|---|---|
| Menyusi | 💸 Xarajat, 💰 Kirim + hisobotlar | faqat **💸 Xarajat** va **💰 Kirim** | — |
| 💰 Kirim: smena oxirida naqd/karta | ✅ | ✅ (o'z tochkasiga) | ❌ |
| 💸 Xarajat: ovoz yoki matn bilan | ✅ | ✅ (o'z tochkasiga; xo'jayinlarga xabar boradi) | ❌ |
| Yandex tushumini yozish | ✅ | ❌ | ❌ |
| Hisobot, Excel | ✅ | ❌ (faqat o'z tochkasining oxirgi 7 kunini ko'radi) | ❌ |
| Tochka, kassir, xo'jayin qo'shish/o'chirish | ✅ | ❌ | ❌ |
| Ishchini ishga olish, oyligini o'zgartirish, bo'shatish | ✅ | ❌ | ❌ |
| Xatolarni o'chirish | ✅ | o'z savdosini qayta kiritib almashtiradi | ❌ |

**Botga qanday kiriladi:**
- **Asosiy xo'jayinlar** `.env` dagi `OWNER_IDS` ga yoziladi. Ular botdan hech qachon chiqarib yuborilmaydi.
- **Qolganlar** (kassirlar, 3-xo'jayin) faqat **taklif havolasi** orqali kiradi. Xo'jayin `/kassir_qosh` ni bosadi, tochkani tanlaydi, bot havola beradi. Havolani kassirga Telegram'da yuborasiz, u bosadi va tayyor. Havola 48 soat yashaydi va bir marta ishlaydi.
- Havolasiz kirgan odam «Ruxsat yo'q» degan javob oladi va hech narsani ko'rmaydi.
- Ishdan ketgan kassir `/foydalanuvchilar` orqali bitta tugma bilan o'chiriladi.

---

## 2. Kechqurun, kompyuterda (taxminan 30 daqiqa)

### 2.1 Kalitlarni olish
1. **Telegram bot tokeni:** @BotFather → `/newbot` → nomi (masalan «Nuqta hisobchi») → username (oxiri `bot` bilan tugaydi) → tokenni nusxalang.
2. **Gemini API kaliti:** https://aistudio.google.com/apikey → Google akkaunt bilan kiring → **Create API key** → nusxalang.
3. **Telegram ID:** har bir xo'jayin @userinfobot ga `/start` yozadi va `Id` raqamini beradi.

> **Gemini Pro obunasi haqida:** 1,5 yillik Pro obuna **Gemini ilovasi** (gemini.google.com) uchun. Bot ishlatadigan **API** alohida xizmat, obuna unga o'tmaydi. Lekin API'ning bepul limiti bu bot uchun bemalol yetadi: kuniga bir necha o'nlab ovozli xabar bu limitning juda kichik qismi.

### 2.2 Ishga tushirib sinash
```bash
git clone https://github.com/wwtf339-wq/jarvis-dashboard.git
cd jarvis-dashboard
git checkout claude/telegram-expense-tracking-bot-kmd0y7
cd expense-bot
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```
`.env` faylini ochib, uchta qator to'ldiriladi:
```
TELEGRAM_BOT_TOKEN=123456:ABC...
GEMINI_API_KEY=AIza...
OWNER_IDS=111111111,222222222
```
Keyin:
```bash
python bot.py
```
Botga `/start` yozing. Xo'jayin menyusi chiqsa, hammasi to'g'ri.

### 2.3 Birinchi sinov
1. `/nuqta_qosh Chilonzor`
2. Ovozli xabar: «10 kilo pomidor 100 ming, tovuq go'shti 10 kilo 350 ming».
3. Bot ajratib ko'rsatadi, **✅ Saqlash** ni bosing.
4. «📅 Bugun» ni bosing, jadval chiqadi.

Agar Gemini xato bersa, ko'pincha kalit noto'g'ri yoki model nomi eskirgan bo'ladi. 8-bo'limga qarang.

---

## 3. Bot doim ishlab turishi uchun (xosting)

`python bot.py` kompyuter yoniq turganda ishlaydi. Kechayu kunduz ishlashi uchun serverga qo'yish kerak. Ikkita yo'l bor:

**A) Railway, telefondan ham boshqarsa bo'ladi (tavsiya)**
1. https://railway.app → GitHub bilan kiring.
2. **New Project → Deploy from GitHub repo** → `jarvis-dashboard` → **Root directory:** `expense-bot`. `Dockerfile` bor, Railway uni o'zi taniydi.
3. **Variables** bo'limida `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `OWNER_IDS` ni kiriting.
4. **Volume** qo'shing, mount path: `/data`. Busiz har yangilanishda baza o'chib ketadi.
5. Narxi taxminan oyiga $5 atrofida. Aniq tarifni saytdan tekshiring.

**B) Arzon VPS (Linux server)**
Server olinadi, kodni `/opt/expense-bot` ga tashlanadi, `.venv` o'rnatiladi, keyin `expense-bot.service` fayli bilan systemd orqali doimiy ishga tushiriladi. Buyruqlari faylning ichida yozilgan.

**V) Bepul: Google Cloud e2-micro (doimiy bepul tarif)**

*1-qadam. Hisob ochish (10 daqiqa)*
1. https://cloud.google.com/free → **Get started for free**. Gmail bilan kiring.
2. Visa/Mastercard karta so'raladi (Humo/Uzcard o'tmaydi). Tekshirish uchun $0–1 bloklanib, qaytariladi.
3. Sizga 90 kunlik $300 sinov krediti beriladi. **Muhim:** 90 kun tugaganda Google "Upgrade" (to'liq hisobga o'tish) so'raydi. Upgrade qilmasangiz, server to'xtatiladi. Upgrade qilganda ham e2-micro bepul limitda qoladi, pul yechilmaydi.

*2-qadam. Server yaratish (5 daqiqa)*
1. Menyu → **Compute Engine → VM instances** → **Enable API** (birinchi marta 1–2 daqiqa) → **Create instance**.
2. Sozlamalar:
   - Name: `expense-bot`
   - Region: **us-central1** (yoki `us-west1`, `us-east1`; faqat shular bepul)
   - Machine type: **e2-micro**
   - Boot disk → **Change**: Debian GNU/Linux 13 (trixie), x86/64, disk turi **Standard persistent disk**, hajmi **30 GB**
   - Qolganiga tegmang. Statik IP **olmang** (pulli).
3. **Create** → 1 daqiqada server tayyor.

*3-qadam. Botni o'rnatish (5 daqiqa)*
1. Server qatoridagi **SSH** tugmasini bosing, brauzerda qora oyna ochiladi.
2. Shu ikki buyruqni kiriting:
   ```bash
   curl -fsSL -o setup.sh https://raw.githubusercontent.com/wwtf339-wq/jarvis-dashboard/claude/telegram-expense-tracking-bot-kmd0y7/expense-bot/deploy_gcp.sh
   sudo bash setup.sh
   ```
3. Skript 3 ta narsani so'raydi: bot tokeni, Gemini kaliti, xo'jayin Telegram ID. Kiriting.
4. Oxirida `TAYYOR: bot ishlayapti` chiqadi. Telegram'da `/start` bosing.

*4-qadam. Xavfsizlik uchun (2 daqiqa)*
- Menyu → **Billing → Budgets & alerts** → $1 lik budjet qo'ying. Tasodifan pul yechila boshlasa, emailga xat keladi.

*Keyinchalik kerak bo'ladigan buyruqlar (SSH oynasida):*
| Nima kerak | Buyruq |
|---|---|
| Bot ishlayaptimi? | `sudo systemctl status expense-bot` |
| Loglar (xatolar) | `sudo journalctl -u expense-bot -f` |
| Kalitni almashtirish | `sudo nano /opt/expense-bot/.env` → saqlash (Ctrl+O, Enter, Ctrl+X) → `sudo systemctl restart expense-bot` |
| Kodni yangilash | yuqoridagi ikki buyruqni qayta bering (`.env` va baza saqlanadi) |
| Bazani yuklab olish | SSH oynasi o'ng yuqorisida ⚙️ → **Download file** → `/opt/expense-bot/expenses.db` |

Bot server o'chib-yonsa ham o'zi qayta ishga tushadi. Har yakshanba baza nusxasi asosiy xo'jayinga Telegram'da keladi.

**G) Bepul, kartasiz: eski Android telefon**
Termux ilovasini (F-Droid'dan) o'rnatib, o'sha buyruqlar bilan `python bot.py` ni ishga tushirasiz. Telefon doim zaryadda va internetda turishi kerak. Bu eng oddiy yo'l, lekin tok yoki internet o'chsa, bot ham to'xtaydi.

> Ikkala holatda ham bot **bir joyda** ishlashi kerak. Kompyuterda va serverda bir vaqtda yoqilsa, Telegram xato beradi.

---

## 4. Birinchi kun: sozlash tartibi

1. **Tochkalar:** `/nuqta_qosh Chilonzor`, `/nuqta_qosh Yunusobod`…
2. **Kassirlar:** `/kassir_qosh` → tochkani tanlash → havolani kassirga yuborish. Har bir kassirga alohida havola. Kassir qo'shilganda xo'jayinlarga xabar keladi.
3. **3-xo'jayin (kerak bo'lsa):** `/hujayin_qosh` → havola.
4. **Xodimlar:** hamma ishchini oyligi bilan kiriting:
   `/ishchi_qosh Ibrat, Jahongir, Otabek` (faqat ism yetadi, oylikni keyin `/oylik Ism summa` bilan qo'yasiz; bir nechta tochka bo'lsa, bot qaysi tochkaligini so'raydi)
   `/ishchilar` — ro'yxat va raqamlari
   `/oylik Jahongir 6000000` yoki shunchaki `/oylik` (ro'yxatdan tanlanadi) — oylik belgilash. Bu xarajat emas, faqat oylik miqdori
   `/boshat 3` — bo'shatish (oy oxirigacha hisobotda ko'rinib turadi)
5. Tekshirish: `/nuqtalar` va `/foydalanuvchilar`.

---

## 5. Kundalik ish tartibi

### Xodim / kassir
**Kun davomida, pul chiqqanda:** **💸 Xarajat** ni bosadi va ovoz yoki matn yuboradi:
«Ibrat 100 ming o'ziga oldi, 50 ming benzin quydim». Bot ajratib ko'rsatadi, xodim **✅ Saqlash** ni bosadi.
Xo'jayinlarga «Ali xarajat yozdi: …» degan xabar boradi. Hisobotda har bir xarajat ostida kim yozgani (✍ Ali) ko'rinadi.

**Smena oxirida (1 daqiqa):**
1. **💰 Kirim** ni bosadi.
2. Smenani tanlaydi: **1-smena** yoki **2-smena** (yozilgan smena yonida ✅ turadi).
3. **Naqd:** summani yozadi, masalan `3456000`, `3 456 000` yoki `3,4 mln`.
4. **Karta:** kartaga tushganini yozadi (terminal, Click, Payme), masalan `870000`.
5. **✅ Saqlash** ni bosadi.

Har smena alohida saqlanadi, hisobotda kunlik jami va har smena alohida ko'rinadi. Smenalar soni `.env` dagi `SHIFTS` bilan o'zgaradi (standart 2).

- Kechasi 05:00 gacha kiritilgan savdo oldingi ish kuniga yoziladi. Tochka kechasi 2-3 da yopilsa ham to'g'ri hisoblanadi.
- Xato yozsa, «💰 Kirim» ni yana bosadi, o'sha smenani tanlab, to'g'risini yozadi. Bot eskisini ko'rsatib, almashtiradi.
- Unutsa, bot soat 23:30 da eslatadi. Ertasiga yozmoqchi bo'lsa, «💰 Kirim» dan keyin chiqadigan **📆 Kechagi kun uchun** tugmasini bosadi.
- Kassir saqlashi bilan xo'jayinlarga «Chilonzor, 2-smena, 14.11: naqd …, karta …» degan xabar keladi.

### Xo'jayin
- **Bozorlik / to'lovlar:** bitta ovozli xabarda hammasini aytish mumkin:
  «Pomidor 10 kilo 100 ming, tovuq 10 kilo 350 ming, Ibrat 100 ming oldi, svet uchun 400 ming to'ladim».
  Bot har birini kategoriyaga ajratadi, siz tekshirib **Saqlash** ni bosasiz.
- «Kecha …» deb boshlasangiz, kechagi sanaga yoziladi.
- Tochka nomini aytsangiz («Chilonzorga…»), o'sha tochkaga yoziladi. Aytmasangiz, bot so'raydi. Ijara kabi hamma tochkaga tegishli xarajatlar uchun **Umumiy** ni tanlang.
- Ishchi ismi ro'yxatdagiga mos kelsa, to'lov o'sha ishchining oylik hisobiga tushadi. Ro'yxatda yo'q ism bo'lsa, bot «⚠️ ro'yxatda yo'q» deb ogohlantiradi.

### Avtomatik
- **09:00:** hamma xo'jayinga kechagi kun va oy boshidan buyongi xulosa keladi. Savdo kiritilmagan kunlar ⚠️ bilan ko'rsatiladi.
- **23:30:** savdo kiritmagan kassirga eslatma boradi.
- **Yakshanba 10:00:** asosiy xo'jayinga bazaning zahira nusxasi (fayl) keladi. Shu fayl bo'lsa, hech narsa yo'qolmaydi.

Vaqtlarni `.env` dagi `DIGEST_TIME`, `SALES_REMINDER_TIME`, `BACKUP_*` orqali o'zgartirish mumkin.

---

## 6. Yandex Dostavka

Yandex puli haftada bir marta hisob raqamga tushadi. Bot uni **pul tushgan kunga** alohida «Yandex» qatori qilib yozadi.

- Ovoz bilan: «Yandexdan 2 million 400 ming tushdi, 3-9 noyabr uchun».
- Yoki buyruq bilan: `/yandex 2400000 3-9 noyabr`.
- Tochkani tanlaysiz. Agar Yandex bitta hisobga hamma tochkanikini birga tushirsa, **Umumiy** ni tanlang.

**Eslab qoling:** oy oxirida Yandex sotgan, lekin puli keyingi oyda tushgan savdo keyingi oyga yoziladi. Bu bank hisobiga mos keladi va tekshirish oson. Yandex komissiyasini alohida ko'rish 9-bo'limdagi rejada bor.

---

## 7. Oy oxiri: hisobot

- **🗓 Oy** ni bosing, Telegram'ning o'zida quyidagilar chiqadi:
  - **Tushum:** naqd, karta, Yandex, jami
  - **Xarajat:** bozorlik, ishchilar, ijara, prochee, jami
  - **Foyda / zarar**
  - **Tochkalar kesimida:** har bir tochkaning tushumi, xarajati va farqi
  - **Kunma-kun jadval**
  - **Ishchilar oyligi:** oyligi, olgani, qoldig'i
  - Savdo kiritilmagan kunlar ⚠️
- Pastdagi tochka tugmalaridan birini bossangiz, faqat o'sha tochkaning hisoboti chiqadi.
- **📊 Excel** 6 varaqli fayl yuboradi: Xulosa, Kunma-kun, Savdo, Xarajatlar, Yandex, Ishchilar. Uni buxgalterga yoki sherikka yuborish mumkin.
- O'tgan oylar uchun: `/oy 2026-10`, `/excel 2026-10`.
- Xato yozuvlar: `/oxirgi` → `/ochir 15` (xarajat) yoki `/yandex_ochir 3`. Kim nimani o'chirgani bazada saqlanadi.

---

## 8. Gemini modeli

**Tez yo'l (Gemini'siz).** `benzin 50000`, `pomidor 100 ming, bodring 45000`, `Umid 700 ming oldi` kabi oddiy matnlarni bot o'zi bir zumda tushunadi. Gemini faqat ovozli xabar, kirill yozuv, `kecha ...`, `10 kg ...` kabi murakkab xabarlar uchun ishlatiladi.

**Bepul kalit (`GEMINI_API_KEY`).** Bepul tarifda har bir modelga kuniga taxminan 20 so'rov beriladi. Bot faqat tez modellarni navbat bilan ishlatadi: `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-3.6-flash`. Band (503), qotgan (504) yoki limiti tugagan (429) model 10–15 daqiqaga chetga qo'yiladi.

**Pullik kalit (`GEMINI_PAID_API_KEY`, ixtiyoriy).** Qo'yilsa:
- **ovozli xabarlar** to'g'ridan-to'g'ri pullik kalitda `gemini-3.5-flash` bilan ishlaydi (band bo'lsa `gemini-3.5-flash-lite`, u ham ishlamasa bepul modellar). Kuniga 10–15 ta ovoz uchun oyiga taxminan $0.5–1;
- **matnlar** avvalgidek bepul: bot o'zi yoki bepul kalit. Bepul limit tugagandagina pullik kalitga o'tadi va o'sha kuni xo'jayinga bir marta xabar beradi.

Kalitni olish:
1. https://aistudio.google.com/apikey → **Create API key** → **yangi loyiha** yarating (masalan `expense-bot-paid`). Bepul kalit turgan loyihani ishlatmang: billing ulangan loyihadagi hamma so'rov pullik bo'ladi.
2. Shu kalit qatorida **Set up billing** → to'lov hisobini ulang.
3. Google Cloud → Billing → **Budgets & alerts** da oyiga $5 lik ogohlantirish qo'ying.
4. Serverda: `sudo nano /opt/expense-bot/.env` → `GEMINI_PAID_API_KEY=` qatoriga kalitni qo'ying → saqlang → `sudo systemctl restart expense-bot`.

- Mavjud modellar ro'yxati (limit sarflamaydi): `cd /opt/expense-bot && sudo .venv/bin/python -c "from dotenv import load_dotenv;load_dotenv();import os;from google import genai;c=genai.Client(api_key=os.environ['GEMINI_API_KEY']);[print(m.name) for m in c.models.list() if 'flash' in m.name]"`
- Qaysi model necha soniyada javob berayotgani: `sudo journalctl -u expense-bot --since "1 hour ago" --no-pager | grep -E "javob berdi|failed" | cut -c1-200`
- **Maxfiylik:** bepul tarifda Google yuborilgan ma'lumotlarni o'z xizmatlarini yaxshilash uchun ishlatishi mumkin. Gemini'ga faqat xarajat matni/ovozi boradi, kassa raqamlari bormaydi. Pullik tarifda ma'lumot o'qitish uchun ishlatilmaydi.

---

## 9. Keyingi bosqichlar (kerak bo'lganda)

| Bosqich | Nima qo'shiladi | Nima beradi |
|---|---|---|
| 2 | **Kassa xarajatlari:** kassir tochkadan chiqqan mayda xarajatni (non, gaz ballon) yozadi | Naqd pul qayerga ketgani ko'rinadi |
| 2 | **Kassadagi qoldiq:** naqd savdo minus kassa xarajatlari minus xo'jayin olib ketgani | O'g'irlik yoki kamomadni darrov sezish |
| 2 | **Yandex komissiyasi:** Yandex hisobotidagi savdo summasi bilan tushgan pulni solishtirish | Yandex qancha olayotgani aniq ko'rinadi |
| 3 | **Nasiya (qarz):** yetkazib beruvchilarga qarz, kim qancha olishi kerak | Oy oxirida kutilmagan qarz chiqmaydi |
| 3 | **Ishchilar davomati:** keldi/kelmadi, oylik o'zi hisoblanadi | Progul va yarim kun to'g'ri hisoblanadi |
| 3 | **Google Sheets'ga avtomat yozish** | Sherik botsiz, jadvalda ko'radi |
| 4 | **Web dashboard** (`jarvis-dashboard` ichida) | Katta ekranda grafiklar, oylarni solishtirish |

---

## 10. Xavfsizlik eslatmalari

- `.env` faylini hech kimga yubormang va GitHub'ga yuklamang. `.gitignore` uni o'zi chetlab o'tadi.
- Token begonaga tushib qolsa, @BotFather → `/revoke` → yangi token oling.
- Yakshanba kuni keladigan zahira faylni o'chirmang. Server buzilsa, shu faylni `DB_PATH` ga qo'yish kifoya.
