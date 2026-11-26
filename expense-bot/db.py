"""SQLite baza. Butun biznes uchun bitta baza (hamma xo'jayinlar bir xil ma'lumotni ko'radi)."""
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
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'cashier')),
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
    salary INTEGER NOT NULL DEFAULT 0,     -- oylik, so'm
    hired_on TEXT,
    fired_on TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    point_id INTEGER REFERENCES points(id),   -- NULL = umumiy (hamma tochkaga)
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
    shift INTEGER NOT NULL DEFAULT 1,       -- smena raqami (1, 2, ...)
    cash INTEGER NOT NULL DEFAULT 0,
    card INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (day, point_id, shift)
);

CREATE TABLE IF NOT EXISTS closings (           -- admin har kuni ertalab yozadigan kunlik hisobot
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    point_id INTEGER NOT NULL REFERENCES points(id),
    total INTEGER NOT NULL,          -- jami savdo (hamma smena)
    card INTEGER NOT NULL,           -- karta / schetga tushgani
    spent INTEGER NOT NULL,          -- shu hisobotdagi xarajatlar jami
    cash_left INTEGER NOT NULL,      -- kassada qolgan naqd (sanalgan)
    expense_ids TEXT,                -- shu hisobot bilan yozilgan xarajatlar (vergul bilan)
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (day, point_id)
);

