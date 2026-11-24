-- Reference copy of the tables Savour Dishes uses on PostgreSQL.
-- You do NOT need to run this: the app creates and upgrades these tables itself on start.

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY ,
    name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    lat DOUBLE PRECISION, lng DOUBLE PRECISION, accuracy DOUBLE PRECISION, location_at TEXT,
    password_hash TEXT, phone_verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY ,
    staff_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    role TEXT NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu (
    id SERIAL PRIMARY KEY ,
    category TEXT NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL,
    emoji TEXT NOT NULL, description TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    is_combo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY ,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service TEXT NOT NULL, location TEXT NOT NULL,
    total INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL,
    started_by INTEGER, served_by INTEGER, served_at TEXT,
    geo_lat DOUBLE PRECISION, geo_lng DOUBLE PRECISION, geo_acc DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY ,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    menu_id INTEGER NOT NULL, name TEXT NOT NULL,
    price INTEGER NOT NULL, qty INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS purchases (
    id SERIAL PRIMARY KEY ,
    item TEXT NOT NULL, supplier TEXT NOT NULL DEFAULT '',
    qty DOUBLE PRECISION NOT NULL, unit_cost DOUBLE PRECISION NOT NULL, total INTEGER NOT NULL,
    date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    trip_id INTEGER, trip_label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY ,
    category TEXT NOT NULL, description TEXT NOT NULL, amount INTEGER NOT NULL,
    date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combo_items (
    combo_id INTEGER NOT NULL, menu_id INTEGER NOT NULL, qty INTEGER NOT NULL,
    pos INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (combo_id, menu_id)
);
CREATE TABLE IF NOT EXISTS price_changes (
    id SERIAL PRIMARY KEY ,
    menu_id INTEGER NOT NULL, name TEXT NOT NULL,
    old_price INTEGER NOT NULL, new_price INTEGER NOT NULL,
    changed_by INTEGER, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_access (
    staff_id INTEGER NOT NULL, area TEXT NOT NULL, allowed INTEGER NOT NULL,
    PRIMARY KEY (staff_id, area)
);
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY ,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    method TEXT NOT NULL, amount INTEGER NOT NULL,
    reference TEXT, status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL, confirmed_by INTEGER, confirmed_at TEXT,
    checkout_id TEXT, note TEXT, auto INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS payments_order_idx ON payments(order_id);
CREATE TABLE IF NOT EXISTS drafts (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT 'Dine in', location TEXT NOT NULL DEFAULT '',
    items TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_drafts (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '', date TEXT NOT NULL, lines TEXT NOT NULL,
    created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    customer_id INTEGER NOT NULL, rating INTEGER, comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wastage (
    id SERIAL PRIMARY KEY,
    item TEXT NOT NULL, qty DOUBLE PRECISION, unit TEXT NOT NULL DEFAULT '', cost INTEGER NOT NULL,
    reason TEXT NOT NULL, date TEXT NOT NULL, recorded_by INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mpesa_receipts (
    trans_id TEXT PRIMARY KEY, amount DOUBLE PRECISION NOT NULL, phone TEXT,
    source TEXT NOT NULL, received_at TEXT NOT NULL, matched_payment INTEGER
);
CREATE TABLE IF NOT EXISTS record_photos (
    kind TEXT NOT NULL, record_id INTEGER NOT NULL, mime TEXT NOT NULL, data TEXT NOT NULL,
    added_by INTEGER, created_at TEXT NOT NULL,
    PRIMARY KEY (kind, record_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_type TEXT NOT NULL, user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL
);
