import os
import secrets
import sqlite3
import time

import pytest

from app.config import get_settings
from app.db import (
    InvalidSession,
    get_db,
    init_schema,
    store_exists,
    store_path,
    sweep_sessions,
    touch_store,
)


def _product(conn, **kw):
    row = dict(
        id="P01",
        sku="S1",
        name="n",
        category="c",
        price_cents=100,
        cost_cents=50,
        stock=1,
        lead_time_days=3,
        supplier_email="a@b.c",
    )
    row.update(kw)
    cols = ",".join(row)
    conn.execute(
        f"insert into products({cols}) values({','.join('?' * len(row))})", list(row.values())
    )


def _customer_order(conn, status="paid"):
    conn.execute("insert into customers values('C1','n','a@b.c','US','t')")
    conn.execute(
        "insert into orders(id,customer_id,created_at,status,total_cents,ship_country)"
        " values('O1','C1','t',?,100,'US')",
        (status,),
    )


def _audit(conn, id_="a1", kind="plan", ref=None):
    conn.execute(
        "insert into audit_log(id,ts,kind,payload_json,ref_id,prev_hash,row_hash)"
        " values(?,?,?,?,?,?,?)",
        (id_, "t", kind, "{}", ref, "0" * 64, "h"),
    )


def test_schema_tables(mem_conn):
    names = {r[0] for r in mem_conn.execute("select name from sqlite_master where type='table'")}
    assert {
        "meta",
        "products",
        "customers",
        "orders",
        "order_items",
        "inbox",
        "guard_verdicts",
        "outbox",
        "purchase_orders",
        "refunds",
        "payment_links",
        "plans",
        "step_runs",
        "audit_log",
    } <= names


def test_init_schema_idempotent(mem_conn):
    init_schema(mem_conn)


def test_negative_stock_rejected(mem_conn):
    with pytest.raises(sqlite3.IntegrityError):
        _product(mem_conn, stock=-1)


def test_product_active_default(mem_conn):
    _product(mem_conn)
    assert mem_conn.execute("select active from products").fetchone()[0] == 1


def test_bad_order_status_rejected(mem_conn):
    with pytest.raises(sqlite3.IntegrityError):
        _customer_order(mem_conn, status="lost")


def test_order_new_columns(mem_conn):
    _customer_order(mem_conn)
    cols = {r[1] for r in mem_conn.execute("pragma table_info(orders)")}
    assert {"refunded_cents", "carrier", "stripe_payment_intent_id"} <= cols


def test_plan_status_check(mem_conn):
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute("insert into plans values('p','r','{}','{}','{}','failed','t')")


def test_step_runs_pk(mem_conn):
    mem_conn.execute("insert into plans values('p','r','{}','{}','{}','proposed','t')")
    mem_conn.execute("insert into step_runs values('p','s1','a','{}','t')")
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute("insert into step_runs values('p','s1','a','{}','t')")


