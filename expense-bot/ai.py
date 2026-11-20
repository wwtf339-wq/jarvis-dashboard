"""Gemini orqali xo'jayinning ovozi/matnidan xarajat va Yandex tushumlarini ajratish."""
import asyncio
import time
from typing import Literal, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

import logging

from config import (GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_MODEL, GEMINI_PAID_API_KEY,
                    GEMINI_PAID_MODELS)

log = logging.getLogger("expense-bot.ai")
# 15 soniya kutib, javob bo'lmasa keyingi modelga o'tadi
_http = types.HttpOptions(timeout=15_000)
client = genai.Client(api_key=GEMINI_API_KEY, http_options=_http)
paid_client = genai.Client(api_key=GEMINI_PAID_API_KEY, http_options=_http) if GEMINI_PAID_API_KEY else None
MODELS = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
PAID_MODELS = GEMINI_PAID_MODELS if paid_client else []

# Pullik rejim statistikasi: {sana: so'rovlar soni}. Bot kuniga bir marta xo'jayinga xabar beradi.
paid_calls: dict[str, int] = {}

PROMPT = """Sen fast-fud biznesining hisobchisisan. Xo'jayin yoki xodim o'zbek (lotin yoki kirill, ba'zan rus)
tilida xarajatlar va tushumlarni aytadi yoki yozadi. Ovoz yoki matndan har birini alohida qator qilib ajrat.

expenses — xarajatlar. Kategoriyalar:
- bozorlik: mahsulot va xomashyo (pomidor, tovuq go'shti, yog', non, lavash, go'sht, ichimlik, idish, salfetka, paket va h.k.)
- ishchilar: ishchilarga to'lovlar — oylik, avans, "oldi", "o'ziga oldi", "berildi", premiya. person maydoniga ishchi ismini yoz.
  "Ibrat 100 ming o'ziga oldi" = ishchilar, person="Ibrat", item="Avans".
- ijara: nuqta ijarasi va kommunal (svet, gaz, suv, chiqindi)
- prochee: boshqa hamma narsa (benzin, ta'mir, transport, taksi, reklama, soliq, bank komissiyasi va h.k.)

yandex — Yandex Yeda/Dostavkadan hisob raqamga tushgan pul ("Yandexdan 2 million tushdi"). Bu xarajat EMAS, tushum.
Kassadagi kunlik naqd/karta savdoni bu yerga yozma — uni kassirlar alohida kiritadi.

Qoidalar:
- amount — har doim butun so'm. "100.000", "100 000", "100 ming", "yuz ming" = 100000. "1,5 mln" / "bir yarim million" = 1500000.
- "10 kg pomidor 100 ming" — amount=100000 (umumiy), quantity="10 kg". Agar "kilosi 10 ming, 10 kilo" desa — amount=100000.
- item va person ni har doim LOTIN yozuvida yoz (kirillda aytilsa ham): "помидор" -> "Pomidor", "Ибрат" -> "Ibrat".
- item — qisqa, toza nomi, bosh harf bilan ("Pomidor", "Tovuq go'shti"). Ishchi to'lovida item = "Avans", "Oylik" yoki "To'lov".
- Summa aytilmagan yoki aniq eshitilmagan bo'lsa, o'ylab topma — u qatorni tashla.
- day_offset: "kecha" desa -1, "oldingi kuni"/"o'tgan kuni" -2, aks holda 0.
- point: agar qaysi tochka uchunligi aytilsa, quyidagi ro'yxatdan aynan nomini yoz, bo'lmasa null.
- transcript — nima deyilganini aynan yoz.
"""


class Expense(BaseModel):
    category: Literal["bozorlik", "ishchilar", "ijara", "prochee"]
    item: str
    quantity: Optional[str] = None
    amount: int
    person: Optional[str] = None


class YandexIncome(BaseModel):
    amount: int
    note: Optional[str] = None


class Parsed(BaseModel):
    transcript: str
    day_offset: int = 0
    point: Optional[str] = None
    expenses: list[Expense] = []
    yandex: list[YandexIncome] = []


