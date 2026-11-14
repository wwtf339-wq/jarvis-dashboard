"""Gemini орқали хўжайиннинг овози/матнидан харажат ва Яндекс тушумларини ажратиш."""
import asyncio
from typing import Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """Сен фаст-фуд бизнесининг ҳисобчисисан. Хўжайин ўзбек (баъзан рус) тилида
харажатлар ва тушумларни айтади. Овоз ёки матндан ҳар бирини алоҳида қатор қилиб ажрат.

expenses — харажатлар. Категориялар:
- bozorlik: маҳсулот ва хомашё (помидор, товуқ гўшти, ёғ, нон, лаваш, гўшт, ичимлик, идиш, салфетка, пакет ва ҳ.к.)
- ishchilar: ишчиларга тўловлар — ойлик, аванс, "олди", "берилди", премия. person майдонига ишчи исмини ёз.
- ijara: нуқта ижараси ва коммунал (свет, газ, сув, чиқинди)
- prochee: бошқа ҳамма нарса (таъмир, транспорт, такси, реклама, солиқ, банк комиссияси ва ҳ.к.)

yandex — Яндекс Еда/Доставкадан ҳисоб рақамга тушган пул ("Яндексдан 2 миллион тушди"). Бу харажат ЭМАС, тушум.
Кассадаги кунлик нақд/карта савдони бу ерга ёзма — уни кассирлар алоҳида киритади.

Қоидалар:
- amount — ҳар доим бутун сўм. "100.000", "100 000", "100 минг", "юз минг" = 100000. "1,5 млн" / "бир ярим миллион" = 1500000.
- "10 кг помидор 100 минг" — amount=100000 (умумий), quantity="10 кг". Агар "килоси 10 минг, 10 кило" деса — amount=100000.
- item — қисқа, тоза номи, бош ҳарф билан ("Помидор", "Товуқ гўшти"). Ишчи тўловида item = "Аванс", "Ойлик" ёки "Тўлов".
- Сумма айтилмаган ёки аниқ эшитилмаган бўлса, ўйлаб топма — у қаторни ташла.
- day_offset: "кеча" деса -1, "олдинги куни"/"ўтган куни" -2, акс ҳолда 0.
- point: агар қайси точка учунлиги айтилса, қуйидаги рўйхатдан айнан номини ёз, бўлмаса null.
- transcript — нима дейилганини айнан ёз.
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
    pts = ", ".join(point_names) or "(битта точка)"
    emps = ", ".join(employee_names) or "(рўйхат бўш)"
    return (f"\nТочкалар: {pts}\nИшчилар рўйхати: {emps}\n"
            "Ишчи исми рўйхатдагига ўхшаса, рўйхатдагидек ёз (масалан 'Ибратга' -> 'Ибрат').\n")


def _call(contents) -> Parsed:
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Parsed,
            temperature=0,
        ),
    )
    if resp.parsed is None:
        raise ValueError(f"Gemini жавоби тушунарсиз: {resp.text!r}")
    return resp.parsed


async def parse_voice(audio: bytes, mime: str, point_names: list[str], employee_names: list[str]) -> Parsed:
    part = types.Part.from_bytes(data=audio, mime_type=mime)
    return await asyncio.to_thread(_call, [part, PROMPT + _context(point_names, employee_names)])


async def parse_text(text: str, point_names: list[str], employee_names: list[str]) -> Parsed:
    return await asyncio.to_thread(
        _call, [PROMPT + _context(point_names, employee_names) + "\nМатн:\n" + text])
