"""
Savour Dishes - backend API (Flask + SQLite)

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000

Add another staff member:
    python app.py create-staff staff02 "Jane Doe" Staff
"""
import base64
import getpass
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SD_DB", os.path.join(BASE_DIR, "saviour.db"))
SESSION_HOURS = 12
SERVICES = {"Dine in", "Room service", "Takeaway"}
ROLES = {"Owner", "Staff"}
# Dashboard areas. Owners can use all of them; staff can too unless the owner switches one off.
AREAS = ["overview", "today", "orders", "sales", "purchases", "expenses", "transactions", "profit", "team", "menu", "customers", "feedback"]
PAYMENT_METHODS = ("KCB Till", "Cash")
REF_RE = re.compile(r"^[A-Z0-9]{8,12}$")         # an M-Pesa confirmation code, e.g. SJK4H2XYZ1
OWNER_ONLY = "owner"
NEXT_STATUS = {"Pending": "Preparing", "Preparing": "Served"}

def _static_dir():
    """The website folder. Accepts `static` or `Static`: uploading through some phones/browsers capitalises it,
    and servers like Render treat the two as different folders."""
    for name in ("static", "Static"):
        if os.path.isfile(os.path.join(BASE_DIR, name, "index.html")):
            return os.path.join(BASE_DIR, name)
    return os.path.join(BASE_DIR, "static")


app = Flask(__name__, static_folder=_static_dir(), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # requests are tiny JSON bodies

# The menu board on the wall: (category, name, price in KES, emoji avatar, description)
SEED_MENU = [
    ("Hot Drinks", "African Tea", 50, "🫖", "Hot African tea."),
    ("Hot Drinks", "White Coffee", 50, "☕", "Coffee with milk."),
    ("Hot Drinks", "Black Coffee", 50, "☕", "Coffee without milk."),
    ("Hot Drinks", "Black Tea", 40, "☕", "Tea without milk."),
    ("Hot Drinks", "Lemon/Ginger Tea", 50, "🍋", "Hot tea with lemon or ginger."),
    ("Hot Drinks", "Milk", 100, "🥛", "A glass of milk."),
    ("Breakfast", "Fried Eggs", 60, "🍳", "Fried eggs."),
    ("Breakfast", "Spanish Omelette", 100, "🍳", "Spanish-style omelette."),
    ("Breakfast", "Sweet Potatoes", 50, "🍠", "Sweet potatoes."),
    ("Breakfast", "Mandazi", 15, "🍩", "Kenyan mandazi."),
    ("Breakfast", "Sausage", 60, "🌭", "Sausage."),
    ("Breakfast", "Smokies", 40, "🌭", "Smoked sausage."),
    ("Chapati", "Chapati", 30, "🫓", "Soft layered chapati."),
    ("Chapati", "Chapati Rolex", 100, "🌯", "Chapati rolled with eggs."),
    ("Chapati", "Chapati Beef", 280, "🥩", "Chapati with beef."),
    ("Chapati", "Chapati Beans", 100, "🫘", "Chapati with beans."),
    ("Chapati", "Chapati Ndengu", 100, "🥣", "Chapati with ndengu (green grams)."),
    ("Ugali", "Plain Ugali", 50, "🍚", "Plain ugali."),
    ("Ugali", "Ugali Omena", 100, "🐟", "Ugali with omena (small lake fish)."),
    ("Ugali", "Ugali & Chicken Kienyeji", 350, "🐔", "Ugali with free-range (kienyeji) chicken."),
    ("Ugali", "Ugali & Chicken", 300, "🍗", "Ugali with chicken."),
    ("Ugali", "Ugali Beef Wet Fry", 280, "🥩", "Ugali with beef wet fry."),
    ("Ugali", "Ugali Beef Stew", 280, "🍲", "Ugali with beef stew."),
    ("Ugali", "Ugali Matumbo", 230, "🥘", "Ugali with matumbo (tripe)."),
    ("Ugali", "Ugali & Fish", 450, "🐟", "Ugali with fish."),
    ("Ugali", "Ugali Mboga Kienyeji", 120, "🥬", "Ugali with traditional greens."),
    ("Ugali", "Ugali Mayai", 150, "🥚", "Ugali with eggs."),
    ("Juices", "Mango Juice", 100, "🥭", "Mango juice."),
    ("Juices", "Passion Juice", 150, "🍹", "Passion fruit juice."),
    ("Juices", "Cocktail Juice", 150, "🥤", "Mixed fruit cocktail juice."),
    ("Rice & Chips", "Rice Beef", 280, "🍛", "Rice with beef."),
    ("Rice & Chips", "Rice Ndengu", 150, "🍚", "Rice with ndengu (green grams)."),
    ("Rice & Chips", "Pilau", 200, "🥘", "Spiced pilau rice."),
    ("Rice & Chips", "Chips & Chicken", 400, "🍗", "Chips with chicken."),
    ("Rice & Chips", "Chips", 150, "🍟", "A plate of chips."),
]

# Real photos (from the shop's own board and sign) shown instead of the emoji avatar.
# To add one: put the file in static/img/ and add the dish name here. No database change needed.
DISH_PHOTOS = {
    "White Coffee": "white-coffee.jpg",
    "Spanish Omelette": "spanish-omelette.jpg",
    "Chapati Rolex": "chapati-rolex.jpg",
    "Ugali & Fish": "ugali-fish.jpg",
    "Mango Juice": "mango-juice.jpg",
    "Chips": "chips.jpg",
}

# The sample menu this project shipped with earlier; it is swapped for the real menu once.
OLD_SAMPLE_DISHES = {"Pilau & Kachumbari", "Ugali & Sukuma Wiki", "Nyama Choma", "Tilapia Fry",
                     "Chapati & Beans", "Chicken Stew", "Masala Chips", "Fresh Juice", "Kenyan Tea"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    lat REAL, lng REAL, accuracy REAL, location_at TEXT
);
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    role TEXT NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL,
    emoji TEXT NOT NULL, description TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    is_combo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service TEXT NOT NULL, location TEXT NOT NULL,
    total INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL,
    started_by INTEGER, served_by INTEGER, served_at TEXT,
    geo_lat REAL, geo_lng REAL, geo_acc REAL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    menu_id INTEGER NOT NULL, name TEXT NOT NULL,
    price INTEGER NOT NULL, qty INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL, supplier TEXT NOT NULL DEFAULT '',
    qty REAL NOT NULL, unit_cost REAL NOT NULL, total INTEGER NOT NULL,
    date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL, description TEXT NOT NULL, amount INTEGER NOT NULL,
    date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combo_items (
    combo_id INTEGER NOT NULL, menu_id INTEGER NOT NULL, qty INTEGER NOT NULL,
    pos INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (combo_id, menu_id)
);
CREATE TABLE IF NOT EXISTS price_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id INTEGER NOT NULL, name TEXT NOT NULL,
    old_price INTEGER NOT NULL, new_price INTEGER NOT NULL,
    changed_by INTEGER, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_access (
    staff_id INTEGER NOT NULL, area TEXT NOT NULL, allowed INTEGER NOT NULL,
    PRIMARY KEY (staff_id, area)
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    method TEXT NOT NULL, amount INTEGER NOT NULL,
    reference TEXT, status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL, confirmed_by INTEGER, confirmed_at TEXT,
    checkout_id TEXT, note TEXT, auto INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mpesa_receipts (
    trans_id TEXT PRIMARY KEY, amount REAL NOT NULL, phone TEXT,
    source TEXT NOT NULL, received_at TEXT NOT NULL, matched_payment INTEGER
);
CREATE INDEX IF NOT EXISTS payments_order_idx ON payments(order_id);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT 'Dine in', location TEXT NOT NULL DEFAULT '',
    items TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    customer_id INTEGER NOT NULL, rating INTEGER, comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wastage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL, qty REAL, unit TEXT NOT NULL DEFAULT '', cost INTEGER NOT NULL,
    reason TEXT NOT NULL, date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_type TEXT NOT NULL, user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL
);
"""


# ---------- database ----------
# SQLite by default (one file, no setup). Set DATABASE_URL=postgresql://user:pass@host/dbname to use PostgreSQL.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
USE_PG = DATABASE_URL.startswith("postgresql://")
if USE_PG:
    import psycopg
    from psycopg_pool import ConnectionPool
    IntegrityError = (sqlite3.IntegrityError, psycopg.errors.IntegrityError)
else:
    IntegrityError = (sqlite3.IntegrityError,)
HAS_ID = {"customers", "staff", "menu", "orders", "order_items", "purchases", "expenses", "price_changes", "payments", "drafts", "wastage", "feedback"}
_pool = None


class Row(tuple):
    """A result row that works as row["name"], row[0] and tuple-unpacking, like sqlite3.Row."""
    _names = ()

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, len(self._names) - 1 - self._names[::-1].index(k))
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._names)


def _row_factory(cursor):
    names = tuple(c.name for c in (cursor.description or ()))
    cls = type("Row", (Row,), {"_names": names})
    return lambda values: cls(values)


class Result:
    """What execute() returns on PostgreSQL: the cursor plus lastrowid, like SQLite's."""
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __iter__(self):
        return iter(self._cur)


class DB:
    """The few things the app needs from a database, the same for SQLite and PostgreSQL."""

    def __init__(self, raw):
        self.raw = raw

    def _pg_sql(self, sql):
        sql = sql.replace("%", "%%").replace("?", "%s")
        sql = re.sub(r"\bAUTOINCREMENT\b", "", sql).replace("INTEGER PRIMARY KEY ", "SERIAL PRIMARY KEY ")
        sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
        return re.sub(r"(?<![A-Za-z])LIKE\b", "ILIKE", sql)       # SQLite's LIKE ignores case; PostgreSQL's doesn't

    def execute(self, sql, params=()):
        if not USE_PG:
            return self.raw.execute(sql, params)
        sql = self._pg_sql(sql)
        m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, re.I)
        returning = bool(m and m.group(1).lower() in HAS_ID and "returning" not in sql.lower())
        try:
            cur = self.raw.execute(sql + (" RETURNING id" if returning else ""), params)
        except psycopg.Error:
            self.raw.rollback()         # a failed statement poisons the whole PostgreSQL transaction
            raise
        return Result(cur, cur.fetchone()[0] if returning else None)

    def executemany(self, sql, rows):
        if not USE_PG:
            return self.raw.executemany(sql, rows)
        with self.raw.cursor() as cur:
            cur.executemany(self._pg_sql(sql), rows)

    def script(self, text):
        if not USE_PG:
            return self.raw.executescript(text)
        for stmt in filter(str.strip, text.split(";")):
            self.execute(stmt)

    def columns(self, table):
        if not USE_PG:
            return {r[1] for r in self.raw.execute(f"PRAGMA table_info({table})")}
        return {r[0] for r in self.raw.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s",
            (table,))}

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


def connect():
    """A new database connection (the web app borrows one per request from a pool when on PostgreSQL)."""
    global _pool
    if USE_PG:
        if _pool is None:
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=int(os.environ.get("SD_DB_POOL", "10")),
                                   kwargs={"row_factory": _row_factory}, open=True)
        return DB(_pool.getconn())
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return DB(raw)


def _close_pool():
    if _pool is not None:
        _pool.close()


import atexit
atexit.register(_close_pool)


def release(conn):
    if USE_PG:
        conn.raw.rollback()         # anything not committed is discarded, as when SQLite closes
        _pool.putconn(conn.raw)
    else:
        conn.raw.close()


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        release(conn)


DIGITS = re.compile(r"[0-9]+")


def normalize_phone(raw):
    """Turns what a person types into one standard form (+2547XXXXXXXX), or None if it is not a phone number.
    Accepts 0712 345 678, 712345678, 254712345678, +254 712 345 678 and other countries' +number."""
    s = re.sub(r"[\s\-().]", "", str(raw or ""))
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
        if len(digits) == 13 and digits.startswith("2540"):      # typed as +254 0712...
            digits = "254" + digits[4:]
        ok = DIGITS.fullmatch(digits) and 8 <= len(digits) <= 15 and digits[0] != "0"
        return "+" + digits if ok else None
    if not DIGITS.fullmatch(s):
        return None
    if len(s) == 10 and s[0] == "0" and s[1] in "17":
        return "+254" + s[1:]
    if len(s) == 12 and s.startswith("254") and s[3] in "17":
        return "+" + s
    if len(s) == 9 and s[0] in "17":
        return "+254" + s
    return None


def migrate_customers(conn):
    """Customers used to sign in with email + password. They now use their phone number only."""
    cols = conn.columns("customers")
    if "email" not in cols and "password_hash" not in cols:
        return
    conn.execute("DROP TABLE IF EXISTS customers_new")
    conn.execute("""CREATE TABLE customers_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        lat REAL, lng REAL, accuracy REAL, location_at TEXT)""")
    first = {}
    for cid, name, phone, created in conn.execute(
            "SELECT id, name, phone, created_at FROM customers ORDER BY id").fetchall():
        p = normalize_phone(phone) or f"unverified-{cid}"
        if p in first:      # two old accounts with the same number become one
            conn.execute("UPDATE orders SET customer_id=? WHERE customer_id=?", (first[p], cid))
            conn.execute("UPDATE sessions SET user_id=? WHERE user_type='customer' AND user_id=?", (first[p], cid))
            continue
        first[p] = cid
        conn.execute("INSERT INTO customers_new (id, name, phone, created_at) VALUES (?,?,?,?)",
                     (cid, name, p, created))
    conn.execute("DROP TABLE customers")
    conn.execute("ALTER TABLE customers_new RENAME TO customers")