def test_audit_append_only(mem_conn):
    _audit(mem_conn)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem_conn.execute("update audit_log set kind='x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem_conn.execute("delete from audit_log")


def test_audit_hash_columns_required(mem_conn):
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute(
            "insert into audit_log(id,ts,kind,payload_json) values('a','t','plan','{}')"
        )


def test_double_undo_blocked(mem_conn):
    _audit(mem_conn)
    _audit(mem_conn, "u1", "undo", "a1")
    with pytest.raises(sqlite3.IntegrityError):
        _audit(mem_conn, "u2", "undo", "a1")


def test_foreign_keys_enforced_by_get_db(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    _make_file(sid)
    with pytest.raises(sqlite3.IntegrityError), get_db(sid) as db:
        db.execute("insert into order_items values('nope','nope',1,1)")


@pytest.mark.parametrize("sid", ["", "../../etc/passwd", "a" * 2000, "x" * 42, "x" * 43 + "/"])
def test_store_path_rejects_bad_ids(sid, tmp_data_dir):
    with pytest.raises(InvalidSession):
        store_path(sid, get_settings())


def test_store_path_inside_data_dir(tmp_data_dir):
    p = store_path(secrets.token_urlsafe(32), get_settings())
    assert p.parent == tmp_data_dir and p.suffix == ".db" and len(p.stem) == 32


def test_get_db_missing_raises(tmp_data_dir):
    with pytest.raises(FileNotFoundError):
        get_db(secrets.token_urlsafe(32)).__enter__()


def _make_file(sid):
    p = store_path(sid, get_settings())
    c = sqlite3.connect(p)
    init_schema(c)
    c.close()
    return p


def test_get_db_rolls_back_on_error(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    _make_file(sid)
    with pytest.raises(RuntimeError), get_db(sid) as db:
        _product(db)
        raise RuntimeError("boom")
    with get_db(sid) as db:
        assert db.execute("select count(*) from products").fetchone()[0] == 0


def test_get_db_commits_and_row_factory(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    _make_file(sid)
    with get_db(sid) as db:
        _product(db)
    with get_db(sid) as db:
        assert db.execute("select name from products").fetchone()["name"] == "n"


def test_store_exists_and_touch(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    assert not store_exists(sid)
    p = _make_file(sid)
    assert store_exists(sid)
    os.utime(p, (1, 1))
    touch_store(sid)
    assert p.stat().st_mtime > 1000


def test_sweep_ttl_and_cap(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS", "3")
    get_settings.cache_clear()
    now = time.time()
    for i in range(5):
        f = tmp_data_dir / f"{i:032d}.db"
        f.write_bytes(b"")
        age = 25 * 3600 if i < 2 else 0
        os.utime(f, (now - age - i, now - age - i))
    assert sweep_sessions(now) == 3
    assert len(list(tmp_data_dir.glob("*.db"))) == 2


def test_sweep_spares_non_store_files(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS", "1")
    get_settings.cache_clear()
    now = time.time()
    spend = tmp_data_dir / "spend.db"
    spend.write_bytes(b"")
    os.utime(spend, (1, 1))
    f = tmp_data_dir / ("a" * 32 + ".db")
    f.write_bytes(b"")
    sweep_sessions(now)
    assert spend.exists() and not f.exists()


def test_get_db_deleted_file_not_recreated(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    p = _make_file(sid)
    p.unlink()
    with pytest.raises(FileNotFoundError):
        get_db(sid).__enter__()
    assert not p.exists()


def test_create_store_unique_tmp_and_fk(tmp_data_dir, monkeypatch):
    import sys
    import types

    seen = []
    g = types.ModuleType("app.seed.generate")
    monkeypatch.setitem(sys.modules, "app.seed.generate", g)

    def fake(conn, anchor):
        seen.append(conn.execute("PRAGMA foreign_keys").fetchone()[0])

    g.seed_store = fake
    from datetime import date

    from app.db import create_store

    sid = secrets.token_urlsafe(32)
    create_store(sid, date(2026, 1, 1))
    create_store(sid, date(2026, 1, 1))
    assert seen == [1, 1] and store_exists(sid)
    assert not list(tmp_data_dir.glob("*.tmp"))


def test_get_db_unreadable_store_is_not_missing(tmp_data_dir):
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    sid = secrets.token_urlsafe(32)
    p = _make_file(sid)
    p.chmod(0)
    try:
        with pytest.raises(sqlite3.OperationalError):
            get_db(sid).__enter__()
    finally:
        p.chmod(0o600)


def test_get_db_corrupt_store_is_not_missing(tmp_data_dir):
    sid = secrets.token_urlsafe(32)
    store_path(sid, get_settings()).write_bytes(b"not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError) as e:
        get_db(sid).__enter__()
    assert not isinstance(e.value, FileNotFoundError)


def test_create_store_data_dir_is_0700(tmp_data_dir, monkeypatch, anchor):
    import stat
    import sys
    import types

    from app.db import create_store

    d = tmp_data_dir / "fresh"
    monkeypatch.setenv("DATA_DIR", str(d))
    get_settings.cache_clear()
    fake = types.SimpleNamespace(seed_store=lambda conn, anchor: None)  # Task 3 owns the real one
    monkeypatch.setitem(sys.modules, "app.seed.generate", fake)
    create_store(secrets.token_urlsafe(32), anchor)
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def _fake_seed(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(
        sys.modules,
        "app.seed.generate",
        types.SimpleNamespace(seed_store=lambda conn, anchor: None),
    )


def test_session_id_re_anchored():
    from app.db import SESSION_ID_RE

    assert SESSION_ID_RE.match("a" * 43)
    assert not SESSION_ID_RE.match("a" * 43 + "/../x")


def test_get_db_relative_data_dir(tmp_data_dir, monkeypatch, anchor):
    from app.db import create_store

    _fake_seed(monkeypatch)
    monkeypatch.chdir(tmp_data_dir)
    monkeypatch.setenv("DATA_DIR", "rel")
    get_settings.cache_clear()
    sid = secrets.token_urlsafe(32)
    create_store(sid, anchor)
    with get_db(sid) as conn:
        conn.execute("select 1")


def test_create_store_tightens_existing_dir(tmp_data_dir, monkeypatch, anchor):
    import stat

    from app.db import create_store

    _fake_seed(monkeypatch)
    d = tmp_data_dir / "old"
    d.mkdir(mode=0o755)
    d.chmod(0o755)
    monkeypatch.setenv("DATA_DIR", str(d))
    get_settings.cache_clear()
    create_store(secrets.token_urlsafe(32), anchor)
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_create_store_removes_stale_journal(tmp_data_dir, monkeypatch, anchor):
    from app.db import create_store

    _fake_seed(monkeypatch)
    sid = secrets.token_urlsafe(32)
    p = store_path(sid, get_settings())
    j = p.with_name(p.name + "-journal")
    j.write_bytes(b"stale")
    create_store(sid, anchor)
    assert not j.exists()


def test_sweep_removes_journal(tmp_data_dir):
    f = tmp_data_dir / ("b" * 32 + ".db")
    f.write_bytes(b"")
    j = tmp_data_dir / ("b" * 32 + ".db-journal")
    j.write_bytes(b"")
    os.utime(f, (1, 1))
    sweep_sessions()
    assert not f.exists() and not j.exists()
