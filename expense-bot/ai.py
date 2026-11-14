"""Gemini орқали овоз/матндан харажатларни ажратиб олиш."""
import asyncio
from typing import Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """Сен фаст-фуд нуқтасининг ҳисобчисисан. Фойдаланувчи ўзбек (баъзан рус) тилида
харажатларни айтади. Овоз ёки матндан ҳар бир харажатни алоҳида қатор қилиб ажрат.

Категориялар:
- bozorlik: маҳсулот ва хомашё (помидор, товуқ гўшти, ёғ, нон, лаваш, гўшт, ичимлик, идиш-товоқ, салфетка ва ҳ.к.)
- ishchilar: ишчиларга тўловлар — ойлик, аванс, "олди", "берилди", прогул/премия. person майдонига ишчи исмини ёз.
- ijara: нуқта ижараси, шунингдек коммунал (свет, газ, сув) ҳам шу ерга
- prochee: юқоридагиларга кирмайдиган бошқа ҳамма нарса (таъмир, транспорт, реклама, солиқ ва ҳ.к.)

Қоидалар:
- amount — ҳар доим бутун сўм. "100.000", "100 000", "100 минг", "юз минг" = 100000. "1,5 млн" = 1500000.
- Агар нарх бир кг/дона учун эмас, умумий сумма деб айтилган бўлса, шуни amount қил. Агар "10кг помидор 100.000 сум" деса — amount=100000 (ҳаммаси учун), quantity="10 кг".
- item — қисқа, тоза номи, бош ҳарф билан (масалан "Помидор", "Товуқ гўшти"). Ишчи тўловларида item = "Аванс" ёки "Ойлик" ёки "Тўлов".
- Суммани аниқ эшитмаган ёки айтилмаган бўлсанг, ўйлаб топма — шу қаторни ташлаб юбор.
- day_offset: "кеча" деса -1, "ўтган кун"/"олдинги куни" -2, акс ҳолда 0.
- transcript — овозда нима дейилганини айнан ёз.
"""


class Entry(BaseModel):
    category: Literal["bozorlik", "ishchilar", "ijara", "prochee"]
    item: str
    quantity: Optional[str] = None
    amount: int
    person: Optional[str] = None


class Parsed(BaseModel):
    transcript: str
    day_offset: int = 0
    entries: list[Entry]


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
        raise ValueError("Gemini жавоби тушунарсиз")
    return resp.parsed


async def parse_voice(audio: bytes, mime: str = "audio/ogg") -> Parsed:
    part = types.Part.from_bytes(data=audio, mime_type=mime)
    return await asyncio.to_thread(_call, [part, PROMPT])


async def parse_text(text: str) -> Parsed:
    return await asyncio.to_thread(_call, [PROMPT + "\n\nМатн:\n" + text])
