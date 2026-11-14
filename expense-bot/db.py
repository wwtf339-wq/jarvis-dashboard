"""SQLite база. Бутун бизнес учун битта база (ҳамма хўжайинлар бир хил маълумотни кўради)."""
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from config import DB_PATH, INVITE_TTL_HOURS

SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'cashier')),
    point_id INTEGER REFERENCES points(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    point_id INTEGER,
    created_by INTEGER,
    expires_at TEXT NOT NULL,
    used_by INTEGER
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    point_id INTEGER REFERENCES points(id),
    salary INTEGER NOT NULL DEFAULT 0,     -- ойлик, сўм
    hired_on TEXT,
    fired_on TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    point_id INTEGER REFERENCES points(id),   -- NULL = умумий (ҳамма точкага)
    category TEXT NOT NULL,
    item TEXT NOT NULL,
    quantity TEXT,
    amount INTEGER NOT NULL,
    person TEXT,
    employee_id INTEGER REFERENCES employees(id),
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_exp_day ON expenses(day);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    point_id INTEGER NOT NULL REFERENCES points(id),
    cash INTEGER NOT NULL DEFAULT 0,
    card INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (day, point_id)
);

CREATE TABLE IF NOT EXISTS yandex (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                        -- ҳисобга тушган кун
    point_id INTEGER REFERENCES points(id),
    amount INTEGER NOT NULL,
    note TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    tg_id INTEGER,
    action TEXT,
    details TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def audit(tg_id: int, action: str, details: str = ""):
    with conn() as c:
        c.execute("INSERT INTO audit(tg_id, action, details) VALUES (?,?,?)", (tg_id, action, details))


# ---------- точкалар ----------

def add_point(name: str) -> int:
    with conn() as c:
        return c.execute("INSERT INTO points(name) VALUES (?)", (name.strip(),)).lastrowid


def points(active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM points" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    with conn() as c:
        return c.execute(q).fetchall()


def point_name(point_id) -> str:
    if not point_id:
        return "Умумий"
    with conn() as c:
        r = c.execute("SELECT name FROM points WHERE id=?", (point_id,)).fetchone()
    return r["name"] if r else f"#{point_id}"


# ---------- фойдаланувчилар ----------

def get_user(tg_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def upsert_user(tg_id: int, name: str, role: str, point_id=None):
    with conn() as c:
        c.execute(
            "INSERT INTO users(tg_id, name, role, point_id, active) VALUES (?,?,?,?,1)"
            " ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name, role=excluded.role,"
            " point_id=excluded.point_id, active=1",
            (tg_id, name, role, point_id),
        )


def users() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM users ORDER BY role DESC, name").fetchall()


def set_user_active(tg_id: int, active: bool):
    with conn() as c:
        c.execute("UPDATE users SET active=? WHERE tg_id=?", (int(active), tg_id))


def owner_ids() -> list[int]:
    with conn() as c:
        return [r["tg_id"] for r in c.execute("SELECT tg_id FROM users WHERE role='owner' AND active=1")]


def cashiers_of(point_id: int) -> list[int]:
    with conn() as c:
        return [r["tg_id"] for r in c.execute(
            "SELECT tg_id FROM users WHERE role='cashier' AND active=1 AND point_id=?", (point_id,))]


# ---------- таклиф ҳаволалари ----------

def create_invite(role: str, point_id, created_by: int) -> str:
    code = secrets.token_urlsafe(9)
    expires = (datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)).isoformat()
    with conn() as c:
        c.execute("INSERT INTO invites(code, role, point_id, created_by, expires_at) VALUES (?,?,?,?,?)",
                  (code, role, point_id, created_by, expires))
    return code


def use_invite(code: str, tg_id: int):
    """Ҳаволани бир марта ишлатади. Яроқсиз бўлса None."""
    now = datetime.now(timezone.utc).isoformat()
    with conn() as c:
        updated = c.execute(
            "UPDATE invites SET used_by=? WHERE code=? AND used_by IS NULL AND expires_at > ?",
            (tg_id, code, now),
        ).rowcount
        if not updated:
            return None
        return c.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()


# ---------- ходимлар ----------

def add_employee(name: str, point_id, salary: int, hired_on: date) -> int:
    with conn() as c:
        return c.execute(
            "INSERT INTO employees(name, point_id, salary, hired_on) VALUES (?,?,?,?)",
            (name.strip(), point_id, salary, hired_on.isoformat()),
        ).lastrowid


def employees(active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM employees" + (" WHERE active=1" if active_only else "") + " ORDER BY point_id, name"
    with conn() as c:
        return c.execute(q).fetchall()


def get_employee(emp_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()


def set_salary(emp_id: int, salary: int) -> bool:
    with conn() as c:
        return c.execute("UPDATE employees SET salary=? WHERE id=?", (salary, emp_id)).rowcount > 0


def fire_employee(emp_id: int, day: date) -> bool:
    with conn() as c:
        return c.execute("UPDATE employees SET active=0, fired_on=? WHERE id=? AND active=1",
                         (day.isoformat(), emp_id)).rowcount > 0


def find_employee(name: str):
    """Исм бўйича (катта-кичик ҳарфсиз) фаол ходимни топади."""
    if not name:
        return None
    n = name.strip().lower()
    for e in employees():
        if e["name"].lower() == n:
            return e
    return None


# ---------- харажатлар ----------

def add_expenses(day: date, point_id, entries: list[dict], by: int) -> list[int]:
    ids = []
    with conn() as c:
        for e in entries:
            ids.append(c.execute(
                "INSERT INTO expenses(day, point_id, category, item, quantity, amount, person,"
                " employee_id, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (day.isoformat(), point_id, e["category"], e["item"], e.get("quantity"),
                 int(e["amount"]), e.get("person"), e.get("employee_id"), by),
            ).lastrowid)
    return ids


def _point_filter(point_id):
    return ("", ()) if point_id is None else (" AND point_id=?", (point_id,))


def expenses_between(start: date, end: date, point_id=None) -> list[sqlite3.Row]:
    f, args = _point_filter(point_id)
    with conn() as c:
        return c.execute(f"SELECT * FROM expenses WHERE day BETWEEN ? AND ?{f} ORDER BY day, id",
                         (start.isoformat(), end.isoformat(), *args)).fetchall()


def last_expenses(n: int = 10) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def delete_expense(expense_id: int):
    with conn() as c:
        row = c.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if row:
            c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        return row


# ---------- савдо (нақд / карта) ----------

def get_sale(day: date, point_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM sales WHERE day=? AND point_id=?",
                         (day.isoformat(), point_id)).fetchone()


def upsert_sale(day: date, point_id: int, cash: int, card: int, by: int):
    with conn() as c:
        c.execute(
            "INSERT INTO sales(day, point_id, cash, card, created_by) VALUES (?,?,?,?,?)"
            " ON CONFLICT(day, point_id) DO UPDATE SET cash=excluded.cash, card=excluded.card,"
            " created_by=excluded.created_by, updated_at=CURRENT_TIMESTAMP",
            (day.isoformat(), point_id, cash, card, by),
        )


def sales_between(start: date, end: date, point_id=None) -> list[sqlite3.Row]:
    f, args = _point_filter(point_id)
    with conn() as c:
        return c.execute(f"SELECT * FROM sales WHERE day BETWEEN ? AND ?{f} ORDER BY day, point_id",
                         (start.isoformat(), end.isoformat(), *args)).fetchall()


def sales_of_point(point_id: int, n: int = 7) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM sales WHERE point_id=? ORDER BY day DESC LIMIT ?",
                         (point_id, n)).fetchall()


# ---------- Яндекс ----------

def add_yandex(day: date, point_id, amount: int, note: str | None, by: int) -> int:
    with conn() as c:
        return c.execute("INSERT INTO yandex(day, point_id, amount, note, created_by) VALUES (?,?,?,?,?)",
                         (day.isoformat(), point_id, amount, note, by)).lastrowid


def yandex_between(start: date, end: date, point_id=None) -> list[sqlite3.Row]:
    f, args = _point_filter(point_id)
    with conn() as c:
        return c.execute(f"SELECT * FROM yandex WHERE day BETWEEN ? AND ?{f} ORDER BY day, id",
                         (start.isoformat(), end.isoformat(), *args)).fetchall()


def last_yandex(n: int = 10) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM yandex ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def delete_yandex(yid: int):
    with conn() as c:
        row = c.execute("SELECT * FROM yandex WHERE id=?", (yid,)).fetchone()
        if row:
            c.execute("DELETE FROM yandex WHERE id=?", (yid,))
        return row


def first_sale_day(point_id: int):
    with conn() as c:
        r = c.execute("SELECT MIN(day) AS d FROM sales WHERE point_id=?", (point_id,)).fetchone()
    return date.fromisoformat(r["d"]) if r and r["d"] else None


def ensure_owner(tg_id: int):
    """.env даги OWNER_IDS ни ҳар доим хўжайин қилиб туради."""
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(tg_id, role) VALUES (?, 'owner')", (tg_id,))
        c.execute("UPDATE users SET role='owner', active=1, point_id=NULL WHERE tg_id=?", (tg_id,))


def set_user_name(tg_id: int, name: str):
    with conn() as c:
        c.execute("UPDATE users SET name=? WHERE tg_id=?", (name, tg_id))