def _context(point_names: list[str], employee_names: list[str]) -> str:
    pts = ", ".join(point_names) or "(bitta tochka)"
    emps = ", ".join(employee_names) or "(ro'yxat bo'sh)"
    return (f"\nTochkalar: {pts}\nIshchilar ro'yxati: {emps}\n"
            "Ishchi ismi ro'yxatdagiga o'xshasa, ro'yxatdagidek yoz (masalan 'Ibratga' -> 'Ibrat').\n")


def _thinking(model: str) -> Optional[types.ThinkingConfig]:
    """Xarajat ajratish oddiy ish — modelning "o'ylash" bosqichini o'chirib, javobni tezlatamiz.
    Gemini 2.x da thinking_budget=0, Gemini 3+ da thinking_level=MINIMAL ishlaydi."""
    if "2.5" in model or "2.0" in model:
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def _generate(model: str, contents, thinking: Optional[types.ThinkingConfig], paid: bool = False):
    return (paid_client if paid else client).models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Parsed,
            temperature=0,
            thinking_config=thinking,
        ),
    )


# Limiti tugagan (429) yoki yo'q (404) modellarni bir muddat chetlab o'tamiz,
# shunda har xabarda bekorga ularga so'rov yuborilmaydi.
_resting: dict[str, float] = {}


def _rest(model: str, err: Exception) -> None:
    code = getattr(err, "code", None)
    msg = str(err)
    if code == 429:          # limit tugagan
        _resting[model] = time.monotonic() + 15 * 60
    elif code == 404:        # bunday model yo'q
        _resting[model] = time.monotonic() + 24 * 3600
    elif code in (500, 503, 504) or "timed out" in msg.lower() or "deadline" in msg.lower():
        _resting[model] = time.monotonic() + 10 * 60   # band yoki qotgan — 10 daqiqa tegmaymiz


def _routes():
    """(pullikmi, model) navbati: avval bepul tez modellar, keyin pullik zaxira."""
    now = time.monotonic()
    free = [(False, m) for m in MODELS]
    paid = [(True, m) for m in PAID_MODELS]
    ready = [r for r in free + paid if _resting.get(_tag(*r), 0) <= now]
    return ready or free + paid


def _tag(paid: bool, model: str) -> str:
    return ("paid:" if paid else "") + model


def _call(contents) -> Parsed:
    last_err = None
    for paid, model in _routes():
        tag = _tag(paid, model)
        t0 = time.monotonic()
        try:
            try:
                resp = _generate(model, contents, _thinking(model), paid)
            except genai_errors.ClientError as e:
                # model bu thinking sozlamasini qabul qilmasa — sozlamasiz qayta urinamiz
                if e.code != 400:
                    raise
                log.info("Gemini %s: thinking sozlamasi qabul qilinmadi, sozlamasiz", tag)
                resp = _generate(model, contents, None, paid)
            if resp.parsed is None:
                raise ValueError(f"tushunarsiz javob: {resp.text!r}")
            log.info("Gemini %s javob berdi: %.1f s", tag, time.monotonic() - t0)
            if paid:
                day = time.strftime("%Y-%m-%d")
                paid_calls[day] = paid_calls.get(day, 0) + 1
            return resp.parsed
        except Exception as e:  # band, limit, timeout — keyingi model
            log.warning("Gemini %s failed (%.1f s): %s", tag, time.monotonic() - t0, str(e)[:200])
            _rest(tag, e)
            last_err = e
    raise RuntimeError(f"Hamma Gemini modellari xato berdi: {last_err}")


async def parse_voice(audio: bytes, mime: str, point_names: list[str], employee_names: list[str]) -> Parsed:
    part = types.Part.from_bytes(data=audio, mime_type=mime)
    return await asyncio.to_thread(_call, [part, PROMPT + _context(point_names, employee_names)])


async def parse_text(text: str, point_names: list[str], employee_names: list[str]) -> Parsed:
    return await asyncio.to_thread(
        _call, [PROMPT + _context(point_names, employee_names) + "\nMatn:\n" + text])