def init_db():
    conn = connect()
    if not USE_PG:
        conn.raw.execute("PRAGMA foreign_keys = OFF")      # lets the old-account upgrade rebuild the customers table
    conn.script(SCHEMA)
    migrate_customers(conn)
    # upgrade databases created before order tracking existed
    have = conn.columns("orders")
    for col, typ in (("started_by", "INTEGER"), ("served_by", "INTEGER"), ("served_at", "TEXT"),
                     ("geo_lat", "REAL"), ("geo_lng", "REAL"), ("geo_acc", "REAL")):
        if col not in have:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
    have = conn.columns("payments")
    for col, typ in (("checkout_id", "TEXT"), ("note", "TEXT"), ("auto", "INTEGER NOT NULL DEFAULT 0")):
        if col not in have:
            conn.execute(f"ALTER TABLE payments ADD COLUMN {col} {typ}")
    # an order can now be paid in two parts (split payment): drop the old one-payment-per-order rule
    if USE_PG:
        conn.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_order_id_key")
    else:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='payments'").fetchone()
        if row and "UNIQUE" in row[0].upper():
            cols = "id, order_id, method, amount, reference, status, created_at, confirmed_by, confirmed_at, checkout_id, note, auto"
            conn.execute("DROP TABLE IF EXISTS payments_new")
            conn.execute("""CREATE TABLE payments_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
                method TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT, status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL, confirmed_by INTEGER, confirmed_at TEXT,
                checkout_id TEXT, note TEXT, auto INTEGER NOT NULL DEFAULT 0)""")
            conn.execute(f"INSERT INTO payments_new ({cols}) SELECT {cols} FROM payments")
            conn.execute("DROP TABLE payments")
            conn.execute("ALTER TABLE payments_new RENAME TO payments")
            conn.execute("CREATE INDEX IF NOT EXISTS payments_order_idx ON payments(order_id)")
    # upgrade for combos
    for table, col, typ in (("menu", "is_combo", "INTEGER NOT NULL DEFAULT 0"),
                            ("order_items", "detail", "TEXT NOT NULL DEFAULT ''"),
                            ("combo_items", "pos", "INTEGER NOT NULL DEFAULT 0"),
                            ("purchases", "unit", "TEXT NOT NULL DEFAULT ''")):
        have = conn.columns(table)
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    # roles are now just Owner / Staff (older databases used Manager, Chef, Waiter...)
    conn.execute("UPDATE staff SET role='Owner' WHERE role='Manager'")
    conn.execute("UPDATE staff SET role='Staff' WHERE role NOT IN ('Owner','Staff')")
    if conn.execute("SELECT COUNT(*) FROM staff WHERE role='Owner'").fetchone()[0] == 0:
        conn.execute("UPDATE staff SET role='Owner' WHERE id=(SELECT MIN(id) FROM staff)")
    existing = {r[0] for r in conn.execute("SELECT name FROM menu")}
    seeded = conn.execute("SELECT 1 FROM settings WHERE key='menu_seeded'").fetchone()
    if not seeded and existing <= OLD_SAMPLE_DISHES:  # brand-new database, or still the old sample menu (once only)
        conn.execute("DELETE FROM menu")
        conn.executemany(
            "INSERT INTO menu (category, name, price, emoji, description) VALUES (?,?,?,?,?)", SEED_MENU
        )
    if not seeded:      # from now on the menu belongs to the owner: adding or removing dishes is never undone on restart
        conn.execute("INSERT INTO settings (key, value) VALUES ('menu_seeded', '1') ON CONFLICT (key) DO NOTHING")
    if conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0] == 0:
        pw = os.environ.get("SD_ADMIN_PASSWORD")
        default = pw is None
        pw = pw or "saviour123"
        conn.execute(
            "INSERT INTO staff (staff_id, name, role, password_hash) VALUES (?,?,?,?)",
            ("staff01", "Owner", "Owner", generate_password_hash(pw)),
        )
        if default:
            print("WARNING: created staff01 with the DEFAULT password 'saviour123'.\n"
                  "         Set SD_ADMIN_PASSWORD before first run, or change it before going live.")
    conn.commit()
    release(conn)