CREATE TABLE IF NOT EXISTS creditors (          -- kimga qarzdormiz (go'shtchi, bozor, ta'minotchi...)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS debt_moves (         -- + qarz olindi, − qarz to'landi
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creditor_id INTEGER NOT NULL REFERENCES creditors(id),
    day TEXT NOT NULL,
    amount INTEGER NOT NULL,
    note TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance (         -- davomat: kim qaysi kuni ishladi
    day TEXT NOT NULL,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    point_id INTEGER,
    marked_by INTEGER,
    PRIMARY KEY (day, employee_id)
);

CREATE TABLE IF NOT EXISTS yandex (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                        -- hisobga tushgan kun
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
        _migrate_sales_shift(c)
        _migrate_users_admin(c)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(employees)")]
        if "daily_rate" not in cols:  # oylik o'rniga kunlik stavka
            c.execute("ALTER TABLE employees ADD COLUMN daily_rate INTEGER NOT NULL DEFAULT 0")


def _migrate_users_admin(c):
    """Eski bazada users.role faqat owner/cashier bo'lishi mumkin edi — 'admin' ni qo'shamiz."""
    sql = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()["sql"]
    if "'admin'" in sql:
        return
    c.commit()
    c.execute("PRAGMA foreign_keys=OFF")
    c.executescript("""
        CREATE TABLE users_new (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'cashier')),
            point_id INTEGER REFERENCES points(id),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users_new(tg_id, name, role, point_id, active, created_at)
            SELECT tg_id, name, role, point_id, active, created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
    """)
    c.execute("PRAGMA foreign_keys=ON")


def _migrate_sales_shift(c):
    """Eski bazada sales jadvalida smena yo'q edi: jadvalni qayta quramiz, eski yozuvlar 1-smena bo'ladi."""
    cols = [r["name"] for r in c.execute("PRAGMA table_info(sales)")]
    if "shift" in cols:
        return
    c.executescript("""
        CREATE TABLE sales_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            point_id INTEGER NOT NULL REFERENCES points(id),
            shift INTEGER NOT NULL DEFAULT 1,
            cash INTEGER NOT NULL DEFAULT 0,
            card INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (day, point_id, shift)
        );
        INSERT INTO sales_new(id, day, point_id, shift, cash, card, created_by, updated_at)
            SELECT id, day, point_id, 1, cash, card, created_by, updated_at FROM sales;
        DROP TABLE sales;
        ALTER TABLE sales_new RENAME TO sales;
    """)


def audit(tg_id: int, action: str, details: str = ""):
    with conn() as c:
        c.execute("INSERT INTO audit(tg_id, action, details) VALUES (?,?,?)", (tg_id, action, details))


# ---------- tochkalar ----------

def add_point(name: str) -> int:
    with conn() as c:
        return c.execute("INSERT INTO points(name) VALUES (?)", (name.strip(),)).lastrowid


def points(active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM points" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    with conn() as c:
        return c.execute(q).fetchall()


def point_name(point_id) -> str:
    if not point_id:
        return "Umumiy"
    with conn() as c:
        r = c.execute("SELECT name FROM points WHERE id=?", (point_id,)).fetchone()
    return r["name"] if r else f"#{point_id}"


# ---------- foydalanuvchilar ----------

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


def admins_of(point_id) -> list[int]:
    if not point_id:
        return []
    with conn() as c:
        return [r["tg_id"] for r in c.execute(
            "SELECT tg_id FROM users WHERE role='admin' AND active=1 AND point_id=?", (point_id,))]


def cashiers_of(point_id: int) -> list[int]:
    with conn() as c:
        return [r["tg_id"] for r in c.execute(
            "SELECT tg_id FROM users WHERE role='cashier' AND active=1 AND point_id=?", (point_id,))]


# ---------- taklif havolalari ----------

def create_invite(role: str, point_id, created_by: int) -> str:
    code = secrets.token_urlsafe(9)
    expires = (datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)).isoformat()
    with conn() as c:
        c.execute("INSERT INTO invites(code, role, point_id, created_by, expires_at) VALUES (?,?,?,?,?)",
                  (code, role, point_id, created_by, expires))
    return code


def use_invite(code: str, tg_id: int):
    """Havolani bir marta ishlatadi. Yaroqsiz bo'lsa None."""
    now = datetime.now(timezone.utc).isoformat()
    with conn() as c:
        updated = c.execute(
            "UPDATE invites SET used_by=? WHERE code=? AND used_by IS NULL AND expires_at > ?",
            (tg_id, code, now),
        ).rowcount
        if not updated:
            return None
        return c.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()


# ---------- xodimlar ----------

def add_employee(name: str, point_id, rate: int, hired_on: date) -> int:
    """rate — kunlik stavka (so'm)."""
    with conn() as c:
        return c.execute(
            "INSERT INTO employees(name, point_id, daily_rate, hired_on) VALUES (?,?,?,?)",
            (name.strip(), point_id, rate, hired_on.isoformat()),
        ).lastrowid


def employees(active_only: bool = True, point_id=None) -> list[sqlite3.Row]:
    """point_id berilsa — faqat o'sha tochka ishchilari (admin uchun)."""
    where, args = [], []
    if active_only:
        where.append("active=1")
    if point_id:
        where.append("point_id=?")
        args.append(point_id)
    q = "SELECT * FROM employees" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY point_id, name"
    with conn() as c:
        return c.execute(q, args).fetchall()


def get_employee(emp_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()


def set_rate(emp_id: int, rate: int) -> bool:
    """Kunlik stavkani o'rnatadi."""
    with conn() as c:
        return c.execute("UPDATE employees SET daily_rate=? WHERE id=?", (rate, emp_id)).rowcount > 0


# ---------- davomat ----------

def staff_for_point(point_id) -> list[sqlite3.Row]:
    """Tochka ishchilari + hech qaysi tochkaga biriktirilmaganlar."""
    with conn() as c:
        return c.execute("SELECT * FROM employees WHERE active=1 AND (point_id=? OR point_id IS NULL)"
                         " ORDER BY name", (point_id,)).fetchall()


def attendance_of(day: date, point_id) -> set[int]:
    with conn() as c:
        return {r["employee_id"] for r in c.execute(
            "SELECT employee_id FROM attendance WHERE day=? AND point_id=?", (day.isoformat(), point_id))}


def set_attendance(day: date, point_id, employee_ids, by: int):
    """O'sha kun va tochka davomatini to'liq almashtiradi."""
    iso = day.isoformat()
    with conn() as c:
        c.execute("DELETE FROM attendance WHERE day=? AND point_id=?", (iso, point_id))
        for eid in employee_ids:
            c.execute("INSERT INTO attendance(day, employee_id, point_id, marked_by) VALUES (?,?,?,?)"
                      " ON CONFLICT(day, employee_id) DO UPDATE SET point_id=excluded.point_id,"
                      " marked_by=excluded.marked_by", (iso, eid, point_id, by))


def attendance_days(start: date, end: date) -> dict[int, int]:
    """{employee_id: ishlagan kunlar soni} shu oraliqda."""
    with conn() as c:
        return {r["employee_id"]: r["n"] for r in c.execute(
            "SELECT employee_id, COUNT(*) AS n FROM attendance WHERE day BETWEEN ? AND ? GROUP BY employee_id",
            (start.isoformat(), end.isoformat()))}


def fire_employee(emp_id: int, day: date) -> bool:
    with conn() as c:
        return c.execute("UPDATE employees SET active=0, fired_on=? WHERE id=? AND active=1",
                         (day.isoformat(), emp_id)).rowcount > 0


def find_employee(name: str):
    """Ism bo'yicha (katta-kichik harfsiz) faol xodimni topadi."""
    if not name:
        return None
    n = name.strip().lower()
    for e in employees():
        if e["name"].lower() == n:
            return e
    return None


# ---------- xarajatlar ----------

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


def last_expenses(n: int = 10, point_id=None) -> list[sqlite3.Row]:
    with conn() as c:
        if point_id:
            return c.execute("SELECT * FROM expenses WHERE point_id=? ORDER BY id DESC LIMIT ?",
                             (point_id, n)).fetchall()
        return c.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def get_expense(expense_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()


def wipe_records() -> dict:
    """Barcha xarajat, kirim, Yandex va kunlik hisobotlarni o'chiradi. Tochka, ishchi, foydalanuvchilar qoladi."""
    with conn() as c:
        return {t: c.execute(f"DELETE FROM {t}").rowcount
                for t in ("expenses", "sales", "yandex", "closings", "attendance")}


# ---------- kunlik hisobot (admin) ----------

def get_closing(day: date, point_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM closings WHERE day=? AND point_id=?", (day.isoformat(), point_id)).fetchone()


def save_closing(day: date, point_id: int, total: int, card: int, cash_left: int,
                 entries: list[dict], by: int) -> int:
    """Kunlik hisobotni bitta tranzaksiyada saqlaydi:
    xarajatlar -> expenses, savdo -> sales (shift=0, o'sha kunning smena yozuvlari almashtiriladi)."""
    iso = day.isoformat()
    with conn() as c:
        ids = []
        for e in entries:
            ids.append(c.execute(
                "INSERT INTO expenses(day, point_id, category, item, quantity, amount, person,"
                " employee_id, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (iso, point_id, e["category"], e["item"], e.get("quantity"), int(e["amount"]),
                 e.get("person"), e.get("employee_id"), by)).lastrowid)
        c.execute("DELETE FROM sales WHERE day=? AND point_id=?", (iso, point_id))
        c.execute("INSERT INTO sales(day, point_id, shift, cash, card, created_by) VALUES (?,?,0,?,?,?)",
                  (iso, point_id, max(total - card, 0), card, by))
        spent = sum(int(e["amount"]) for e in entries)
        return c.execute(
            "INSERT INTO closings(day, point_id, total, card, spent, cash_left, expense_ids, created_by)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (iso, point_id, total, card, spent, cash_left, ",".join(map(str, ids)), by)).lastrowid


def closings_between(start: date, end: date, point_id=None) -> list[sqlite3.Row]:
    f, args = _point_filter(point_id)
    with conn() as c:
        return c.execute(f"SELECT * FROM closings WHERE day BETWEEN ? AND ?{f} ORDER BY day, point_id",
                         (start.isoformat(), end.isoformat(), *args)).fetchall()


def last_closings(n: int = 10) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM closings ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def delete_closing(closing_id: int):
    """Xo'jayin uchun: hisobotni, uning savdo yozuvini va xarajatlarini o'chiradi."""
    with conn() as c:
        row = c.execute("SELECT * FROM closings WHERE id=?", (closing_id,)).fetchone()
        if not row:
            return None
        ids = [int(x) for x in (row["expense_ids"] or "").split(",") if x]
        if ids:
            c.execute(f"DELETE FROM expenses WHERE id IN ({','.join('?' * len(ids))})", ids)
        c.execute("DELETE FROM sales WHERE day=? AND point_id=? AND shift=0", (row["day"], row["point_id"]))
        c.execute("DELETE FROM closings WHERE id=?", (closing_id,))
        return row


def delete_expense(expense_id: int):
    with conn() as c:
        row = c.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if row:
            c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        return row


# ---------- savdo (naqd / karta) ----------

def get_sale(day: date, point_id: int, shift: int | None = None):
    """shift berilmasa — o'sha kunning istalgan smenasi (eslatma uchun)."""
    with conn() as c:
        if shift is None:
            return c.execute("SELECT * FROM sales WHERE day=? AND point_id=? LIMIT 1",
                             (day.isoformat(), point_id)).fetchone()
        return c.execute("SELECT * FROM sales WHERE day=? AND point_id=? AND shift=?",
                         (day.isoformat(), point_id, shift)).fetchone()


def upsert_sale(day: date, point_id: int, cash: int, card: int, by: int, shift: int = 1):
    with conn() as c:
        c.execute(
            "INSERT INTO sales(day, point_id, shift, cash, card, created_by) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(day, point_id, shift) DO UPDATE SET cash=excluded.cash, card=excluded.card,"
            " created_by=excluded.created_by, updated_at=CURRENT_TIMESTAMP",
            (day.isoformat(), point_id, shift, cash, card, by),
        )


def sales_between(start: date, end: date, point_id=None) -> list[sqlite3.Row]:
    f, args = _point_filter(point_id)
    with conn() as c:
        return c.execute(f"SELECT * FROM sales WHERE day BETWEEN ? AND ?{f} ORDER BY day, point_id, shift",
                         (start.isoformat(), end.isoformat(), *args)).fetchall()


def sales_of_point(point_id: int, n: int = 7) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM sales WHERE point_id=? ORDER BY day DESC LIMIT ?",
                         (point_id, n)).fetchall()


# ---------- Yandex ----------

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
    """.env dagi OWNER_IDS ni har doim xo'jayin qilib turadi."""
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(tg_id, role) VALUES (?, 'owner')", (tg_id,))
        c.execute("UPDATE users SET role='owner', active=1, point_id=NULL WHERE tg_id=?", (tg_id,))


def set_user_name(tg_id: int, name: str):
    with conn() as c:
        c.execute("UPDATE users SET name=? WHERE tg_id=?", (name, tg_id))


def user_names() -> dict[int, tuple[str, str]]:
    """tg_id -> (ism, rol)"""
    with conn() as c:
        return {r["tg_id"]: (r["name"] or str(r["tg_id"]), r["role"]) for r in c.execute("SELECT * FROM users")}


# ---------- qarzlar (biz boshqalarga qarzdormiz) ----------

def creditor_id(name: str) -> int:
    """Ism bo'yicha topadi (katta-kichik harfsiz), yo'q bo'lsa yaratadi."""
    name = " ".join(name.split())
    with conn() as c:
        r = c.execute("SELECT id FROM creditors WHERE name=?", (name,)).fetchone()
        if r:
            return r["id"]
        return c.execute("INSERT INTO creditors(name) VALUES (?)", (name,)).lastrowid


def get_creditor(cid: int):
    with conn() as c:
        return c.execute("SELECT * FROM creditors WHERE id=?", (cid,)).fetchone()


def add_debt_move(cid: int, day: date, amount: int, note, by: int) -> int:
    with conn() as c:
        return c.execute("INSERT INTO debt_moves(creditor_id, day, amount, note, created_by) VALUES (?,?,?,?,?)",
                         (cid, day.isoformat(), amount, note, by)).lastrowid


def debt_balances(only_open: bool = True) -> list[sqlite3.Row]:
    """Har bir kreditor: jami olingan, to'langan, qoldiq. Kattasidan kichigiga."""
    with conn() as c:
        rows = c.execute(
            "SELECT c.id, c.name,"
            " COALESCE(SUM(CASE WHEN m.amount > 0 THEN m.amount END), 0) AS taken,"
            " COALESCE(-SUM(CASE WHEN m.amount < 0 THEN m.amount END), 0) AS paid,"
            " COALESCE(SUM(m.amount), 0) AS balance, MAX(m.day) AS last_day"
            " FROM creditors c LEFT JOIN debt_moves m ON m.creditor_id = c.id"
            " GROUP BY c.id ORDER BY balance DESC, c.name").fetchall()
    return [r for r in rows if r["balance"] != 0] if only_open else rows


def debt_balance(cid: int) -> int:
    with conn() as c:
        return c.execute("SELECT COALESCE(SUM(amount), 0) AS b FROM debt_moves WHERE creditor_id=?",
                         (cid,)).fetchone()["b"]


def debt_history(cid: int, n: int = 15) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM debt_moves WHERE creditor_id=? ORDER BY id DESC LIMIT ?",
                         (cid, n)).fetchall()


def debt_moves_between(start: date, end: date) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT m.*, c.name FROM debt_moves m JOIN creditors c ON c.id = m.creditor_id"
                         " WHERE m.day BETWEEN ? AND ? ORDER BY m.day, m.id",
                         (start.isoformat(), end.isoformat())).fetchall()


def delete_debt_move(move_id: int):
    with conn() as c:
        row = c.execute("SELECT m.*, c.name FROM debt_moves m JOIN creditors c ON c.id = m.creditor_id"
                        " WHERE m.id=?", (move_id,)).fetchone()
        if row:
            c.execute("DELETE FROM debt_moves WHERE id=?", (move_id,))
        return row
