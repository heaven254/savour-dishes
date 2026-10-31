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
AREAS = ["overview", "orders", "sales", "purchases", "expenses", "transactions", "team", "menu", "customers"]
PAYMENT_METHODS = ("KCB Till", "Cash")
REF_RE = re.compile(r"^[A-Z0-9]{8,12}$")         # an M-Pesa confirmation code, e.g. SJK4H2XYZ1
OWNER_ONLY = "owner"
NEXT_STATUS = {"Pending": "Preparing", "Preparing": "Served"}

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
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
    date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL
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
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    method TEXT NOT NULL, amount INTEGER NOT NULL,
    reference TEXT, status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL, confirmed_by INTEGER, confirmed_at TEXT,
    checkout_id TEXT, note TEXT, auto INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mpesa_receipts (
    trans_id TEXT PRIMARY KEY, amount REAL NOT NULL, phone TEXT,
    source TEXT NOT NULL, received_at TEXT NOT NULL, matched_payment INTEGER
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
HAS_ID = {"customers", "staff", "menu", "orders", "order_items", "purchases", "expenses", "price_changes", "payments"}
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
    # upgrade for combos
    for table, col, typ in (("menu", "is_combo", "INTEGER NOT NULL DEFAULT 0"),
                            ("order_items", "detail", "TEXT NOT NULL DEFAULT ''"),
                            ("combo_items", "pos", "INTEGER NOT NULL DEFAULT 0")):
        have = conn.columns(table)
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    # roles are now just Owner / Staff (older databases used Manager, Chef, Waiter...)
    conn.execute("UPDATE staff SET role='Owner' WHERE role='Manager'")
    conn.execute("UPDATE staff SET role='Staff' WHERE role NOT IN ('Owner','Staff')")
    if conn.execute("SELECT COUNT(*) FROM staff WHERE role='Owner'").fetchone()[0] == 0:
        conn.execute("UPDATE staff SET role='Owner' WHERE id=(SELECT MIN(id) FROM staff)")
    existing = {r[0] for r in conn.execute("SELECT name FROM menu")}
    if existing <= OLD_SAMPLE_DISHES:  # brand-new database, or still the old sample menu
        conn.execute("DELETE FROM menu")
        conn.executemany(
            "INSERT INTO menu (category, name, price, emoji, description) VALUES (?,?,?,?,?)", SEED_MENU
        )
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


def orders_json(rows, geo=False):
    """geo=True adds where the customer can be found (staff only)."""
    out = []
    for o in rows:
        items = db().execute("SELECT name, qty, detail FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        row = {
            "id": f"SD{o['id']:04d}", "customerName": o["cname"], "phone": o["phone"],
            "items": [{"name": i["name"], "qty": i["qty"], "detail": i["detail"]} for i in items],
            "total": o["total"], "service": o["service"], "location": o["location"],
            "status": o["status"], "time": o["created_at"],
            "startedBy": o["started_name"], "servedBy": o["served_name"], "servedAt": o["served_at"],
            "payment": {"method": o["pay_method"], "status": o["pay_status"], "reference": o["pay_ref"],
                        "note": o["pay_note"], "auto": bool(o["pay_auto"])}
                       if o["pay_method"] else None,
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
                "p.id AS pay_id, p.method AS pay_method, p.status AS pay_status, p.reference AS pay_ref, "
                "p.note AS pay_note, p.auto AS pay_auto "
                "FROM orders o JOIN customers c ON c.id=o.customer_id "
                "LEFT JOIN payments p ON p.order_id=o.id "
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
    """Switch a dish on/off (needs the Menu section) and/or change its price (needs the Sales section)."""
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
        if not can_access(g.user, "sales"):
            return err("You don't have access to prices. Ask the owner.", 403)
    conn = db()
    if wants_switch:
        conn.execute("UPDATE menu SET available=? WHERE id=?", (int(d["available"]), menu_id))
    if wants_price and price != m["price"]:
        conn.execute("UPDATE menu SET price=? WHERE id=?", (price, menu_id))
        log_price_change(menu_id, m["name"], m["price"], price)
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
    if not isinstance(pay, dict) or pay.get("method") not in PAYMENT_METHODS:
        return err("Choose how you will pay: KCB Till or Cash.")
    ref = None
    if pay["method"] == "KCB Till" and str(pay.get("reference") or "").strip():
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
    conn.execute("INSERT INTO payments (order_id, method, amount, reference, created_at) VALUES (?,?,?,?,?)",
                 (order_id, pay["method"], total, ref, now()))
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
                           "WHERE o.id=? AND o.customer_id=?", (int(m.group(1)), g.user["id"])).fetchone()
    if not p:
        return err("Order not found.", 404)
    if p["method"] != "KCB Till" or p["status"] == "Paid":
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
                           "WHERE o.id=? AND o.customer_id=?", (int(m.group(1)), g.user["id"])).fetchone()
    if not p:
        return err("Order not found.", 404)
    if p["method"] != "KCB Till" or p["status"] == "Paid":
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


