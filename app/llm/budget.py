"""LLM prices, spend ledger (session + global, per UTC day), concurrency and rate slot."""

import sqlite3
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Literal

from app.config import get_settings, session_hash

# USD per MTok. Source: https://platform.claude.com/docs/en/about-claude/pricing
# (checked 2026-10-30).
# Haiku prices are for prompts <= 100K tokens.
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.10, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
}
_USAGE_KEYS = {
    "input_tokens": "input",
    "cache_creation_input_tokens": "cache_write",
    "cache_read_input_tokens": "cache_read",
    "output_tokens": "output",
}

MAX_CONCURRENT = 4
CALLS_PER_MIN = 60
_WINDOW_S = 60.0

_sem = threading.BoundedSemaphore(MAX_CONCURRENT)
_lock = threading.Lock()
_calls: deque[float] = deque()


class BudgetExceeded(Exception):
    def __init__(self, scope: Literal["session", "global"]):
        super().__init__(f"LLM {scope} budget reached")
        self.scope = scope


class Busy(Exception):
    pass


def cost_usd(model: str, usage: dict) -> float:
    price = PRICES[model]  # unknown model -> KeyError
    return sum((usage.get(k) or 0) * price[p] for k, p in _USAGE_KEYS.items()) / 1_000_000


def worst_case_usd(model: str, est_input_tokens: int, max_tokens: int) -> float:
    price = PRICES[model]
    return (est_input_tokens * price["input"] + max_tokens * price["output"]) / 1_000_000


def _connect() -> sqlite3.Connection:
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.data_dir / "spend.db", timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS spend(day TEXT, session_hash TEXT, usd REAL)")
    return conn


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def record_spend(session_id: str, usd: float) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO spend VALUES (?, ?, ?)", (_today(), session_hash(session_id), float(usd))
        )


def spend_today(session_id: str | None = None) -> float:
    sql, args = "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day = ?", [_today()]
    if session_id is not None:
        sql += " AND session_hash = ?"
        args.append(session_hash(session_id))
    with closing(_connect()) as conn:
        return float(conn.execute(sql, args).fetchone()[0])


# ponytail: check-then-act. Up to MAX_CONCURRENT slot holders can each pass the check
# before any records spend, so a cap can overshoot by ~4 x worst_case (~$0.40), per spec 02
# §6.2; Console caps (R47) are the hard backstop. Upgrade: reserve worst_case atomically
# inside BEGIN IMMEDIATE, then settle to the real cost after the call.
def ensure_budget(session_id: str, worst_case: float) -> None:
    s = get_settings()
    if spend_today(session_id) + worst_case > s.llm_session_budget_usd:
        raise BudgetExceeded("session")
    if spend_today() + worst_case > s.llm_daily_budget_usd:
        raise BudgetExceeded("global")


def _take_rate_slot(deadline: float) -> None:
    while True:
        with _lock:
            now = time.monotonic()
            while _calls and now - _calls[0] >= _WINDOW_S:
                _calls.popleft()
            if len(_calls) < CALLS_PER_MIN:
                _calls.append(now)
                return
            wait = _calls[0] + _WINDOW_S - now
        if now + wait > deadline:
            raise Busy("LLM call rate limit reached")
        time.sleep(wait)


@contextmanager
def llm_slot(wait_s: float = 10.0) -> Iterator[None]:
    """At most MAX_CONCURRENT calls in flight and CALLS_PER_MIN starts per minute (process-wide)."""
    deadline = time.monotonic() + wait_s
    if not _sem.acquire(timeout=wait_s):
        raise Busy("too many concurrent LLM calls")
    try:
        _take_rate_slot(deadline)
        yield
    finally:
        _sem.release()
