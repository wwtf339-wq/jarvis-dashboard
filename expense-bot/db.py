import sqlite3
from contextlib import contextmanager
from datetime import date

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    day TEXT NOT NULL,              -- YYYY-MM-DD
    category TEXT NOT NULL,
    item TEXT NOT NULL,
    quantity TEXT,
    amount INTEGER NOT NULL,        -- сўмда
    person TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_day ON expenses(chat_id, day);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def add_many(chat_id: int, day: date, entries: list[dict]) -> list[int]:
    ids = []
    with conn() as c:
        for e in entries:
            cur = c.execute(
                "INSERT INTO expenses(chat_id, day, category, item, quantity, amount, person)"
                " VALUES (?,?,?,?,?,?,?)",
                (chat_id, day.isoformat(), e["category"], e["item"],
                 e.get("quantity"), int(e["amount"]), e.get("person")),
            )
            ids.append(cur.lastrowid)
    return ids


def between(chat_id: int, start: date, end: date) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM expenses WHERE chat_id=? AND day BETWEEN ? AND ? ORDER BY day, id",
            (chat_id, start.isoformat(), end.isoformat()),
        ).fetchall()


def last(chat_id: int, n: int = 10) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM expenses WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, n)
        ).fetchall()


def delete(chat_id: int, expense_id: int) -> bool:
    with conn() as c:
        return c.execute(
            "DELETE FROM expenses WHERE chat_id=? AND id=?", (chat_id, expense_id)
        ).rowcount > 0
