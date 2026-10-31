"""Per-session SQLite store: schema, paths, connections, sweep."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import date
from pathlib import Path

from app.config import Settings, get_settings
from app.config import session_hash as session_hash  # noqa: F401  (re-export, R21)

STORE_STEM_RE = re.compile(r"[0-9a-f]{32}")
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{43}")


class InvalidSession(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  sku TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
  cost_cents INTEGER NOT NULL CHECK (cost_cents >= 0),
  stock INTEGER NOT NULL CHECK (stock >= 0),
  lead_time_days INTEGER NOT NULL CHECK (lead_time_days > 0),
  supplier_email TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)));

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  country TEXT NOT NULL CHECK (length(country) = 2),
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('paid','shipped','refunded','cancelled','on_hold')),
  total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
  refunded_cents INTEGER NOT NULL DEFAULT 0 CHECK (refunded_cents >= 0),
  currency TEXT NOT NULL DEFAULT 'usd',
  ship_country TEXT NOT NULL,
  note TEXT,
  carrier TEXT, tracking_number TEXT, shipped_at TEXT,
  stripe_payment_intent_id TEXT);
CREATE INDEX IF NOT EXISTS ix_orders_created ON orders(created_at);

CREATE TABLE IF NOT EXISTS order_items (
  order_id TEXT NOT NULL REFERENCES orders(id),
  product_id TEXT NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL CHECK (qty > 0),
  unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
  PRIMARY KEY (order_id, product_id));

CREATE TABLE IF NOT EXISTS inbox (
  id TEXT PRIMARY KEY,
  from_addr TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
  received_at TEXT NOT NULL,
  order_id TEXT REFERENCES orders(id));

CREATE TABLE IF NOT EXISTS guard_verdicts (
  source_id TEXT PRIMARY KEY,
  allowed INTEGER NOT NULL CHECK (allowed IN (0,1)),
  label TEXT NOT NULL, reason TEXT NOT NULL, score REAL,
  screened_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY, to_email TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
  template TEXT NOT NULL, order_id TEXT REFERENCES orders(id),
  created_at TEXT NOT NULL, recalled_at TEXT);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL CHECK (qty > 0),
  unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents >= 0),
  status TEXT NOT NULL CHECK (status IN ('open','received','cancelled')),
  forecast_json TEXT,
  created_at TEXT NOT NULL, expected_at TEXT);

CREATE TABLE IF NOT EXISTS refunds (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  reason TEXT NOT NULL,
  stripe_refund_id TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL CHECK (mode IN ('test','mock')),
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS payment_links (
  id TEXT PRIMARY KEY, order_id TEXT REFERENCES orders(id),
  customer_id TEXT REFERENCES customers(id),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  stripe_link_id TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL CHECK (mode IN ('test','mock')),
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  request TEXT NOT NULL,
  plan_json TEXT NOT NULL, validations_json TEXT NOT NULL, diff_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('proposed','executing','executed')),
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS step_runs (
  plan_id TEXT NOT NULL REFERENCES plans(id), step_id TEXT NOT NULL,
  audit_id TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (plan_id, step_id));

CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN
    ('session','plan','guard_block','validate','confirm','execute','undo','error')),
  plan_id TEXT, step_id TEXT, tool TEXT,
  payload_json TEXT NOT NULL,
  undo_token TEXT,
  ref_id TEXT REFERENCES audit_log(id),
  prev_hash TEXT NOT NULL, row_hash TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_one_undo ON audit_log(ref_id) WHERE kind = 'undo';
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def store_path(session_id: str, s: Settings) -> Path:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise InvalidSession("invalid session id")
    return s.data_dir / f"{hashlib.sha256(session_id.encode()).hexdigest()[:32]}.db"


@contextmanager
def get_db(session_id: str) -> Iterator[sqlite3.Connection]:
    path = store_path(session_id, get_settings())
    try:  # mode=rw: never create a file (no exists()/connect race)
        conn = sqlite3.connect(
            f"{path.as_uri()}?mode=rw", uri=True, check_same_thread=False, timeout=5
        )
    except sqlite3.OperationalError as e:
        if not path.exists():  # only a missing store means "reseed"; locks/IO errors propagate
            raise FileNotFoundError(path.name) from e
        raise
    try:
        conn.execute("select 1 from sqlite_master limit 1")
    except BaseException:
        conn.close()
        raise
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        conn.close()


def store_exists(session_id: str) -> bool:
    return store_path(session_id, get_settings()).exists()


def touch_store(session_id: str) -> None:
    os.utime(store_path(session_id, get_settings()))


def create_store(session_id: str, anchor: date) -> None:
    """Rebuild the store atomically: write <path>.tmp, then os.replace."""
    from app.seed.generate import seed_store  # lazy: Task 3 owns it

    s = get_settings()
    path = store_path(session_id, s)
    s.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)  # spec 01 §9
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")  # unique per call
    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        init_schema(conn)
        seed_store(conn, anchor)
        conn.commit()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp, path)


def sweep_sessions(now: float | None = None) -> int:
    """Delete idle stores past TTL, then oldest-first until there is room for one more."""
    s = get_settings()
    now = time.time() if now is None else now
    files = []
    for p in s.data_dir.glob("*.db"):
        if not STORE_STEM_RE.fullmatch(p.stem):  # never touch spend.db etc.
            continue
        with suppress(FileNotFoundError):
            files.append((p.stat().st_mtime, p))
    files.sort(key=lambda f: f[0])
    cutoff = now - s.session_ttl_hours * 3600
    doomed = [p for m, p in files if m < cutoff]
    live = [p for m, p in files if m >= cutoff]
    excess = len(live) - (s.max_sessions - 1)
    if excess > 0:
        doomed += live[:excess]
    for p in doomed:
        p.unlink(missing_ok=True)
    return len(doomed)