# ---------- helpers ----------
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def err(message, code=400):
    return jsonify({"error": message}), code


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def new_session(user_type, user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db().execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    db().execute("INSERT INTO sessions VALUES (?,?,?,?)", (sha(token), user_type, user_id, expires))
    db().commit()
    return token


# Simple in-memory brake on password guessing (per IP).
_fails = {}


def too_many_attempts():
    ip = request.remote_addr or "?"
    recent = [t for t in _fails.get(ip, []) if time.time() - t < 300]
    _fails[ip] = recent
    return len(recent) >= 10


def note_failure():
    _fails.setdefault(request.remote_addr or "?", []).append(time.time())


def require(kind, area=None):
    """kind: 'customer' or 'staff'. area: dashboard area a staff member needs (OWNER_ONLY = owner only)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return err("Please log in.", 401)
            row = db().execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                (sha(header[7:]), now()),
            ).fetchone()
            if not row:
                return err("Session expired. Please log in again.", 401)
            if row["user_type"] != kind:
                return err("You do not have access to this.", 403)
            table = "customers" if kind == "customer" else "staff"
            g.user = db().execute(f"SELECT * FROM {table} WHERE id=?", (row["user_id"],)).fetchone()
            if not g.user:
                return err("Account no longer exists.", 401)
            g.token_hash = row["token_hash"]
            if area and not can_access(g.user, area):
                return err("Only the owner can do this." if area == OWNER_ONLY
                           else "You don't have access to this section. Ask the owner.", 403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def customer_json(c):
    # A customer's saved coordinates are never sent back to the browser: only whether a location is shared.
    return {"type": "customer", "name": c["name"], "phone": c["phone"],
            "locationShared": c["lat"] is not None, "locationAt": c["location_at"]}


def staff_json(s):
    return {"type": "staff", "id": s["staff_id"], "name": s["name"], "role": s["role"], "access": access_for(s)}


def menu_json(m):
    return {"id": m["id"], "cat": m["category"], "name": m["name"], "price": m["price"],
            "emoji": m["emoji"], "desc": m["description"], "available": bool(m["available"]),
            "image": "/static/img/" + DISH_PHOTOS[m["name"]] if m["name"] in DISH_PHOTOS else None}


def pay_rows_for(order_ids):
    """{order id: [payment rows]} - an order has one payment, or two when it is paid in two parts (split)."""
    ids, out = list(order_ids), {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for r in db().execute("SELECT * FROM payments WHERE order_id IN (%s) ORDER BY id" % ",".join("?" * len(chunk)), chunk):
            out.setdefault(r["order_id"], []).append(r)
    return out


def pay_summary(rows):
    if not rows:
        return None
    parts = [{"id": f"TX{r['id']:04d}", "method": r["method"], "amount": r["amount"], "status": r["status"],
              "reference": r["reference"], "note": r["note"], "auto": bool(r["auto"])} for r in rows]
    statuses = {p["status"] for p in parts}
    till = next((p for p in parts if p["method"] == "KCB Till"), None)
    return {"method": parts[0]["method"] if len(parts) == 1 else "Split",
            "status": "Paid" if statuses == {"Paid"} else "Pending" if "Pending" in statuses else "Failed",
            "reference": till["reference"] if till else None,
            "note": next((p["note"] for p in parts if p["note"]), None),
            "auto": bool(till and till["auto"]),
            "amount": sum(p["amount"] for p in parts),
            "paid": sum(p["amount"] for p in parts if p["status"] == "Paid"), "parts": parts}


def feedback_for(order_ids):
    ids, out = list(order_ids), {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for r in db().execute("SELECT * FROM feedback WHERE order_id IN (%s)" % ",".join("?" * len(chunk)), chunk):
            out[r["order_id"]] = r
    return out


def orders_json(rows, geo=False):
    """geo=True adds where the customer can be found (staff only)."""
    out = []
    pays = pay_rows_for([o["id"] for o in rows])
    fbs = feedback_for([o["id"] for o in rows])
    for o in rows:
        items = db().execute("SELECT name, qty, detail FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        row = {
            "id": f"SD{o['id']:04d}", "customerName": o["cname"], "phone": o["phone"],
            "items": [{"name": i["name"], "qty": i["qty"], "detail": i["detail"]} for i in items],
            "total": o["total"], "service": o["service"], "location": o["location"],
            "status": o["status"], "time": o["created_at"],
            "startedBy": o["started_name"], "servedBy": o["served_name"], "servedAt": o["served_at"],
            "payment": pay_summary(pays.get(o["id"])),
            "feedback": {"rating": fbs[o["id"]]["rating"], "comment": fbs[o["id"]]["comment"]} if o["id"] in fbs else None,
        }
        if geo:
            if o["geo_lat"] is not None:        # shared with this order
                row["geo"] = {"lat": o["geo_lat"], "lng": o["geo_lng"], "accuracy": o["geo_acc"],
                              "time": o["created_at"], "source": "order"}
            elif o["c_lat"] is not None:        # otherwise the location saved on the customer's account
                row["geo"] = {"lat": o["c_lat"], "lng": o["c_lng"], "accuracy": o["c_acc"],
                              "time": o["c_at"], "source": "profile"}
            else:
                row["geo"] = None
        out.append(row)
    return out


ORDER_SELECT = ("SELECT o.*, c.name AS cname, c.phone AS phone, "
                "c.lat AS c_lat, c.lng AS c_lng, c.accuracy AS c_acc, c.location_at AS c_at, "
                "s1.name AS started_name, s2.name AS served_name, "
                "o.id AS _oid "
                "FROM orders o JOIN customers c ON c.id=o.customer_id "
                "LEFT JOIN staff s1 ON s1.id=o.started_by "
                "LEFT JOIN staff s2 ON s2.id=o.served_by ")

def parse_geo(v):
    """An optional location from the browser: {lat, lng, accuracy?}.
    Returns ((lat, lng, accuracy), None); ((None, None, None), None) when none was sent;
    or (None, error_response) when it is not a real location."""
    if v is None:
        return (None, None, None), None

    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

    bad = err("That location doesn't look right. Please try sharing it again.")
    if not isinstance(v, dict) or not num(v.get("lat")) or not num(v.get("lng")):
        return None, bad
    if not (-90 <= v["lat"] <= 90 and -180 <= v["lng"] <= 180):
        return None, bad
    acc = v.get("accuracy")
    if acc is not None and not (num(acc) and 0 <= acc <= 1_000_000):
        return None, bad
    return (round(float(v["lat"]), 6), round(float(v["lng"]), 6), None if acc is None else round(float(acc))), None


# ---------- auth routes ----------
PHONE_HELP = "Enter a valid phone number, for example 0712 345 678."


@app.post("/api/register")
def register():
    """Sign up with a phone number only (name and location are optional)."""
    d = body()
    phone = normalize_phone(d.get("phone"))
    name = str(d.get("name", "")).strip()
    if not phone:
        return err(PHONE_HELP)
    if len(name) > 80:
        return err("That name is too long.")
    geo, e = parse_geo(d.get("location"))
    if e:
        return e
    name = name or f"Customer {phone[-4:]}"
    try:
        cur = db().execute(
            "INSERT INTO customers (name, phone, created_at, lat, lng, accuracy, location_at) VALUES (?,?,?,?,?,?,?)",
            (name, phone, now(), *geo, now() if geo[0] is not None else None))
        db().commit()
    except IntegrityError:
        return err("This number already has an account. Please log in instead.", 409)
    c = db().execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"token": new_session("customer", c["id"]), "user": customer_json(c)}), 201


@app.post("/api/login/customer")
def login_customer():
    """Log in with a phone number only."""
    if too_many_attempts():
        return err("Too many failed attempts. Try again in a few minutes.", 429)
    phone = normalize_phone(body().get("phone"))
    if not phone:
        return err(PHONE_HELP)
    c = db().execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
    if not c:
        note_failure()
        return err("No account found for that number. Please sign up first.", 404)
    return jsonify({"token": new_session("customer", c["id"]), "user": customer_json(c)})


@app.post("/api/login/staff")
def login_staff():
    if too_many_attempts():
        return err("Too many failed attempts. Try again in a few minutes.", 429)
    d = body()
    s = db().execute("SELECT * FROM staff WHERE staff_id=?", (str(d.get("id", "")).strip().lower(),)).fetchone()
    if not s or not check_password_hash(s["password_hash"], str(d.get("password", ""))):
        note_failure()
        return err("Invalid staff ID or password.", 401)
    return jsonify({"token": new_session("staff", s["id"]), "user": staff_json(s)})


@app.post("/api/logout")
def logout():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        db().execute("DELETE FROM sessions WHERE token_hash=?", (sha(header[7:]),))
        db().commit()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return err("Please log in.", 401)
    row = db().execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                       (sha(header[7:]), now())).fetchone()
    if not row:
        return err("Session expired. Please log in again.", 401)
    if row["user_type"] == "customer":
        c = db().execute("SELECT * FROM customers WHERE id=?", (row["user_id"],)).fetchone()
        return jsonify({"user": customer_json(c)}) if c else err("Please log in.", 401)
    s = db().execute("SELECT * FROM staff WHERE id=?", (row["user_id"],)).fetchone()
    return jsonify({"user": staff_json(s)}) if s else err("Please log in.", 401)


# ---------- customer location (optional, set by the customer) ----------
@app.put("/api/me/location")
@require("customer")
def save_my_location():
    geo, e = parse_geo(body())
    if e:
        return e
    db().execute("UPDATE customers SET lat=?, lng=?, accuracy=?, location_at=? WHERE id=?",
                 (*geo, now(), g.user["id"]))
    db().commit()
    return jsonify({"ok": True})


@app.delete("/api/me/location")
@require("customer")
def remove_my_location():
    db().execute("UPDATE customers SET lat=NULL, lng=NULL, accuracy=NULL, location_at=NULL WHERE id=?",
                 (g.user["id"],))
    db().commit()
    return jsonify({"ok": True})


# ---------- menu, prices & combos ----------
COMBO_CATEGORY = "Combos"
COMBO_EMOJI = "🍱"


def load_menu():
    """Every menu entry as the website needs it. Combos come first. A combo can only be ordered
    when it is switched on AND every dish inside it is available."""
    conn = db()
    rows = conn.execute("SELECT * FROM menu ORDER BY is_combo DESC, id").fetchall()
    by_id = {r["id"]: r for r in rows}
    parts = {}
    for ci in conn.execute("SELECT combo_id, menu_id, qty FROM combo_items ORDER BY combo_id, pos, menu_id"):
        parts.setdefault(ci["combo_id"], []).append((ci["menu_id"], ci["qty"]))
    out = []
    for m in rows:
        d = menu_json(m)
        d["enabled"] = bool(m["available"])      # the on/off switch itself
        d["combo"] = bool(m["is_combo"])
        if m["is_combo"]:
            comps = [(by_id[i], q) for i, q in parts.get(m["id"], []) if i in by_id]
            d["items"] = [{"id": c["id"], "name": c["name"], "qty": q, "price": c["price"]} for c, q in comps]
            d["worth"] = sum(c["price"] * q for c, q in comps)
            d["note"] = m["description"]
            d["available"] = d["enabled"] and bool(comps) and all(c["available"] for c, _ in comps)
            if not m["description"].strip():
                d["desc"] = " + ".join(f"{q}× {c['name']}" if q > 1 else c["name"] for c, q in comps)
        out.append(d)
    return out


def valid_price(v):
    """Whole shillings, 1 to 100,000. Returns the int, or None."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 100000):
        return None
    return v


def log_price_change(menu_id, name, old, new):
    db().execute("INSERT INTO price_changes (menu_id, name, old_price, new_price, changed_by, changed_at) "
                 "VALUES (?,?,?,?,?,?)", (menu_id, name, old, new, g.user["id"], now()))


@app.get("/api/menu")
def get_menu():
    return jsonify(load_menu())


@app.patch("/api/menu/<int:menu_id>")
@require("staff")
def update_menu_item(menu_id):
    """Switch a dish on/off (needs the Menu section) and/or change its price (needs the Menu or Sales section)."""
    d = body()
    m = db().execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone()
    if not m:
        return err("Dish not found.", 404)
    wants_switch, wants_price = "available" in d, "price" in d
    if not (wants_switch or wants_price):
        return err("Nothing to change.")
    price = None
    if wants_switch:
        if not isinstance(d["available"], bool):
            return err("'available' must be true or false.")
        if not can_access(g.user, "menu"):
            return err("You don't have access to the menu section. Ask the owner.", 403)
    if wants_price:
        price = valid_price(d["price"])
        if price is None:
            return err("Enter a whole-number price between 1 and 100,000.")
        if not (can_access(g.user, "sales") or can_access(g.user, "menu")):
            return err("You don't have access to prices. Ask the owner.", 403)
    conn = db()
    if wants_switch:
        conn.execute("UPDATE menu SET available=? WHERE id=?", (int(d["available"]), menu_id))
    if wants_price and price != m["price"]:
        conn.execute("UPDATE menu SET price=? WHERE id=?", (price, menu_id))
        log_price_change(menu_id, m["name"], m["price"], price)
    conn.commit()
    return jsonify({"ok": True})


def clean_dish(d, existing=None):
    """Checks a dish typed in by staff. Returns (fields, None) or (None, error_response).
    `existing` is the current row when editing: anything left out keeps its old value."""
    def pick(key, default=""):
        return d[key] if key in d else (existing[key] if existing is not None else default)
    name = re.sub(r"\s+", " ", str(pick("name")).strip())
    if not (1 <= len(name) <= 60):
        return None, err("Enter the dish name (up to 60 letters).")
    cat = re.sub(r"\s+", " ", str(d["category"] if "category" in d else (existing["category"] if existing is not None else "")).strip())
    if not (1 <= len(cat) <= 30):
        return None, err("Enter a category, for example Ugali or Juices (up to 30 letters).")
    if cat.lower() == "combos":
        return None, err("Combos are made in Sales → Combos. Choose another category.")
    for r in db().execute("SELECT DISTINCT category FROM menu WHERE is_combo=0"):
        if r["category"].lower() == cat.lower():
            cat = r["category"]            # same category as an existing one: keep its spelling
            break
    price = valid_price(d["price"] if "price" in d else (existing["price"] if existing is not None else None))
    if price is None:
        return None, err("Enter a whole-number price between 1 and 100,000.")
    emoji = str(pick("emoji", "🍽️")).strip() or "🍽️"
    if len(emoji) > 12:
        return None, err("The avatar should be a single emoji, like 🍛.")
    desc = str(pick("description")).strip()
    if len(desc) > 120:
        return None, err("Keep the description under 120 letters.")
    own = existing["id"] if existing is not None else None
    dup = ("SELECT 1 FROM menu WHERE lower(name)=lower(?)", (name,)) if own is None else \
          ("SELECT 1 FROM menu WHERE lower(name)=lower(?) AND id != ?", (name, own))
    if db().execute(*dup).fetchone():
        return None, err("There is already a dish or combo with that name.", 409)
    return {"name": name, "category": cat, "price": price, "emoji": emoji, "description": desc}, None


@app.post("/api/menu")
@require("staff", "menu")
def add_dish():
    f, e = clean_dish(body())
    if e:
        return e
    conn = db()
    cur = conn.execute("INSERT INTO menu (category, name, price, emoji, description) VALUES (?,?,?,?,?)",
                       (f["category"], f["name"], f["price"], f["emoji"], f["description"]))
    conn.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.put("/api/menu/<int:menu_id>")
@require("staff", "menu")
def edit_dish(menu_id):
    m = db().execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone()
    if not m:
        return err("Dish not found.", 404)
    if m["is_combo"]:
        return err("Combos are changed in Sales → Combos.", 409)
    f, e = clean_dish(body(), m)
    if e:
        return e
    conn = db()
    conn.execute("UPDATE menu SET category=?, name=?, price=?, emoji=?, description=? WHERE id=?",
                 (f["category"], f["name"], f["price"], f["emoji"], f["description"], menu_id))
    if f["price"] != m["price"]:
        log_price_change(menu_id, f["name"], m["price"], f["price"])
    conn.commit()
    return jsonify({"ok": True})


@app.delete("/api/menu/<int:menu_id>")
@require("staff", "menu")
def delete_dish(menu_id):
    """Removes a dish from the menu. Past orders keep their own copy of its name and price."""
    m = db().execute("SELECT * FROM menu WHERE id=?", (menu_id,)).fetchone()
    if not m:
        return err("Dish not found.", 404)
    if m["is_combo"]:
        return err("Combos are removed in Sales → Combos.", 409)
    used = db().execute("SELECT c.name FROM combo_items i JOIN menu c ON c.id=i.combo_id WHERE i.menu_id=?",
                        (menu_id,)).fetchall()
    if used:
        return err("It is part of the combo " + ", ".join(f"“{r['name']}”" for r in used)
                   + ". Change or remove the combo first, or just mark the dish unavailable.", 409)
    conn = db()
    conn.execute("DELETE FROM menu WHERE id=?", (menu_id,))
    conn.commit()
    return jsonify({"ok": True})


@app.get("/api/price-changes")
@require("staff", "sales")
def list_price_changes():
    rows = db().execute(
        "SELECT p.*, s.name AS by_name FROM price_changes p LEFT JOIN staff s ON s.id=p.changed_by "
        "ORDER BY p.id DESC LIMIT 20").fetchall()
    return jsonify([{"time": r["changed_at"], "name": r["name"], "oldPrice": r["old_price"],
                     "newPrice": r["new_price"], "by": r["by_name"]} for r in rows])


def parse_combo(d, own_id=None):
    """Checks a combo sent by the website. Returns (clean, None) or (None, error_response)."""
    name = str(d.get("name", "")).strip()
    note = str(d.get("description", "")).strip()
    price = valid_price(d.get("price"))
    items = d.get("items")
    if not (1 <= len(name) <= 60):
        return None, err("Please enter a combo name.")
    if len(note) > 120:
        return None, err("The description is too long (120 characters at most).")
    if price is None:
        return None, err("Enter a whole-number combo price between 1 and 100,000.")
    if not isinstance(items, list) or not (1 <= len(items) <= 10):
        return None, err("Add 1 to 10 dishes to the combo.")
    parts = {}
    for it in items:
        ok = (isinstance(it, dict) and isinstance(it.get("id"), int) and not isinstance(it.get("id"), bool)
              and isinstance(it.get("qty"), int) and not isinstance(it.get("qty"), bool))
        if not ok:
            return None, err("Invalid combo items.")
        parts[it["id"]] = parts.get(it["id"], 0) + it["qty"]
    for menu_id, qty in parts.items():
        if not (1 <= qty <= 20):
            return None, err("Each dish can appear 1 to 20 times in a combo.")
        m = db().execute("SELECT is_combo FROM menu WHERE id=?", (menu_id,)).fetchone()
        if not m:
            return None, err("A dish in the combo does not exist.")
        if m["is_combo"]:
            return None, err("A combo cannot contain another combo.")
    dup = ("SELECT 1 FROM menu WHERE lower(name)=lower(?)", (name,)) if own_id is None else \
          ("SELECT 1 FROM menu WHERE lower(name)=lower(?) AND id != ?", (name, own_id))
    if db().execute(*dup).fetchone():
        return None, err("There is already a dish or combo with that name.", 409)
    return {"name": name, "note": note, "price": price, "parts": parts}, None


@app.post("/api/combos")
@require("staff", "sales")
def create_combo():
    c, e = parse_combo(body())
    if e:
        return e
    conn = db()
    cur = conn.execute(
        "INSERT INTO menu (category, name, price, emoji, description, available, is_combo) VALUES (?,?,?,?,?,1,1)",
        (COMBO_CATEGORY, c["name"], c["price"], COMBO_EMOJI, c["note"]))
    conn.executemany("INSERT INTO combo_items (combo_id, menu_id, qty, pos) VALUES (?,?,?,?)",
                     [(cur.lastrowid, i, q, n) for n, (i, q) in enumerate(c["parts"].items())])
    conn.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.put("/api/combos/<int:combo_id>")
@require("staff", "sales")
def update_combo(combo_id):
    old = db().execute("SELECT * FROM menu WHERE id=? AND is_combo=1", (combo_id,)).fetchone()
    if not old:
        return err("Combo not found.", 404)
    c, e = parse_combo(body(), own_id=combo_id)
    if e:
        return e
    conn = db()
    conn.execute("UPDATE menu SET name=?, price=?, description=? WHERE id=?", (c["name"], c["price"], c["note"], combo_id))
    conn.execute("DELETE FROM combo_items WHERE combo_id=?", (combo_id,))
    conn.executemany("INSERT INTO combo_items (combo_id, menu_id, qty, pos) VALUES (?,?,?,?)",
                     [(combo_id, i, q, n) for n, (i, q) in enumerate(c["parts"].items())])
    if c["price"] != old["price"]:
        log_price_change(combo_id, c["name"], old["price"], c["price"])
    conn.commit()
    return jsonify({"ok": True})


@app.delete("/api/combos/<int:combo_id>")
@require("staff", "sales")
def delete_combo(combo_id):
    conn = db()
    if not conn.execute("SELECT 1 FROM menu WHERE id=? AND is_combo=1", (combo_id,)).fetchone():
        return err("Combo not found.", 404)
    conn.execute("DELETE FROM combo_items WHERE combo_id=?", (combo_id,))
    conn.execute("DELETE FROM menu WHERE id=?", (combo_id,))   # past orders keep their own copy of the name and price
    conn.commit()
    return jsonify({"ok": True})


# ---------- orders ----------
@app.post("/api/orders")
@require("customer")
def place_order():
    d = body()
    service = d.get("service")
    location = str(d.get("location", "")).strip()
    items = d.get("items")
    if service not in SERVICES:
        return err("Choose dine in, room service or takeaway.")
    if not (1 <= len(location) <= 40):
        return err("Please enter your table or room number.")
    if not isinstance(items, list) or not (1 <= len(items) <= 30):
        return err("Your order is empty.")
    geo, e = parse_geo(d.get("geo"))        # optional: where to find the customer
    if e:
        return e
    pay = d.get("payment", {"method": "Cash"})      # no choice sent = pay cash
    if not isinstance(pay, dict) or pay.get("method") not in PAYMENT_METHODS + ("Split",):
        return err("Choose how you will pay: KCB Till, Cash or both.")
    ref = None
    if pay["method"] in ("KCB Till", "Split") and str(pay.get("reference") or "").strip():
        ref, e = clean_ref(pay.get("reference"))
        if e:
            return e

    # Prices and availability always come from the database, never the browser.
    wanted = {}
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("id"), int) or not isinstance(it.get("qty"), int):
            return err("Invalid order items.")
        if not (1 <= it["qty"] <= 50):
            return err("Quantity must be between 1 and 50.")
        wanted[it["id"]] = wanted.get(it["id"], 0) + it["qty"]

    menu = {m["id"]: m for m in load_menu()}
    lines, total = [], 0
    for menu_id, qty in wanted.items():
        m = menu.get(menu_id)
        if not m:
            return err("A dish in your order does not exist.")
        if not m["available"]:
            return err(f"Sorry, {m['name']} is currently unavailable.", 409)
        detail = ", ".join(f"{i['qty']}× {i['name']}" for i in m["items"]) if m["combo"] else ""
        lines.append((m["id"], m["name"], m["price"], qty, detail))
        total += m["price"] * qty
    shown = d.get("total")      # the total the customer saw; if prices changed meanwhile, ask them to check
    if isinstance(shown, int) and not isinstance(shown, bool) and shown != total:
        return err("Some prices have changed. Please check your order total and place it again.", 409)

    if pay["method"] == "Split":        # part in cash, the rest by till
        cash = pay.get("cash")
        if isinstance(cash, bool) or not isinstance(cash, (int, float)) or not (1 <= cash < total):
            return err("For a split payment, enter how much you will pay in cash. It must be less than the total.")
        cash = int(round(cash))
        pay_rows = [("Cash", cash, None), ("KCB Till", total - cash, ref)]
    else:
        pay_rows = [(pay["method"], total, ref)]
    conn = db()
    if ref and ref_in_use(ref):
        return err("That M-Pesa code has already been used for another payment.", 409)
    cur = conn.execute(
        "INSERT INTO orders (customer_id, service, location, total, created_at, geo_lat, geo_lng, geo_acc) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (g.user["id"], service, location, total, now(), *geo),
    )
    order_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO order_items (order_id, menu_id, name, price, qty, detail) VALUES (?,?,?,?,?,?)",
        [(order_id, *line) for line in lines],
    )
    for method, amount, reference in pay_rows:
        conn.execute("INSERT INTO payments (order_id, method, amount, reference, created_at) VALUES (?,?,?,?,?)",
                     (order_id, method, amount, reference, now()))
    conn.commit()
    return jsonify({"ok": True, "id": f"SD{order_id:04d}", "total": total, "payment": pay["method"]}), 201


