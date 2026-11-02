"""connect.db: which browser owns which connected account, its platform plan, webhook dedupe.

Brief: "If there is a DB already setup, store a mapping from the user object to the account ID."
A "user" is one browser: the hash of its sp_connect cookie (spec 10 §6).
Never stored: onboarding, requirement or capability status (the brief says read it from the API
every time), the contact email, the raw cookie, webhook bodies and keys.
The file sits in DATA_DIR; its stem is not 32 hex chars, so the demo's sweep never deletes it.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  session_hash TEXT PRIMARY KEY,         -- the user: session_hash(sp_connect cookie)
  account_id   TEXT NOT NULL UNIQUE,     -- acct_...: the connected account AND the customer
  display_name TEXT NOT NULL,            -- storefront header (public shop name)
  products_created INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,            -- UTC ISO; the global daily cap counts these
  -- platform plan, written only by the billing webhook (brief: store subscription status)
  sub_id TEXT, sub_status TEXT, sub_price_id TEXT, sub_quantity INTEGER,
  sub_cancel_at_period_end INTEGER, sub_paused INTEGER, sub_updated_at TEXT);
CREATE TABLE IF NOT EXISTS events (      -- webhook dedupe + "recent Stripe events" on the dashboard
  id TEXT PRIMARY KEY,                   -- evt_... (snapshot) or the v2 event id (thin)
  type TEXT NOT NULL,
  account_id TEXT,                       -- related_object.id (thin) or customer_account (snapshot)
  received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_account ON events(account_id, received_at);
"""
PLAN_COLUMNS = (
    "sub_id",
    "sub_status",
    "sub_price_id",
    "sub_quantity",
    "sub_cancel_at_period_end",
    "sub_paused",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    """Open (and on first use create) DATA_DIR/connect.db, like llm/budget.py opens spend.db."""
    s = get_settings()
    s.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(s.data_dir / "connect.db", timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _one(sql: str, args: tuple) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def get_account(session_hash: str) -> dict | None:
    return _one("SELECT * FROM accounts WHERE session_hash = ?", (session_hash,))


def get_by_account_id(account_id: str) -> dict | None:
    return _one("SELECT * FROM accounts WHERE account_id = ?", (account_id,))


def accounts_created_today() -> int:
    today = datetime.now(UTC).date().isoformat()
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE created_at >= ?", (today,)
        ).fetchone()[0]


def insert_account(session_hash: str, account_id: str, display_name: str) -> None:
    """Store the user -> account mapping. A double-click replay of the same create is a no-op."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO accounts (session_hash, account_id, display_name, created_at)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(session_hash) DO NOTHING",
            (session_hash, account_id, display_name, _now()),
        )


def bump_products(session_hash: str) -> int:
    """Count one more product toward the plan's cap; returns the new count."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE accounts SET products_created = products_created + 1 WHERE session_hash = ?",
            (session_hash,),
        )
        return conn.execute(
            "SELECT products_created FROM accounts WHERE session_hash = ?", (session_hash,)
        ).fetchone()[0]


def set_plan(account_id: str, plan: dict | None) -> None:
    """Brief: store the user's subscription status. None (no subscription at all) clears it."""
    values = [None] * len(PLAN_COLUMNS) if plan is None else [plan[c] for c in PLAN_COLUMNS]
    sets = ", ".join(f"{c} = ?" for c in PLAN_COLUMNS)  # fixed column names, values bound below
    sql = f"UPDATE accounts SET {sets}, sub_updated_at = ? WHERE account_id = ?"  # noqa: S608
    with closing(_connect()) as conn, conn:
        conn.execute(sql, (*values, _now(), account_id))


def seen(event_id: str) -> bool:
    """Webhook dedupe: Stripe can deliver the same event more than once."""
    return _one("SELECT 1 FROM events WHERE id = ?", (event_id,)) is not None


def record_event(event_id: str, event_type: str, account_id: str | None) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO events (id, type, account_id, received_at) VALUES (?, ?, ?, ?)",
            (event_id, event_type, account_id, _now()),
        )


def recent_events(account_id: str, limit: int = 5) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT type, received_at FROM events WHERE account_id = ?"
            " ORDER BY received_at DESC, rowid DESC LIMIT ?",
            (account_id, limit),
        )
        return [dict(r) for r in rows]