# ---------- customers (staff only) ----------
@app.get("/api/customers")
@require("staff", "customers")
def list_customers():
    rows = db().execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    return jsonify([{"name": r["name"], "phone": r["phone"], "joined": r["created_at"],
                     "location": {"lat": r["lat"], "lng": r["lng"], "accuracy": r["accuracy"], "time": r["location_at"]}
                                 if r["lat"] is not None else None}
                    for r in rows])


# ---------- business records & reports (managers only) ----------
TZ_OFFSET = timedelta(hours=float(os.environ.get("SD_TZ_HOURS", "3")))  # default: East Africa Time
EXPENSE_CATEGORIES = ["Rent", "Salaries", "Utilities", "Transport", "Repairs", "Marketing", "Other"]
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
        return daily.setdefault(dt.isoformat(), {"date": dt.isoformat(), "sales": 0, "spend": 0})

    if first:
        cursor = first
        while cursor <= today_local():
            day(cursor)
            cursor += timedelta(days=1)
    for o in sold:
        day(local_date(o["served_at"] or o["created_at"]))["sales"] += o["total"]
    for p in purchases:
        day(parse_date(p["date"]))["spend"] += p["total"]
    for e in expenses:
        day(parse_date(e["date"]))["spend"] += e["amount"]
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
        "net": sales - total_purchases - total_expenses,
        "average": round(sales / len(sold)) if sold else 0,
        "orders": counts, "daily": series, "topDishes": top, "expenseByCategory": by_category,
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
        {"id": r["id"], "item": r["item"], "supplier": r["supplier"], "qty": r["qty"],
         "unitCost": r["unit_cost"], "total": r["total"], "date": r["date"], "recordedBy": r["by_name"]}
        for r in rows]})


@app.post("/api/purchases")
@require("staff", "purchases")
def add_purchase():
    d = body()
    item = str(d.get("item", "")).strip()
    supplier = str(d.get("supplier", "")).strip()
    qty = number(d.get("qty"), 0.01, 1_000_000)
    unit_cost = number(d.get("unit_cost"), 0, 10_000_000)
    day = parse_date(d.get("date")) if d.get("date") else today_local()
    if not (1 <= len(item) <= 80):
        return err("Please enter the item name.")
    if len(supplier) > 80:
        return err("Supplier name is too long.")
    if qty is None:
        return err("Enter a valid quantity.")
    if unit_cost is None:
        return err("Enter a valid unit cost.")
    if day is None:
        return err("Enter a valid date.")
    cur = db().execute(
        "INSERT INTO purchases (item, supplier, qty, unit_cost, total, date, recorded_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (item, supplier, qty, unit_cost, round(qty * unit_cost), day.isoformat(), g.user["id"], now()))
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
         "date": r["date"], "recordedBy": r["by_name"]} for r in rows]})


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
              "purchases", "expenses", "price_changes", "staff_access", "settings"]


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