@app.get("/api/orders/mine")
@require("customer")
def my_orders():
    rows = db().execute(ORDER_SELECT + "WHERE o.customer_id=? ORDER BY o.id DESC", (g.user["id"],)).fetchall()
    return jsonify(orders_json(rows))


@app.get("/api/orders")
@require("staff", "orders")
def all_orders():
    rows = db().execute(ORDER_SELECT + "ORDER BY o.id DESC").fetchall()
    return jsonify(orders_json(rows, geo=True))


@app.patch("/api/orders/<code>")
@require("staff", "orders")
def update_order(code):
    m = re.fullmatch(r"SD(\d{1,9})", code)
    if not m:
        return err("Order not found.", 404)
    order_id = int(m.group(1))
    o = db().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not o:
        return err("Order not found.", 404)
    new = body().get("status")
    if NEXT_STATUS.get(o["status"]) != new:
        return err(f"An order that is {o['status']} cannot be changed to {new}.", 409)
    if new == "Preparing":
        db().execute("UPDATE orders SET status=?, started_by=? WHERE id=?", (new, g.user["id"], order_id))
    else:
        db().execute("UPDATE orders SET status=?, served_by=?, served_at=? WHERE id=?",
                     (new, g.user["id"], now(), order_id))
    db().commit()
    return jsonify({"ok": True})


# ---------- customer feedback ----------
@app.post("/api/orders/<code>/feedback")
@require("customer")
def give_feedback(code):
    """Optional: a star rating (1-5) and/or a few words about a served order. Can be changed later."""
    m = re.fullmatch(r"SD(\d{1,9})", code)
    o = m and db().execute("SELECT * FROM orders WHERE id=? AND customer_id=?", (int(m.group(1)), g.user["id"])).fetchone()
    if not o:
        return err("Order not found.", 404)
    if o["status"] != "Served":
        return err("You can rate an order once it has been served.", 409)
    d = body()
    rating = d.get("rating")
    if rating in (None, ""):
        rating = None
    elif type(rating) is not int or not (1 <= rating <= 5):
        return err("Choose between 1 and 5 stars.")
    comment = str(d.get("comment") or "").strip()
    if len(comment) > 500:
        return err("Please keep your comment under 500 characters.")
    if rating is None and not comment:
        return err("Choose a star rating or write a few words.")
    t = now()
    if db().execute("SELECT id FROM feedback WHERE order_id=?", (o["id"],)).fetchone():
        db().execute("UPDATE feedback SET rating=?, comment=?, updated_at=? WHERE order_id=?", (rating, comment, t, o["id"]))
    else:
        db().execute("INSERT INTO feedback (order_id, customer_id, rating, comment, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (o["id"], g.user["id"], rating, comment, t, t))
    db().commit()
    return jsonify({"ok": True})


@app.get("/api/feedback")
@require("staff", "feedback")
def list_feedback():
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    rows = db().execute("SELECT f.*, c.name AS cname FROM feedback f JOIN customers c ON c.id=f.customer_id "
                        "ORDER BY f.updated_at DESC").fetchall()
    rows = [r for r in rows if in_range(local_date(r["updated_at"]), first)]
    rated = [r["rating"] for r in rows if r["rating"]]
    dist = {str(n): rated.count(n) for n in range(1, 6)}
    out = []
    for r in rows:
        its = db().execute("SELECT name, qty FROM order_items WHERE order_id=?", (r["order_id"],)).fetchall()
        out.append({"order": f"SD{r['order_id']:04d}", "customer": r["cname"], "rating": r["rating"], "comment": r["comment"],
                    "items": ", ".join(f"{i['qty']}× {i['name']}" for i in its), "time": r["updated_at"]})
    return jsonify({"count": len(rows), "rated": len(rated), "average": round(sum(rated) / len(rated), 1) if rated else None,
                    "happy": round(sum(1 for x in rated if x >= 4) / len(rated) * 100) if rated else None,
                    "distribution": dist, "rows": out})


# ---------- payments: KCB Till or cash ----------
def clean_ref(raw):
    """Returns (code, None) or (None, error_response) for an M-Pesa confirmation code."""
    code = re.sub(r"\s+", "", str(raw or "")).upper()
    if not REF_RE.match(code):
        return None, err("That M-Pesa code doesn't look right. It is 8-12 letters and numbers, e.g. SJK4H2XYZ1.")
    return code, None


def ref_in_use(code, except_payment=None):
    sql, args = "SELECT id FROM payments WHERE reference=? AND status!='Failed'", [code]
    if except_payment is not None:
        sql += " AND id != ?"; args.append(except_payment)
    return bool(db().execute(sql, args).fetchone())


def till_number():
    row = db().execute("SELECT value FROM settings WHERE key='kcb_till'").fetchone()
    return row["value"] if row else os.environ.get("SD_KCB_TILL", "")


@app.get("/api/payment-info")
def payment_info():
    return jsonify({"methods": list(PAYMENT_METHODS), "till": till_number(), "prompt": mpesa_enabled()})


@app.put("/api/settings/till")
@require("staff", OWNER_ONLY)
def set_till():
    t = re.sub(r"\s+", "", str(body().get("till", "")))
    if t and not re.fullmatch(r"\d{5,10}", t):
        return err("A till number is 5 to 10 digits.")
    if t:
        db().execute("INSERT INTO settings (key, value) VALUES ('kcb_till', ?) "
                     "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (t,))
    else:
        db().execute("DELETE FROM settings WHERE key='kcb_till'")
    db().commit()
    return jsonify({"ok": True, "till": till_number()})


@app.post("/api/orders/<code>/payment-ref")
@require("customer")
def add_payment_ref(code):
    """The customer enters the M-Pesa code after paying to the till."""
    m = re.fullmatch(r"SD(\d{1,9})", code)
    p = m and db().execute("SELECT p.* FROM payments p JOIN orders o ON o.id=p.order_id "
                           "WHERE o.id=? AND o.customer_id=? AND p.method='KCB Till' ORDER BY p.id LIMIT 1",
                           (int(m.group(1)), g.user["id"])).fetchone()
    if not p:
        return err("Order not found.", 404)
    if p["status"] == "Paid":
        return err("This payment can't be changed.", 409)
    ref, e = clean_ref(body().get("reference"))
    if e:
        return e
    if ref_in_use(ref, p["id"]):
        return err("That M-Pesa code has already been used for another payment.", 409)
    db().execute("UPDATE payments SET reference=?, status='Pending' WHERE id=?", (ref, p["id"]))
    db().commit()
    paid = try_auto_confirm(p["id"])        # the money may already have been reported by Safaricom
    return jsonify({"ok": True, "paid": paid})


# ---------- automatic M-Pesa confirmation (Safaricom Daraja) ----------
# Off until these are set. See README. Staff can always confirm by hand instead.
MPESA = {k: os.environ.get(v, "") for k, v in (
    ("key", "SD_MPESA_KEY"), ("secret", "SD_MPESA_SECRET"), ("shortcode", "SD_MPESA_SHORTCODE"),
    ("till", "SD_MPESA_TILL"), ("passkey", "SD_MPESA_PASSKEY"), ("public", "SD_PUBLIC_URL"))}
MPESA_BASE = ("https://api.safaricom.co.ke" if os.environ.get("SD_MPESA_ENV", "sandbox") == "production"
              else "https://sandbox.safaricom.co.ke")
MPESA_PAYBILL = os.environ.get("SD_MPESA_TYPE", "till") == "paybill"     # default: Buy Goods till
_token = {"v": None, "exp": 0}
_last_push = {}


def mpesa_enabled():
    """Prompts on the customer's phone are possible."""
    return all(MPESA[k] for k in ("key", "secret", "shortcode", "passkey", "public")) and MPESA["public"].startswith("https://")


def callback_secret():
    """A random token inside the callback addresses: Safaricom doesn't sign its calls, so only it should know them."""
    row = db().execute("SELECT value FROM settings WHERE key='callback_secret'").fetchone()
    if row:
        return row["value"]
    s = secrets.token_urlsafe(24)
    db().execute("INSERT INTO settings (key, value) VALUES ('callback_secret', ?) ON CONFLICT (key) DO NOTHING", (s,))
    db().commit()
    return db().execute("SELECT value FROM settings WHERE key='callback_secret'").fetchone()["value"]


def mpesa_urls():
    base, s = MPESA["public"].rstrip("/"), callback_secret()
    # Safaricom refuses addresses containing words like "mpesa", so these say "pay"
    return {"stk": f"{base}/api/pay/stk/{s}", "confirmation": f"{base}/api/pay/c2b/{s}/confirmation",
            "validation": f"{base}/api/pay/c2b/{s}/validation"}


def mpesa_call(path, payload=None, basic=None):
    """One request to Safaricom. Returns the decoded JSON; raises RuntimeError with a readable message."""
    headers = {"Content-Type": "application/json"}
    if basic:
        headers["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
    else:
        headers["Authorization"] = "Bearer " + mpesa_token()
    req = urllib.request.Request(MPESA_BASE + path, headers=headers,
                                 data=None if payload is None else json.dumps(payload).encode())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("errorMessage") or e.reason
        except Exception:
            msg = e.reason
        raise RuntimeError(f"M-Pesa said: {msg}")
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RuntimeError("Could not reach M-Pesa. Please try again.")


def mpesa_token():
    if _token["v"] and time.time() < _token["exp"]:
        return _token["v"]
    r = mpesa_call("/oauth/v1/generate?grant_type=client_credentials", basic=f"{MPESA['key']}:{MPESA['secret']}")
    _token["v"], _token["exp"] = r.get("access_token"), time.time() + int(r.get("expires_in", 3599)) - 60
    if not _token["v"]:
        raise RuntimeError("M-Pesa did not accept the app's credentials.")
    return _token["v"]


def record_receipt(trans_id, amount, phone, source):
    """Remember money Safaricom says arrived. Safe to call twice for the same receipt."""
    try:
        db().execute("INSERT INTO mpesa_receipts (trans_id, amount, phone, source, received_at) VALUES (?,?,?,?,?)",
                     (trans_id, float(amount), phone, source, now()))
        db().commit()
    except IntegrityError:
        pass


def try_auto_confirm(payment_id):
    """Mark a till payment Paid when Safaricom has reported a receipt with the same code and enough money.
    Works whichever arrives first: the customer's code or Safaricom's message."""
    p = db().execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not p or p["method"] != "KCB Till" or p["status"] == "Paid" or not p["reference"]:
        return False
    r = db().execute("SELECT * FROM mpesa_receipts WHERE trans_id=? AND matched_payment IS NULL", (p["reference"],)).fetchone()
    if not r:
        return False
    if r["amount"] + 0.005 < p["amount"]:
        db().execute("UPDATE payments SET note=? WHERE id=?",
                     (f"M-Pesa received KES {r['amount']:g}, but this order is KES {p['amount']}. Staff will check.", p["id"]))
        db().commit()
        return False
    db().execute("UPDATE payments SET status='Paid', auto=1, confirmed_by=NULL, confirmed_at=?, note=NULL WHERE id=?",
                 (now(), p["id"]))
    db().execute("UPDATE mpesa_receipts SET matched_payment=? WHERE trans_id=?", (p["id"], r["trans_id"]))
    db().commit()
    return True


@app.get("/api/mpesa/status")
@require("staff", OWNER_ONLY)
def mpesa_status():
    return jsonify({"prompt": mpesa_enabled(), "env": "production" if "api." in MPESA_BASE else "sandbox",
                    "urls": mpesa_urls() if MPESA["public"].startswith("https://") else None})


@app.post("/api/orders/<code>/stk-push")
@require("customer")
def stk_push(code):
    """Sends the M-Pesa payment prompt to the customer's phone."""
    if not mpesa_enabled():
        return err("Automatic M-Pesa isn't set up yet. Pay to the till and enter your code.", 503)
    m = re.fullmatch(r"SD(\d{1,9})", code)
    p = m and db().execute("SELECT p.* FROM payments p JOIN orders o ON o.id=p.order_id "
                           "WHERE o.id=? AND o.customer_id=? AND p.method='KCB Till' ORDER BY p.id LIMIT 1",
                           (int(m.group(1)), g.user["id"])).fetchone()
    if not p:
        return err("Order not found.", 404)
    if p["status"] == "Paid":
        return err("This order doesn't need a payment prompt.", 409)
    phone = normalize_phone(body().get("phone") or g.user["phone"])
    if not phone or not re.fullmatch(r"\+254[17]\d{8}", phone):
        return err("Enter a Kenyan M-Pesa number, like 0712 345 678.")
    if time.time() - _last_push.get(p["id"], 0) < 30:
        return err("A prompt was just sent. Please wait a few seconds, check your phone, then try again.", 429)
    stamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")      # Safaricom clocks are EAT
    till = MPESA["till"] or MPESA["shortcode"]
    payload = {
        "BusinessShortCode": MPESA["shortcode"],
        "Password": base64.b64encode((MPESA["shortcode"] + MPESA["passkey"] + stamp).encode()).decode(),
        "Timestamp": stamp,
        "TransactionType": "CustomerPayBillOnline" if MPESA_PAYBILL else "CustomerBuyGoodsOnline",
        "Amount": int(p["amount"]), "PartyA": phone[1:], "PartyB": till, "PhoneNumber": phone[1:],
        "CallBackURL": mpesa_urls()["stk"], "AccountReference": f"SD{p['order_id']:04d}",
        "TransactionDesc": "Savour Dishes",
    }
    try:
        r = mpesa_call("/mpesa/stkpush/v1/processrequest", payload)
    except RuntimeError as e:
        return err(str(e), 502)
    if str(r.get("ResponseCode")) != "0" or not r.get("CheckoutRequestID"):
        return err(r.get("errorMessage") or r.get("ResponseDescription") or "M-Pesa could not send the prompt.", 502)
    _last_push[p["id"]] = time.time()
    db().execute("UPDATE payments SET checkout_id=?, note=NULL WHERE id=?", (r["CheckoutRequestID"], p["id"]))
    db().commit()
    return jsonify({"ok": True, "message": "Check your phone and enter your M-Pesa PIN."})


def _secret_ok(token):
    return hmac.compare_digest(str(token), callback_secret())


@app.post("/api/pay/stk/<token>")
def stk_callback(token):
    """Safaricom reports what happened to a payment prompt."""
    if not _secret_ok(token):
        return err("Not found.", 404)
    cb = ((body().get("Body") or {}).get("stkCallback")) or {}
    p = db().execute("SELECT * FROM payments WHERE checkout_id=?", (str(cb.get("CheckoutRequestID", "")),)).fetchone()
    if p and p["status"] != "Paid":
        if cb.get("ResultCode") == 0:
            meta = {i.get("Name"): i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])
                    if isinstance(i, dict)}
            receipt = str(meta.get("MpesaReceiptNumber") or "").upper()
            if REF_RE.match(receipt) and isinstance(meta.get("Amount"), (int, float)):
                record_receipt(receipt, meta["Amount"], str(meta.get("PhoneNumber") or ""), "prompt")
                if not ref_in_use(receipt, p["id"]):
                    db().execute("UPDATE payments SET reference=? WHERE id=?", (receipt, p["id"]))
                    db().commit()
                    try_auto_confirm(p["id"])
        else:   # cancelled, timed out, wrong PIN, not enough money...
            db().execute("UPDATE payments SET note=? WHERE id=?",
                         (str(cb.get("ResultDesc") or "The M-Pesa payment was not completed.")[:160], p["id"]))
            db().commit()
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})


@app.post("/api/pay/c2b/<token>/validation")
def c2b_validation(token):
    if not _secret_ok(token):
        return err("Not found.", 404)
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})


@app.post("/api/pay/c2b/<token>/confirmation")
def c2b_confirmation(token):
    """Safaricom reports any payment made to the till (also when the customer paid by hand)."""
    if not _secret_ok(token):
        return err("Not found.", 404)
    d = body()
    trans_id, amount = str(d.get("TransID", "")).upper(), d.get("TransAmount")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = None
    if REF_RE.match(trans_id) and amount is not None:
        record_receipt(trans_id, amount, str(d.get("MSISDN") or ""), "till")
        p = db().execute("SELECT id FROM payments WHERE reference=? AND status!='Paid'", (trans_id,)).fetchone()
        if p:
            try_auto_confirm(p["id"])
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})


TX_SELECT = ("SELECT p.*, o.id AS oid, c.name AS cname, c.phone AS phone, s.name AS by_name "
             "FROM payments p JOIN orders o ON o.id=p.order_id JOIN customers c ON c.id=o.customer_id "
             "LEFT JOIN staff s ON s.id=p.confirmed_by ")


def tx_json(r):
    return {"id": f"TX{r['id']:04d}", "order": f"SD{r['oid']:04d}", "customerName": r["cname"], "phone": r["phone"],
            "amount": r["amount"], "method": r["method"], "status": r["status"], "reference": r["reference"],
            "time": r["created_at"], "confirmedBy": "M-Pesa (automatic)" if r["auto"] else r["by_name"],
            "confirmedAt": r["confirmed_at"], "auto": bool(r["auto"]), "note": r["note"]}


@app.get("/api/transactions")
@require("staff", "transactions")
def transactions():
    """Newest first. Default is the last 20; page through the full history with offset, and filter."""
    q = request.args
    where, args = [], []
    if q.get("method") in PAYMENT_METHODS:
        where.append("p.method=?"); args.append(q["method"])
    if q.get("status") in ("Pending", "Paid", "Failed"):
        where.append("p.status=?"); args.append(q["status"])
    d1, d2 = parse_date(q.get("from")), parse_date(q.get("to"))
    fmt_utc = lambda day: (datetime.combine(day, datetime.min.time()) - TZ_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")
    if d1:
        where.append("p.created_at>=?"); args.append(fmt_utc(d1))
    if d2:
        where.append("p.created_at<?"); args.append(fmt_utc(d2 + timedelta(days=1)))
    text = str(q.get("q", "")).strip()[:40]
    if text:
        like = "%" + text.replace("%", "").replace("_", "") + "%"
        digits = re.sub(r"\D", "", text)
        conds = ["UPPER(p.reference) LIKE UPPER(?)", "c.name LIKE ?", "c.phone LIKE ?"]
        args += [like, like, "%" + (digits[-9:] if len(digits) >= 3 else text) + "%"]
        om = re.fullmatch(r"(?i)sd0*(\d+)", text)          # an order number such as SD0002
        if om:
            conds.append("o.id=?"); args.append(int(om.group(1)))
        where.append("(" + " OR ".join(conds) + ")")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        limit = min(max(int(q.get("limit", 20)), 1), 100)
        offset = max(int(q.get("offset", 0)), 0)
    except ValueError:
        return err("Invalid page.")
    base = " FROM payments p JOIN orders o ON o.id=p.order_id JOIN customers c ON c.id=o.customer_id" + clause
    rows = db().execute(TX_SELECT + clause + " ORDER BY p.id DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
    total = db().execute("SELECT COUNT(*)" + base, args).fetchone()[0]
    sums = db().execute("SELECT p.method, p.status, COALESCE(SUM(p.amount),0) AS amt, COUNT(*) AS n" + base +
                        " GROUP BY p.method, p.status", args).fetchall()
    summary = {"paid": 0, "pending": 0, "paidByMethod": {m: 0 for m in PAYMENT_METHODS}}
    for r in sums:
        if r["status"] == "Paid":
            summary["paid"] += r["amt"]; summary["paidByMethod"][r["method"]] += r["amt"]
        elif r["status"] == "Pending":
            summary["pending"] += r["amt"]
    return jsonify({"items": [tx_json(r) for r in rows], "count": total, "limit": limit, "offset": offset,
                    "summary": summary})


@app.patch("/api/transactions/<tx>")
@require("staff", "transactions")
def update_transaction(tx):
    """Staff confirm that money arrived (Paid) or that it didn't (Failed). A Paid payment is final."""
    m = re.fullmatch(r"TX(\d{1,9})", tx)
    p = m and db().execute("SELECT * FROM payments WHERE id=?", (int(m.group(1)),)).fetchone()
    if not p:
        return err("Transaction not found.", 404)
    d = body()
    if p["status"] == "Paid":
        return err("A confirmed payment can't be changed.", 409)
    method = d.get("method", p["method"])
    if method not in PAYMENT_METHODS:
        return err("Unknown payment method.")
    status = d.get("status", p["status"])
    if status not in ("Pending", "Paid", "Failed"):
        return err("Unknown status.")
    confirmed = (g.user["id"], now()) if status == "Paid" else (None, None)
    db().execute("UPDATE payments SET method=?, status=?, confirmed_by=?, confirmed_at=? WHERE id=?",
                 (method, status, *confirmed, p["id"]))
    db().commit()
    return jsonify({"ok": True})


# ---------- split payments, counter sales and drafts ----------
def parse_parts(raw):
    """Payment parts typed by staff: [{method, amount, status?, reference?}]. Returns (parts, None) or (None, error)."""
    if not isinstance(raw, list) or not (1 <= len(raw) <= 2):
        return None, err("Choose one or two ways of paying.")
    parts, seen = [], set()
    for p in raw:
        if not isinstance(p, dict) or p.get("method") not in PAYMENT_METHODS:
            return None, err("Unknown payment method.")
        if p["method"] in seen:
            return None, err("Use each payment method only once.")
        seen.add(p["method"])
        amount = number(p.get("amount"), 1, 10_000_000)
        if amount is None:
            return None, err("Enter a valid amount for each payment.")
        status = p.get("status") or "Pending"
        if status not in ("Paid", "Pending"):
            return None, err("Unknown payment status.")
        ref = None
        if p["method"] == "KCB Till" and str(p.get("reference") or "").strip():
            ref, e = clean_ref(p.get("reference"))
            if e:
                return None, e
        parts.append({"method": p["method"], "amount": round(amount), "status": status, "ref": ref})
    return parts, None


def apply_parts(order_id, total, parts):
    """Replaces an order's payments that are not confirmed yet. Returns an error response, or None. The caller commits."""
    conn = db()
    paid = [r for r in conn.execute("SELECT * FROM payments WHERE order_id=? AND status='Paid'", (order_id,)).fetchall()]
    left = total - sum(r["amount"] for r in paid)
    if left <= 0:
        return err("This order is already fully paid.", 409)
    if sum(p["amount"] for p in parts) != left:
        return err(f"The payments must add up to KES {left:,}.")
    if {p["method"] for p in parts} & {r["method"] for r in paid}:
        return err("That order already has a confirmed payment by that method.", 409)
    for p in parts:
        if p["ref"] and conn.execute("SELECT id FROM payments WHERE reference=? AND status!='Failed' AND order_id!=?",
                                     (p["ref"], order_id)).fetchone():
            return err("That M-Pesa code has already been used for another payment.", 409)
    conn.execute("DELETE FROM payments WHERE order_id=? AND status!='Paid'", (order_id,))
    for p in parts:
        done = p["status"] == "Paid"
        conn.execute("INSERT INTO payments (order_id, method, amount, reference, status, created_at, confirmed_by, confirmed_at) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (order_id, p["method"], p["amount"], p["ref"], p["status"], now(),
                      g.user["id"] if done else None, now() if done else None))
    return None


@app.put("/api/orders/<code>/payments")
@require("staff", "transactions")
def set_order_payments(code):
    """Split an order's payment between cash and till (or change how it is paid). Confirmed parts stay as they are."""
    m = re.fullmatch(r"SD(\d{1,9})", code)
    o = m and db().execute("SELECT * FROM orders WHERE id=?", (int(m.group(1)),)).fetchone()
    if not o:
        return err("Order not found.", 404)
    parts, e = parse_parts(body().get("parts"))
    if e:
        return e
    e = apply_parts(o["id"], o["total"], parts)
    if e:
        db().rollback()
        return e
    db().commit()
    return jsonify({"ok": True})


def walkin_id():
    """Counter sales belong to one shared 'Walk-in customer' that nobody can sign in as."""
    q = "SELECT id FROM customers WHERE phone='walk-in'"
    r = db().execute(q).fetchone()
    if not r:
        try:
            db().execute("INSERT INTO customers (name, phone, created_at) VALUES ('Walk-in customer', 'walk-in', ?)", (now(),))
            db().commit()
        except IntegrityError:
            db().rollback()
        r = db().execute(q).fetchone()
    return r["id"]


def clean_lines(items):
    """[{id, qty}] -> ({menu id: qty}, None) or (None, error)."""
    if not isinstance(items, list) or not (1 <= len(items) <= 30):
        return None, err("Add at least one dish.")
    wanted = {}
    for it in items:
        if not isinstance(it, dict) or type(it.get("id")) is not int or type(it.get("qty")) is not int:
            return None, err("Invalid items.")
        if not (1 <= it["qty"] <= 50):
            return None, err("Quantity must be between 1 and 50.")
        wanted[it["id"]] = wanted.get(it["id"], 0) + it["qty"]
    return wanted, None


def draft_fields(d):
    """Validated draft contents as a tuple, or (None, error)."""
    wanted, e = clean_lines(d.get("items"))
    if e:
        return None, e
    if not set(wanted) <= {m["id"] for m in load_menu()}:
        return None, err("A dish in this draft does not exist.")
    service = d.get("service") or "Dine in"
    if service not in SERVICES:
        return None, err("Choose dine in, room service or takeaway.")
    label, location, note = (str(d.get(k) or "").strip() for k in ("label", "location", "note"))
    if len(label) > 40 or len(location) > 40 or len(note) > 120:
        return None, err("The name, table or note is too long.")
    return (label, service, location, json.dumps([{"id": i, "qty": q} for i, q in wanted.items()]), note), None


def draft_json(r, menu):
    lines, total, problems = [], 0, []
    for it in json.loads(r["items"]):
        m = menu.get(it["id"])
        if not m:
            problems.append("A dish in this draft was removed from the menu.")
            continue
        lines.append({"id": m["id"], "name": m["name"], "price": m["price"], "qty": it["qty"]})
        total += m["price"] * it["qty"]
        if not m["available"]:
            problems.append(f"{m['name']} is switched off.")
    return {"id": r["id"], "label": r["label"], "service": r["service"], "location": r["location"], "note": r["note"],
            "items": lines, "total": total, "problems": problems, "by": r["by_name"], "updated": r["updated_at"]}


@app.get("/api/drafts")
@require("staff", "sales")
def list_drafts():
    menu = {m["id"]: m for m in load_menu()}
    rows = db().execute("SELECT d.*, s.name AS by_name FROM drafts d LEFT JOIN staff s ON s.id=d.created_by "
                        "ORDER BY d.updated_at DESC, d.id DESC").fetchall()
    return jsonify([draft_json(r, menu) for r in rows])


@app.post("/api/drafts")
@require("staff", "sales")
def add_draft():
    f, e = draft_fields(body())
    if e:
        return e
    t = now()
    cur = db().execute("INSERT INTO drafts (label, service, location, items, note, created_by, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (*f, g.user["id"], t, t))
    db().commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.put("/api/drafts/<int:did>")
@require("staff", "sales")
def update_draft(did):
    f, e = draft_fields(body())
    if e:
        return e
    cur = db().execute("UPDATE drafts SET label=?, service=?, location=?, items=?, note=?, updated_at=? WHERE id=?",
                       (*f, now(), did))
    db().commit()
    return jsonify({"ok": True, "id": did}) if cur.rowcount else err("Draft not found.", 404)


@app.delete("/api/drafts/<int:did>")
@require("staff", "sales")
def delete_draft(did):
    cur = db().execute("DELETE FROM drafts WHERE id=?", (did,))
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Draft not found.", 404)


@app.post("/api/sales")
@require("staff", "sales")
def new_sale():
    """A counter sale: dishes sold across the counter, recorded as served at once. Can be paid in cash, by till, or split."""
    d = body()
    wanted, e = clean_lines(d.get("items"))
    if e:
        return e
    service = d.get("service") or "Takeaway"
    location = str(d.get("location") or "").strip() or "Counter"
    if service not in SERVICES:
        return err("Choose dine in, room service or takeaway.")
    if len(location) > 40:
        return err("The table or room is too long.")
    menu = {m["id"]: m for m in load_menu()}
    lines, total = [], 0
    for menu_id, qty in wanted.items():
        m = menu.get(menu_id)
        if not m:
            return err("A dish in this sale does not exist.")
        if not m["available"]:
            return err(f"{m['name']} is currently switched off. Remove it, or switch it on in Menu.", 409)
        detail = ", ".join(f"{i['qty']}× {i['name']}" for i in m["items"]) if m["combo"] else ""
        lines.append((m["id"], m["name"], m["price"], qty, detail))
        total += m["price"] * qty
    parts, e = parse_parts(d.get("parts") or [{"method": "Cash", "amount": total, "status": "Paid"}])
    if e:
        return e
    if sum(p["amount"] for p in parts) != total:
        return err(f"The payments must add up to the total, KES {total:,}.")
    conn, t, uid = db(), now(), g.user["id"]
    cur = conn.execute(
        "INSERT INTO orders (customer_id, service, location, total, status, created_at, started_by, served_by, served_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (walkin_id(), service, location, total, "Served", t, uid, uid, t))
    order_id = cur.lastrowid
    conn.executemany("INSERT INTO order_items (order_id, menu_id, name, price, qty, detail) VALUES (?,?,?,?,?,?)",
                     [(order_id, *line) for line in lines])
    e = apply_parts(order_id, total, parts)
    if e:
        conn.rollback()
        return e
    if type(d.get("draft_id")) is int:
        conn.execute("DELETE FROM drafts WHERE id=?", (d["draft_id"],))
    conn.commit()
    return jsonify({"ok": True, "id": f"SD{order_id:04d}", "total": total}), 201


# ---------- customers (staff only) ----------
@app.get("/api/customers")
@require("staff", "customers")
def list_customers():
    rows = db().execute("SELECT * FROM customers WHERE phone != 'walk-in' ORDER BY id DESC").fetchall()
    return jsonify([{"name": r["name"], "phone": r["phone"], "joined": r["created_at"],
                     "location": {"lat": r["lat"], "lng": r["lng"], "accuracy": r["accuracy"], "time": r["location_at"]}
                                 if r["lat"] is not None else None}
                    for r in rows])


# ---------- business records & reports (managers only) ----------
TZ_OFFSET = timedelta(hours=float(os.environ.get("SD_TZ_HOURS", "3")))  # default: East Africa Time
EXPENSE_CATEGORIES = ["Rent", "Salaries", "Utilities", "Transport", "Repairs", "Marketing", "Other"]
WASTE_REASONS = ["Spoiled", "Burnt or overcooked", "Unsold leftovers", "Returned by customer", "Spilled or dropped", "Expired", "Other"]
RANGES = ("today", "week", "month", "all")


def today_local():
    return (datetime.now(timezone.utc) + TZ_OFFSET).date()


def local_date(iso):
    return (datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ") + TZ_OFFSET).date()


def parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def get_range():
    """Returns (name, first_day); (None, None) when ?range= is not valid."""
    name = request.args.get("range", "month")
    if name not in RANGES:
        return None, None
    t = today_local()
    first = {"today": t, "week": t - timedelta(days=6), "month": t - timedelta(days=29), "all": None}[name]
    return name, first


def in_range(day, first):
    return first is None or day >= first


def date_filter(first, column="date"):
    return (f"WHERE {column} >= ? ", (first.isoformat(),)) if first else ("", ())


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if low <= value <= high else None


def served_orders(first):
    rows = db().execute(ORDER_SELECT + "WHERE o.status='Served' ORDER BY o.served_at DESC, o.id DESC").fetchall()
    return [o for o in rows if in_range(local_date(o["served_at"] or o["created_at"]), first)]


@app.get("/api/reports/overview")
@require("staff", "overview")
def report_overview():
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    sold = served_orders(first)
    sales = sum(o["total"] for o in sold)
    where, args = date_filter(first)
    purchases = db().execute("SELECT date, total FROM purchases " + where, args).fetchall()
    expenses = db().execute("SELECT date, category, amount FROM expenses " + where, args).fetchall()
    total_purchases = sum(p["total"] for p in purchases)
    total_expenses = sum(e["amount"] for e in expenses)

    counts = {"total": 0, "pending": 0, "preparing": 0, "served": 0}
    for o in db().execute("SELECT status, created_at FROM orders"):
        if in_range(local_date(o["created_at"]), first):
            counts["total"] += 1
            counts[o["status"].lower()] += 1

    daily = {}

    def day(dt):
        return daily.setdefault(dt.isoformat(), {"date": dt.isoformat(), "sales": 0, "purchases": 0, "expenses": 0, "spend": 0})

    if first:
        cursor = first
        while cursor <= today_local():
            day(cursor)
            cursor += timedelta(days=1)
    for o in sold:
        day(local_date(o["served_at"] or o["created_at"]))["sales"] += o["total"]
    for p in purchases:
        day(parse_date(p["date"]))["spend"] += p["total"]
        day(parse_date(p["date"]))["purchases"] += p["total"]
    for e in expenses:
        day(parse_date(e["date"]))["spend"] += e["amount"]
        day(parse_date(e["date"]))["expenses"] += e["amount"]
    series = sorted(daily.values(), key=lambda x: x["date"])[-31:]

    sold_ids = {o["id"] for o in sold}
    dishes = {}
    for it in db().execute("SELECT order_id, name, qty, price FROM order_items"):
        if it["order_id"] in sold_ids:
            row = dishes.setdefault(it["name"], {"name": it["name"], "qty": 0, "revenue": 0})
            row["qty"] += it["qty"]
            row["revenue"] += it["qty"] * it["price"]
    top = sorted(dishes.values(), key=lambda x: (-x["qty"], x["name"]))[:5]

    cats = {}
    for e in expenses:
        cats[e["category"]] = cats.get(e["category"], 0) + e["amount"]
    by_category = sorted(({"category": k, "amount": v} for k, v in cats.items()), key=lambda x: -x["amount"])

    return jsonify({
        "range": name, "sales": sales, "purchases": total_purchases, "expenses": total_expenses,
        "wastage": wastage_block(first)["total"],
        "net": sales - total_purchases - total_expenses,
        "average": round(sales / len(sold)) if sold else 0,
        "orders": counts, "daily": series, "topDishes": top, "expenseByCategory": by_category,
    })


# ---------- profit & loss ----------
PNL_RECORD_LIMIT = 500


def utc_bounds(d1, d2):
    """The UTC timestamps that cover local days d1..d2 inclusive."""
    f = "%Y-%m-%dT%H:%M:%SZ"
    return ((datetime.combine(d1, datetime.min.time()) - TZ_OFFSET).strftime(f),
            (datetime.combine(d2 + timedelta(days=1), datetime.min.time()) - TZ_OFFSET).strftime(f))


def pnl_totals(d1, d2):
    lo, hi = utc_bounds(d1, d2)
    s = db().execute("SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS t FROM orders WHERE status='Served' "
                     "AND COALESCE(served_at, created_at) >= ? AND COALESCE(served_at, created_at) < ?", (lo, hi)).fetchone()
    p = db().execute("SELECT COALESCE(SUM(total),0) AS t FROM purchases WHERE date >= ? AND date <= ?",
                     (d1.isoformat(), d2.isoformat())).fetchone()["t"]
    e = db().execute("SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE date >= ? AND date <= ?",
                     (d1.isoformat(), d2.isoformat())).fetchone()["t"]
    sales, p, e = int(s["t"]), int(p), int(e)
    return {"sales": sales, "orders": s["n"], "purchases": p, "expenses": e, "grossProfit": sales - p, "netProfit": sales - p - e}


@app.get("/api/reports/pnl")
@require("staff", "profit")
def report_pnl():
    """Profit & loss for any period: ?from=YYYY-MM-DD&to=YYYY-MM-DD (local days, both included)."""
    d1, d2 = parse_date(request.args.get("from")), parse_date(request.args.get("to"))
    if not d1 or not d2 or d1 > d2:
        return err("Choose a start day that is on or before the end day.")
    if (d2 - d1).days > 3660:
        return err("Please choose a period of 10 years or less.")
    lo, hi = utc_bounds(d1, d2)
    conn = db()
    served = "o.status='Served' AND COALESCE(o.served_at, o.created_at) >= ? AND COALESCE(o.served_at, o.created_at) < ?"

    cur = pnl_totals(d1, d2)
    days = (d2 - d1).days + 1
    prev = pnl_totals(d1 - timedelta(days=days), d1 - timedelta(days=1))     # the same number of days just before

    # money received for the orders sold in this period
    pay_rows = conn.execute(
        "SELECT p.method, p.status, COALESCE(SUM(p.amount),0) AS amt, COUNT(*) AS n FROM payments p "
        "JOIN orders o ON o.id=p.order_id WHERE " + served + " GROUP BY p.method, p.status", (lo, hi)).fetchall()
    received = {"Cash": 0, "KCB Till": 0}
    waiting = 0
    recorded = 0
    for r in pay_rows:
        recorded += int(r["amt"])
        if r["status"] == "Paid":
            received[r["method"]] = received.get(r["method"], 0) + int(r["amt"])
        else:
            waiting += int(r["amt"])
    payments = {"cash": received.get("Cash", 0), "till": received.get("KCB Till", 0),
                "notConfirmed": waiting, "notRecorded": max(cur["sales"] - recorded, 0)}

    # what sold
    items = conn.execute(
        "SELECT oi.name AS name, oi.qty AS qty, oi.price AS price, COALESCE(m.category, 'Other') AS cat "
        "FROM order_items oi JOIN orders o ON o.id=oi.order_id LEFT JOIN menu m ON m.id=oi.menu_id WHERE " + served,
        (lo, hi)).fetchall()
    dishes, cats = {}, {}
    for it in items:
        d = dishes.setdefault(it["name"], {"name": it["name"], "qty": 0, "revenue": 0})
        d["qty"] += it["qty"]; d["revenue"] += it["qty"] * it["price"]
        cats[it["cat"]] = cats.get(it["cat"], 0) + it["qty"] * it["price"]

    exp_rows = conn.execute("SELECT category, COALESCE(SUM(amount),0) AS amt FROM expenses WHERE date >= ? AND date <= ? "
                            "GROUP BY category", (d1.isoformat(), d2.isoformat())).fetchall()
    sup_rows = conn.execute("SELECT item, COALESCE(SUM(total),0) AS amt FROM purchases WHERE date >= ? AND date <= ? "
                            "GROUP BY item", (d1.isoformat(), d2.isoformat())).fetchall()

    # over time: by day, or by month for long periods
    monthly = days > 62
    buckets = {}

    def bucket(day):
        key = day.strftime("%Y-%m") if monthly else day.isoformat()
        return buckets.setdefault(key, {"label": key, "sales": 0, "purchases": 0, "expenses": 0})
    cursor = d1
    while cursor <= d2:
        bucket(cursor)
        cursor += timedelta(days=1)
    sold_rows = conn.execute(
        "SELECT o.id AS id, o.total AS total, COALESCE(o.served_at, o.created_at) AS at, c.name AS cname, c.phone AS phone "
        "FROM orders o JOIN customers c ON c.id=o.customer_id WHERE " + served + " ORDER BY at DESC, o.id DESC", (lo, hi)).fetchall()
    sale_pays = {k: pay_summary(v) for k, v in pay_rows_for([o["id"] for o in sold_rows[:PNL_RECORD_LIMIT]]).items()}
    w_rows = conn.execute("SELECT reason, COALESCE(SUM(cost),0) AS amt FROM wastage WHERE date >= ? AND date <= ? GROUP BY reason",
                          (d1.isoformat(), d2.isoformat())).fetchall()
    w_total = sum(int(r["amt"]) for r in w_rows)
    w_prev = int(conn.execute("SELECT COALESCE(SUM(cost),0) AS t FROM wastage WHERE date >= ? AND date <= ?",
                              ((d1 - timedelta(days=days)).isoformat(), (d1 - timedelta(days=1)).isoformat())).fetchone()["t"])
    for o in sold_rows:
        bucket(local_date(o["at"]))["sales"] += o["total"]
    pur = conn.execute("SELECT p.*, s.name AS by_name FROM purchases p LEFT JOIN staff s ON s.id=p.recorded_by "
                       "WHERE p.date >= ? AND p.date <= ? ORDER BY p.date DESC, p.id DESC",
                       (d1.isoformat(), d2.isoformat())).fetchall()
    exp = conn.execute("SELECT e.*, s.name AS by_name FROM expenses e LEFT JOIN staff s ON s.id=e.recorded_by "
                       "WHERE e.date >= ? AND e.date <= ? ORDER BY e.date DESC, e.id DESC",
                       (d1.isoformat(), d2.isoformat())).fetchall()
    for p in pur:
        bucket(parse_date(p["date"]))["purchases"] += p["total"]
    for e in exp:
        bucket(parse_date(e["date"]))["expenses"] += e["amount"]
    timeline = sorted(buckets.values(), key=lambda b: b["label"])
    for b in timeline:
        b["net"] = b["sales"] - b["purchases"] - b["expenses"]

    return jsonify({
        "from": d1.isoformat(), "to": d2.isoformat(), "days": days, "by": "month" if monthly else "day",
        "current": cur, "previous": prev,
        "average": round(cur["sales"] / cur["orders"]) if cur["orders"] else 0,
        "margin": round(cur["netProfit"] / cur["sales"] * 100, 1) if cur["sales"] else None,
        "payments": payments,
        "wastage": {"total": w_total, "previous": w_prev,
                    "byReason": sorted(({"reason": r["reason"], "amount": int(r["amt"])} for r in w_rows), key=lambda x: -x["amount"]),
                    "percentOfPurchases": round(w_total / cur["purchases"] * 100, 1) if cur["purchases"] else None},
        "expensesByCategory": sorted(({"category": r["category"], "amount": int(r["amt"])} for r in exp_rows), key=lambda x: -x["amount"]),
        "purchasesByItem": sorted(({"item": r["item"], "amount": int(r["amt"])} for r in sup_rows), key=lambda x: -x["amount"])[:10],
        "salesByCategory": sorted(({"category": k, "amount": v} for k, v in cats.items()), key=lambda x: -x["amount"]),
        "topDishes": sorted(dishes.values(), key=lambda x: (-x["revenue"], x["name"]))[:10],
        "timeline": timeline,
        "records": {
            "limit": PNL_RECORD_LIMIT,
            "sales": [{"id": f"SD{o['id']:04d}", "time": o["at"], "customer": o["cname"], "phone": o["phone"],
                       "total": o["total"], "method": (sale_pays.get(o["id"]) or {}).get("method"),
                       "paid": (sale_pays[o["id"]]["status"] == "Paid") if o["id"] in sale_pays else None}
                      for o in sold_rows[:PNL_RECORD_LIMIT]],
            "purchases": [{"date": p["date"], "item": p["item"], "supplier": p["supplier"], "qty": p["qty"], "unit": p["unit"],
                           "unitCost": p["unit_cost"], "total": p["total"], "by": p["by_name"]} for p in pur[:PNL_RECORD_LIMIT]],
            "expenses": [{"date": e["date"], "category": e["category"], "description": e["description"],
                          "amount": e["amount"], "by": e["by_name"]} for e in exp[:PNL_RECORD_LIMIT]],
            "counts": {"sales": len(sold_rows), "purchases": len(pur), "expenses": len(exp)},
        },
    })


# ---------- business today ----------
@app.get("/api/reports/today")
@require("staff", "today")
def report_today():
    """What happened in the business on one day (today unless ?date=YYYY-MM-DD): money, orders, hours, and a timeline."""
    day = parse_date(request.args.get("date")) if request.args.get("date") else today_local()
    if day is None or day > today_local():
        return err("Choose a day that is today or earlier.")
    lo, hi = utc_bounds(day, day)
    conn = db()
    cur, before = pnl_totals(day, day), pnl_totals(day - timedelta(days=1), day - timedelta(days=1))
    q = lambda sql, *args: conn.execute(sql, args).fetchall()

    served = q("SELECT o.id, o.total, o.location, COALESCE(o.served_at, o.created_at) AS at, c.name AS cname, c.phone AS phone, "
               "s.name AS sname FROM orders o JOIN customers c ON c.id=o.customer_id LEFT JOIN staff s ON s.id=o.served_by "
               "WHERE o.status='Served' AND COALESCE(o.served_at, o.created_at) >= ? AND COALESCE(o.served_at, o.created_at) < ? "
               "ORDER BY at DESC", lo, hi)
    placed = q("SELECT o.id, o.total, o.status, o.created_at, c.name AS cname, c.phone AS phone FROM orders o "
               "JOIN customers c ON c.id=o.customer_id WHERE o.created_at >= ? AND o.created_at < ? ORDER BY o.id DESC", lo, hi)
    counts = {"placed": len(placed), "pending": 0, "preparing": 0, "served": 0}
    for o in placed:
        counts[o["status"].lower()] += 1
    open_now = conn.execute("SELECT COUNT(*) FROM orders WHERE status IN ('Pending','Preparing')").fetchone()[0]

    hours = {h: {"hour": h, "sales": 0, "orders": 0} for h in range(24)}
    team = {}
    for o in served:
        h = (datetime.strptime(o["at"], "%Y-%m-%dT%H:%M:%SZ") + TZ_OFFSET).hour
        hours[h]["sales"] += o["total"]; hours[h]["orders"] += 1
        t = team.setdefault(o["sname"] or "—", {"name": o["sname"] or "—", "served": 0, "sales": 0})
        t["served"] += 1; t["sales"] += o["total"]

    items = q("SELECT oi.name AS name, oi.qty AS qty, oi.price AS price FROM order_items oi JOIN orders o ON o.id=oi.order_id "
              "WHERE o.status='Served' AND COALESCE(o.served_at, o.created_at) >= ? AND COALESCE(o.served_at, o.created_at) < ?", lo, hi)
    dishes = {}
    for it in items:
        d = dishes.setdefault(it["name"], {"name": it["name"], "qty": 0, "revenue": 0})
        d["qty"] += it["qty"]; d["revenue"] += it["qty"] * it["price"]

    money_in = q("SELECT p.id, p.method, p.amount, p.auto, p.confirmed_at, o.id AS oid, s.name AS sname FROM payments p "
                 "JOIN orders o ON o.id=p.order_id LEFT JOIN staff s ON s.id=p.confirmed_by "
                 "WHERE p.status='Paid' AND p.confirmed_at >= ? AND p.confirmed_at < ? ORDER BY p.confirmed_at DESC", lo, hi)
    received = {"cash": 0, "till": 0}
    for p in money_in:
        received["cash" if p["method"] == "Cash" else "till"] += p["amount"]
    waiting = conn.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='Pending'").fetchone()

    iso = day.isoformat()
    buys = q("SELECT p.*, s.name AS sname FROM purchases p LEFT JOIN staff s ON s.id=p.recorded_by WHERE p.date=? ORDER BY p.id DESC", iso)
    spends = q("SELECT e.*, s.name AS sname FROM expenses e LEFT JOIN staff s ON s.id=e.recorded_by WHERE e.date=? ORDER BY e.id DESC", iso)
    waste = q("SELECT w.*, s.name AS sname FROM wastage w LEFT JOIN staff s ON s.id=w.recorded_by WHERE w.date=? ORDER BY w.id DESC", iso)
    wasted = sum(w["cost"] for w in waste)

    feed = []
    code = lambda i: f"SD{i:04d}"
    for o in placed:
        if o["phone"] != "walk-in":
            feed.append({"time": o["created_at"], "type": "order", "text": f"{code(o['id'])} placed by {o['cname']}", "amount": o["total"]})
    for o in served:
        who = f" by {o['sname']}" if o["sname"] else ""
        feed.append({"time": o["at"], "type": "sale" if o["phone"] == "walk-in" else "served",
                     "text": (f"Counter sale {code(o['id'])}" if o["phone"] == "walk-in" else f"{code(o['id'])} served to {o['cname']}") + who,
                     "amount": o["total"]})
    for p in money_in:
        who = "M-Pesa (automatic)" if p["auto"] else p["sname"]
        feed.append({"time": p["confirmed_at"], "type": "payment",
                     "text": f"{p['method']} payment received for {code(p['oid'])}" + (f" · {who}" if who else ""), "amount": p["amount"]})
    for p in buys:
        feed.append({"time": p["created_at"], "type": "purchase", "text": f"Bought {p['item']}" + (f" from {p['supplier']}" if p["supplier"] else ""), "amount": p["total"]})
    for e in spends:
        feed.append({"time": e["created_at"], "type": "expense", "text": f"{e['category']}: {e['description']}", "amount": e["amount"]})
    for w in waste:
        feed.append({"time": w["created_at"], "type": "waste", "text": f"Wasted {w['item']} ({w['reason'].lower()})", "amount": w["cost"]})
    feed.sort(key=lambda x: x["time"], reverse=True)

    return jsonify({
        "date": iso, "isToday": day == today_local(),
        "sales": cur["sales"], "orders": cur["orders"], "average": round(cur["sales"] / cur["orders"]) if cur["orders"] else 0,
        "purchases": cur["purchases"], "expenses": cur["expenses"], "wastage": wasted,
        "net": cur["netProfit"], "yesterday": {"sales": before["sales"], "net": before["netProfit"]},
        "counts": counts, "openNow": open_now,
        "received": {**received, "total": received["cash"] + received["till"]},
        "awaiting": {"count": waiting[0], "amount": int(waiting[1])},
        "drafts": conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
        "hourly": [hours[h] for h in range(24)],
        "topDishes": sorted(dishes.values(), key=lambda x: (-x["qty"], x["name"]))[:5],
        "team": sorted(team.values(), key=lambda x: -x["sales"]),
        "purchasesList": [{"item": p["item"], "total": p["total"], "by": p["sname"]} for p in buys],
        "expensesList": [{"category": e["category"], "description": e["description"], "amount": e["amount"], "by": e["sname"]} for e in spends],
        "wastageList": [{"item": w["item"], "reason": w["reason"], "cost": w["cost"], "qty": w["qty"], "unit": w["unit"], "by": w["sname"]} for w in waste],
        "feed": feed[:60],
    })


@app.get("/api/sales")
@require("staff", "sales")
def list_sales():
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    sold = served_orders(first)
    total = sum(o["total"] for o in sold)
    return jsonify({"total": total, "count": len(sold),
                    "average": round(total / len(sold)) if sold else 0, "orders": orders_json(sold)})


@app.get("/api/purchases")
@require("staff", "purchases")
def list_purchases():
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    where, args = date_filter(first, "p.date")
    rows = db().execute(
        "SELECT p.*, s.name AS by_name FROM purchases p LEFT JOIN staff s ON s.id=p.recorded_by "
        + where + "ORDER BY p.date DESC, p.id DESC", args).fetchall()
    return jsonify({"total": sum(r["total"] for r in rows), "rows": [
        {"id": r["id"], "item": r["item"], "supplier": r["supplier"], "qty": r["qty"], "unit": r["unit"],
         "unitCost": r["unit_cost"], "total": r["total"], "date": r["date"], "recordedBy": r["by_name"]}
        for r in rows]})


@app.post("/api/purchases")
@require("staff", "purchases")
def add_purchase():
    d = body()
    item = str(d.get("item", "")).strip()
    supplier = str(d.get("supplier", "")).strip()
    unit = str(d.get("unit") or "").strip()
    qty = number(d.get("qty"), 0.01, 1_000_000)
    unit_cost = number(d.get("unit_cost"), 0, 10_000_000)
    day = parse_date(d.get("date")) if d.get("date") else today_local()
    if not (1 <= len(item) <= 80):
        return err("Please enter the item name.")
    if len(supplier) > 80:
        return err("Supplier name is too long.")
    if len(unit) > 12:
        return err("The unit is too long, e.g. kg, litres, bags.")
    if qty is None:
        return err("Enter a valid quantity.")
    if unit_cost is None:
        return err("Enter a valid unit cost.")
    if day is None:
        return err("Enter a valid date.")
    cur = db().execute(
        "INSERT INTO purchases (item, supplier, qty, unit_cost, total, date, recorded_by, created_at, unit) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (item, supplier, qty, unit_cost, round(qty * unit_cost), day.isoformat(), g.user["id"], now(), unit))
    db().commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.delete("/api/purchases/<int:pid>")
@require("staff", "purchases")
def delete_purchase(pid):
    cur = db().execute("DELETE FROM purchases WHERE id=?", (pid,))
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Record not found.", 404)


@app.get("/api/expenses")
@require("staff", "expenses")
def list_expenses():
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    where, args = date_filter(first, "e.date")
    rows = db().execute(
        "SELECT e.*, s.name AS by_name FROM expenses e LEFT JOIN staff s ON s.id=e.recorded_by "
        + where + "ORDER BY e.date DESC, e.id DESC", args).fetchall()
    return jsonify({"total": sum(r["amount"] for r in rows), "categories": EXPENSE_CATEGORIES, "rows": [
        {"id": r["id"], "category": r["category"], "description": r["description"], "amount": r["amount"],
         "date": r["date"], "recordedBy": r["by_name"]} for r in rows],
        "wastage": wastage_block(first)})


def wastage_block(first):
    """Food that was thrown away or lost, with what it cost. This money was already spent on purchases,
    so it is shown beside the expenses and never added to them a second time."""
    where, args = date_filter(first, "w.date")
    rows = db().execute("SELECT w.*, s.name AS by_name FROM wastage w LEFT JOIN staff s ON s.id=w.recorded_by "
                        + where + "ORDER BY w.date DESC, w.id DESC", args).fetchall()
    reasons = {}
    for r in rows:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + r["cost"]
    return {"total": sum(r["cost"] for r in rows), "count": len(rows), "reasons": WASTE_REASONS,
            "byReason": sorted(({"reason": k, "amount": v} for k, v in reasons.items()), key=lambda x: -x["amount"]),
            "rows": [{"id": r["id"], "item": r["item"], "qty": r["qty"], "unit": r["unit"], "cost": r["cost"],
                      "reason": r["reason"], "date": r["date"], "recordedBy": r["by_name"]} for r in rows]}


@app.post("/api/wastage")
@require("staff", "expenses")
def add_wastage():
    d = body()
    item = str(d.get("item", "")).strip()
    unit = str(d.get("unit") or "").strip()
    qty = number(d.get("qty"), 0.01, 1_000_000) if d.get("qty") not in (None, "") else None
    cost = number(d.get("cost"), 1, 10_000_000)
    day = parse_date(d.get("date")) if d.get("date") else today_local()
    if not (1 <= len(item) <= 80):
        return err("What food was wasted?")
    if d.get("qty") not in (None, "") and qty is None:
        return err("Enter a valid quantity, or leave it blank.")
    if len(unit) > 12:
        return err("The unit is too long, e.g. kg, plates.")
    if cost is None:
        return err("Enter what the wasted food cost, in KES.")
    if d.get("reason") not in WASTE_REASONS:
        return err("Choose a reason.")
    if day is None:
        return err("Enter a valid date.")
    cur = db().execute("INSERT INTO wastage (item, qty, unit, cost, reason, date, recorded_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                       (item, qty, unit, round(cost), d["reason"], day.isoformat(), g.user["id"], now()))
    db().commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.delete("/api/wastage/<int:wid>")
@require("staff", "expenses")
def delete_wastage(wid):
    cur = db().execute("DELETE FROM wastage WHERE id=?", (wid,))
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Record not found.", 404)


@app.post("/api/expenses")
@require("staff", "expenses")
def add_expense():
    d = body()
    category = d.get("category")
    description = str(d.get("description", "")).strip()
    amount = number(d.get("amount"), 1, 10_000_000)
    day = parse_date(d.get("date")) if d.get("date") else today_local()
    if category not in EXPENSE_CATEGORIES:
        return err("Choose an expense category.")
    if not (1 <= len(description) <= 120):
        return err("Please describe the expense.")
    if amount is None:
        return err("Enter a valid amount.")
    if day is None:
        return err("Enter a valid date.")
    cur = db().execute(
        "INSERT INTO expenses (category, description, amount, date, recorded_by, created_at) VALUES (?,?,?,?,?,?)",
        (category, description, round(amount), day.isoformat(), g.user["id"], now()))
    db().commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.delete("/api/expenses/<int:eid>")
@require("staff", "expenses")
def delete_expense(eid):
    cur = db().execute("DELETE FROM expenses WHERE id=?", (eid,))
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Record not found.", 404)


@app.get("/api/reports/staff")
@require("staff", "team")
def report_staff():
    """Which staff members handled orders: started (accepted into the kitchen) and served."""
    name, first = get_range()
    if name is None:
        return err("Invalid period.")
    started = {}
    for o in db().execute("SELECT started_by, created_at FROM orders WHERE started_by IS NOT NULL"):
        if in_range(local_date(o["created_at"]), first):
            started[o["started_by"]] = started.get(o["started_by"], 0) + 1
    served = {}
    for o in served_orders(first):
        if o["served_by"]:
            row = served.setdefault(o["served_by"], [0, 0])
            row[0] += 1
            row[1] += o["total"]
    rows = []
    for s in db().execute("SELECT id, staff_id, name, role FROM staff"):
        n_served, value = served.get(s["id"], [0, 0])
        rows.append({"id": s["staff_id"], "name": s["name"], "role": s["role"],
                     "started": started.get(s["id"], 0), "served": n_served, "salesValue": value})
    rows.sort(key=lambda r: (-r["salesValue"], -r["started"], r["name"]))
    return jsonify(rows)


# ---------- owner: staff accounts & what staff may open ----------
STAFF_ID_RE = re.compile(r"^[a-z0-9_]{3,20}$")


def access_for(staff_row):
    """Dashboard areas this staff member may open. Owners always get everything."""
    if staff_row["role"] == "Owner":
        return list(AREAS)
    blocked = {r["area"] for r in db().execute(
        "SELECT area FROM staff_access WHERE staff_id=? AND allowed=0", (staff_row["id"],))}
    return [x for x in AREAS if x not in blocked]


def can_access(staff_row, area):
    if staff_row["role"] == "Owner":
        return True
    return area != OWNER_ONLY and area in access_for(staff_row)


@app.get("/api/access")
@require("staff", OWNER_ONLY)
def get_access():
    rows = db().execute("SELECT * FROM staff WHERE role='Staff' ORDER BY name").fetchall()
    return jsonify({"areas": AREAS, "staff": [
        {"id": s["staff_id"], "name": s["name"], "access": access_for(s)} for s in rows]})


@app.put("/api/access/<staff_id>")
@require("staff", OWNER_ONLY)
def set_access(staff_id):
    d = body()
    area, allowed = d.get("area"), d.get("allowed")
    if area not in AREAS or not isinstance(allowed, bool):
        return err("Invalid access setting.")
    s = db().execute("SELECT * FROM staff WHERE staff_id=? AND role='Staff'", (staff_id,)).fetchone()
    if not s:
        return err("Staff member not found.", 404)
    db().execute("INSERT INTO staff_access (staff_id, area, allowed) VALUES (?,?,?) "
                 "ON CONFLICT (staff_id, area) DO UPDATE SET allowed=EXCLUDED.allowed",
                 (s["id"], area, int(allowed)))
    db().commit()
    return jsonify({"ok": True})


@app.post("/api/staff")
@require("staff", OWNER_ONLY)
def add_staff():
    d = body()
    staff_id = str(d.get("id", "")).strip().lower()
    name = str(d.get("name", "")).strip()
    password = str(d.get("password", ""))
    if not STAFF_ID_RE.match(staff_id):
        return err("Staff ID must be 3-20 letters, numbers or underscores.")
    if not (1 <= len(name) <= 60):
        return err("Please enter the staff member's name.")
    if not (8 <= len(password) <= 200):
        return err("Password must be at least 8 characters.")
    try:
        db().execute("INSERT INTO staff (staff_id, name, role, password_hash) VALUES (?,?,?,?)",
                     (staff_id, name, "Staff", generate_password_hash(password)))
        db().commit()
    except IntegrityError:
        return err("That staff ID is already taken.", 409)
    return jsonify({"ok": True}), 201


# ---------- frontend ----------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- CLI ----------
def create_staff(argv):
    if len(argv) != 3 or argv[2] not in ROLES:
        print(f'Usage: python app.py create-staff <id> "<Full Name>" <{"|".join(sorted(ROLES))}>')
        sys.exit(1)
    staff_id, name, role = argv[0].lower(), argv[1], argv[2]
    pw = getpass.getpass("Password (min 8 characters): ")
    if len(pw) < 8 or pw != getpass.getpass("Repeat password: "):
        print("Passwords must match and be at least 8 characters.")
        sys.exit(1)
    conn = connect()
    try:
        conn.execute("INSERT INTO staff (staff_id, name, role, password_hash) VALUES (?,?,?,?)",
                     (staff_id, name, role, generate_password_hash(pw)))
        conn.commit()
        print(f"Staff member '{staff_id}' created.")
    except IntegrityError:
        print("That staff ID already exists.")
        sys.exit(1)


COPY_ORDER = ["staff", "customers", "menu", "combo_items", "orders", "order_items", "payments", "mpesa_receipts",
              "purchases", "expenses", "drafts", "wastage", "feedback", "price_changes", "staff_access", "settings"]


def migrate_to_postgres(argv):
    """python app.py migrate-to-postgres [saviour.db]  - copies an existing SQLite database into PostgreSQL."""
    if not USE_PG:
        print("Set DATABASE_URL=postgresql://... first, so I know where to copy to.")
        sys.exit(1)
    path = argv[0] if argv else DB_PATH
    if not os.path.exists(path):
        print(f"No SQLite file at {path}.")
        sys.exit(1)
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    dst = connect()
    if dst.execute("SELECT COUNT(*) FROM orders").fetchone()[0] or dst.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
        print("The PostgreSQL database already has customers or orders. Use an empty database so nothing gets mixed up.")
        sys.exit(1)
    for t in reversed(COPY_ORDER):          # clear the starter owner and menu that were created on first start
        dst.execute(f"DELETE FROM {t}")
    for t in COPY_ORDER:
        if t not in have:
            continue
        cols = [c for c in (r[1] for r in src.execute(f"PRAGMA table_info({t})")) if c in dst.columns(t)]
        rows = [tuple(r[c] for c in cols) for r in src.execute(f"SELECT {', '.join(cols)} FROM {t}")]
        if rows:
            dst.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
        print(f"  {t}: {len(rows)} rows")
    for t in HAS_ID:                        # new records continue after the copied ones
        dst.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 1), "
                    f"(SELECT MAX(id) FROM {t}) IS NOT NULL)")
    dst.commit()
    print("Done. Customers will need to log in again (sessions are not copied).")


def mpesa_register():
    """python app.py mpesa-register  - tells Safaricom where to send till payment notifications."""
    if not (MPESA["key"] and MPESA["secret"] and MPESA["shortcode"] and MPESA["public"].startswith("https://")):
        print("Set SD_MPESA_KEY, SD_MPESA_SECRET, SD_MPESA_SHORTCODE and SD_PUBLIC_URL (https://...) first.")
        sys.exit(1)
    with app.app_context():
        urls = mpesa_urls()
    try:
        r = mpesa_call("/mpesa/c2b/v1/registerurl", {
            "ShortCode": MPESA["till"] or MPESA["shortcode"], "ResponseType": "Completed",
            "ConfirmationURL": urls["confirmation"], "ValidationURL": urls["validation"]})
    except RuntimeError as e:
        print("Could not register:", e)
        sys.exit(1)
    print("Safaricom replied:", r.get("ResponseDescription") or r)


init_db()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-staff":
        create_staff(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "migrate-to-postgres":
        migrate_to_postgres(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "mpesa-register":
        mpesa_register()
    else:
        app.run(host=os.environ.get("SD_HOST", "127.0.0.1"),
                port=int(os.environ.get("SD_PORT", "5000")), debug=False)
