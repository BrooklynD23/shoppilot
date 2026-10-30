# ShopPilot+ Foundations (W0–W1) Implementation Plan

> Amended by 00-contract-resolutions.md (2026-10-30): R1, R3, R4, R5, R8, R9, R10, R11, R12, R13, R14, R15, R21, R22, R23, R24, R26, R29, R30, R31, R32, R36, R38

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployable FastAPI skeleton with CI, a slim Docker image, per-session seeded SQLite stores, a strict tool registry and an append-only audit log, so W2 feature tasks can plug in without touching shared files.

**Architecture:** One uvicorn worker. Each anonymous browser gets an unguessable session id in an HttpOnly cookie; its store is one SQLite file under `DATA_DIR` named by `sha256(session_id)`. Every route opens a short-lived connection through `get_db(session_id)`. Tools register typed specs into an in-process dict; audit rows are append-only (SQLite triggers).

**Tech Stack:** Python 3.12, FastAPI 0.162.0, Pydantic 2.14.2, uvicorn 0.54.0, stdlib `sqlite3`, `jsonschema`, pytest 9.2.0, ruff 0.17.3, Docker `python:3.12-slim`, GitHub Actions.

**Spec:** `shoppilot/docs/specs/01-architecture.md` (read it first). Contract: `shoppilot/docs/specs/00-shared-brief.md`.

## Global Constraints

- Python `>=3.12,<3.13`. All direct deps pinned with `==` in `pyproject.toml` (versions in spec §7).
- Names in `00-shared-brief.md` are frozen: `ToolSpec`, `ToolResult`, `register`, `get_tools`, `log_action`, `get_db`, HTTP paths. Do not rename.
- No GPU, no network in tests. `APP_ENV=test` never needs API keys.
- Stripe key must be empty or start with `sk_test_` or `rk_test_` (R15); anything else aborts startup.
- Money is integer cents. Timestamps are ISO-8601 UTC strings ending in `Z`.
- Session id: `secrets.token_urlsafe(32)` (43 chars, regex `^[A-Za-z0-9_-]{43}$`). Cookie `sp_session`, HttpOnly, SameSite=Lax, Secure when `APP_ENV=prod`, Max-Age = `SESSION_TTL_HOURS*3600`.
- Defaults: `DATA_DIR=/tmp/shoppilot`, `SESSION_TTL_HOURS=24`, `MAX_SESSIONS=100`, `PLAN_TTL_MINUTES=15`.
- Seed: per `../specs/00-contract-resolutions.md` §4 (R4): `RNG_SEED=4680`, 20 products, ~400 customers, ~2,700 orders over the 180 days before `anchor`, 4 inbox emails.
- Error body for every 4xx/5xx: `{"error": {"code": str, "message": str, "retry_after_s"?: int}}` (`retry_after_s` only on 429/503; codes in resolutions §7.6). Never include stack traces or secrets.
- One uvicorn worker (`--workers 1`). Rate limiter and registry are in-process.
- Every file stays under 400 lines; functions under 50 lines.

## Review Focus

1. **Tampered or garbage cookie** (`../../etc/passwd`, 2 KB string, empty) → treated as no session: 401 `no_session`, never touches the filesystem. Test in Task 6.
2. **Server restarted, cookie still valid, file gone** (free hosts wipe disk) → store reseeds silently and `/api/store` returns `"store_reset": true` so the UI can show a banner. Test in Task 6.
3. **Two browsers in parallel** → a write in session A never shows in session B. Test in Task 6.
4. **Double-click undo** → second undo of the same audit id returns 409 `already_undone`, not a second state change. Test in Task 5.
5. **Disk flood via repeated `POST /api/session`** → rate limit 429 after 10/min/IP and file count never exceeds `MAX_SESSIONS`. Test in Tasks 2 and 6.

## File map

| File | Task | Responsibility |
|---|---|---|
| `pyproject.toml`, `.gitignore`, `.env.example`, `README.md` (stub), `app/**/__init__.py` | 1 | packaging, lint, test config |
| `app/main.py`, `app/static/index.html` (placeholder) | 1 (hello) → 6 (routes) | HTTP surface |
| `.github/workflows/ci.yml` | 1 | lint + test |
| `Dockerfile`, `.dockerignore` | 1 | image |
| `tests/conftest.py` | 1 | shared fixtures, network block |
| `app/config.py` | 2 | settings from env |
| `app/db.py` | 2 | schema, paths, `get_db`, `create_store`, `sweep_sessions` |
| `app/seed/generate.py` | 3 | deterministic store data |
| `app/tools/registry.py` | 4 | `ToolSpec`, `ToolResult`, `Ctx`, registry |
| `app/agent/audit.py` | 5 | `log_action`, `list_actions`, `undo_action` |

---

### Task 1D: Deploy hello to host (manual, runs after Task 1)

> **Dropped (R14):** replaced by P7-D1 (`render.yaml` Blueprint). Cold-start timing moves to P6-UI7 Step 1. Steps kept for reference only.

Wave: W0 · Depends-on: Task 1 · Owns-files: none (writes README "Known limits" lines only after Task 1 is merged) · Est: 1 h

- [ ] **Step 1:** Create a Render Web Service from the GitHub repo, runtime Docker, plan Free, env `APP_ENV=prod`. (Fallback hosts in spec §8.)
- [ ] **Step 2:** Verify `curl -fsS https://<app>.onrender.com/healthz` → `{"ok":true,...}`.
- [ ] **Step 3:** Verify cold start: wait 20 min, re-curl, note seconds in README "Known limits".

### Task 1: Repo bootstrap, hello app, CI, Docker, test harness

Wave: W0 · Depends-on: none · Owns-files: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `.dockerignore`, `Dockerfile`, `.github/workflows/ci.yml`, `app/__init__.py`, `app/{seed,llm,llm/prompts,agent,tools,ml,safety,integrations}/__init__.py`, `app/main.py`, `app/static/index.html`, `tests/__init__.py`, `tests/{agent,tools,llm,seed,ml,safety,integrations,static,eval,e2e}/__init__.py` (R30), `tests/conftest.py`, `tests/test_main.py` · Est: 3.5 h

**Interfaces:**
- Produces: `app.main:app` (FastAPI); `GET /healthz` → `{"ok": true, "version": os.environ.get("RENDER_GIT_COMMIT", "dev")[:7]}` (R11); fixtures `tmp_data_dir`, `anchor`, `no_network` (autouse); marker `live` (skipped unless `RUN_LIVE=1`).

- [ ] **Step 1: Write `pyproject.toml`** — `[project]` name `shoppilot`, `requires-python = ">=3.12,<3.13"`, deps and `[project.optional-dependencies] dev` per R29 (spec §7 minus statsforecast and scikit-learn; plus stripe 16.1.0, reportlab 5.1.0; dev adds playwright). `[tool.ruff] line-length = 100, target-version = "py312"`, `lint.select = ["E","F","I","B","UP","S","SIM"]`, per-file-ignores `"tests/**" = ["S101"]`. `[tool.pytest.ini_options] testpaths = ["tests"]`, `markers = ["live: needs real API keys"]`, `addopts = "-q -m 'not live'"`.
- [ ] **Step 2: Write the failing test** `tests/test_main.py`

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ShopPilot" in r.text

def test_network_blocked():
    import socket, pytest
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.create_connection(("example.com", 80))
```

- [ ] **Step 3: Write `tests/conftest.py`** with **all** shared fixtures now; fixtures that need W1 modules import them lazily inside the fixture body, so they only fail if a test uses them before the module exists:
  - autouse `no_network`: monkeypatch `socket.socket.connect` to raise `RuntimeError("network disabled in tests")` unless the test has `@pytest.mark.live`. `pytest_collection_modifyitems` skips `live` unless `RUN_LIVE=1`. (TestClient is in-process, unaffected.)
  - autouse `tmp_data_dir`: env `DATA_DIR=tmp_path`, `APP_ENV=test`; calls `get_settings.cache_clear()` and `app.main._reset_rate_limits()` when those exist.
  - `anchor` → `date(2026, 10, 15)`; `fixed_now` → `datetime(2026, 10, 15, 9, 0, tzinfo=UTC)`.
  - `mem_conn` → `sqlite3.connect(":memory:")` + `init_schema`.
  - `seeded` → `mem_conn` + `seed_store(conn, anchor)`.
  - `tmp_store` → `sid = token_urlsafe(32)`; `create_store(sid, anchor)`; yields `sid`.
  - `ctx` → `with get_db(tmp_store) as db: yield Ctx(tmp_store, db, fixed_now, anchor)` (R3: `today` = anchor).
  - `client` → `TestClient(app, headers={"X-ShopPilot": "1"})` (R10, so tests survive INT-1); `session_client` → client after `POST /api/session {}`; `two_session_clients` → two independent `session_client`s.
- [ ] **Step 4: Run** `pytest tests/test_main.py -v` → FAIL (`app.main` missing).
- [ ] **Step 5: Implement `app/main.py`** with `app = FastAPI(title="ShopPilot+")`, `GET /healthz`, `StaticFiles(directory=app/static, html=True)` mounted at `/` **last**. `app/static/index.html` = `<!doctype html><title>ShopPilot+</title><h1>ShopPilot+</h1>` (UI task replaces it in W2).
- [ ] **Step 6: Run** `pytest -v && ruff check . && ruff format --check .` → all pass.
- [ ] **Step 7: Write `Dockerfile`** per spec §6 with `CMD` port `${PORT:-8000}` (R12) and `.dockerignore` (`.git`, `tests`, `docs`, `.env*`, `__pycache__`, `.venv`).
- [ ] **Step 8: Verify image** — `docker build -t shoppilot . && docker run --rm -d -p 8000:8000 --memory=512m --name sp shoppilot && curl -fsS localhost:8000/healthz && docker stats --no-stream sp && docker image ls shoppilot`. Expected: healthz OK, idle RSS < 250 MB, image < 700 MB. Record both numbers in README "Known limits".
- [ ] **Step 9: Write `.github/workflows/ci.yml`** per spec §6 with `name: CI` (R13) (jobs `test`, `docker`).
- [ ] **Step 10: Write `.env.example`** with every key from Task 2's `Settings`, values empty or defaults, comment `# test-mode keys only (sk_test_...)`.
- [ ] **Step 11: Commit** `git add -A && git commit -m "chore: bootstrap repo, CI, Docker, hello app"`; push; confirm CI green.

### Task 2: Settings and database core

Wave: W1 · Depends-on: Task 1 · Owns-files: `app/config.py`, `app/db.py`, `tests/test_config.py`, `tests/test_db.py` · Est: 3 h

**Interfaces:**
- Produces:
  - `class Settings(BaseModel)` frozen; fields: `app_env: Literal["dev","test","prod"]="dev"`, `data_dir: Path=Path("/tmp/shoppilot")`, `session_ttl_hours: int=24`, `max_sessions: int=100`, `plan_ttl_minutes: int=15`, `anthropic_api_key: SecretStr|None=None`, `planner_model: str="claude-sonnet-5-5"`, `judge_model: str="claude-haiku-5-5"`, `llm_max_plans_per_session_hour: int=20`, `stripe_secret_key: SecretStr|None=None`, plus the R31 fields (`planner_effort`, `llm_mode`, `llm_daily_budget_usd`, `llm_session_budget_usd`, `stripe_mode`, `stripe_max_writes_per_session`); no Groq/NVIDIA keys. Full list: resolutions §6.2.
  - `def session_hash(session_id: str) -> str` → `sha256(sid).hexdigest()[:16]` (R21).
  - `def load_settings(env: Mapping[str, str] = os.environ) -> Settings` (reads UPPER_CASE names); `def get_settings() -> Settings` (`@functools.cache`).
  - `SESSION_ID_RE: re.Pattern`; `class InvalidSession(ValueError)`.
  - `def store_path(session_id: str, s: Settings) -> Path` → `data_dir / f"{sha256(sid).hexdigest()[:32]}.db"`; raises `InvalidSession` if regex fails.
  - `def init_schema(conn: sqlite3.Connection) -> None` (idempotent DDL from spec §3 **as amended by resolutions §5**, incl. `step_runs` and audit `prev_hash`/`row_hash`).
  - `@contextmanager def get_db(session_id: str) -> Iterator[sqlite3.Connection]` — opens existing file only (`FileNotFoundError` if missing), `row_factory=sqlite3.Row`, `check_same_thread=False`, `timeout=5`, `PRAGMA foreign_keys=ON`; commit on success, rollback on exception, always close.
  - `def store_exists(session_id: str) -> bool`; `def touch_store(session_id: str) -> None` (mtime = now).
  - `def create_store(session_id: str, anchor: date) -> None` — deletes existing file, writes to `<path>.tmp`, `init_schema`, `seed_store` (lazy import from `app.seed.generate`), `os.replace` to final path (atomic).
  - `def sweep_sessions(now: float | None = None) -> int` — deletes `*.db` with mtime older than TTL, then oldest-first until count ≤ `max_sessions - 1`; returns number deleted.

- [ ] **Step 1: Failing tests** `tests/test_config.py`

```python
def test_defaults():
    s = load_settings({})
    assert s.app_env == "dev" and s.max_sessions == 100 and s.session_ttl_hours == 24

def test_live_stripe_key_rejected():
    with pytest.raises(ValueError, match="sk_test_"):
        load_settings({"STRIPE_SECRET_KEY": "sk_live_abc"})

def test_prod_requires_anthropic_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        load_settings({"APP_ENV": "prod"})

def test_secret_not_in_repr():
    s = load_settings({"ANTHROPIC_API_KEY": "sk-ant-xyz"})
    assert "sk-ant-xyz" not in repr(s)
```

- [ ] **Step 2: Failing tests** `tests/test_db.py`

```python
def test_schema_tables(mem_conn):  # sqlite3.connect(":memory:") + init_schema
    names = {r[0] for r in mem_conn.execute("select name from sqlite_master where type='table'")}
    assert {"meta","products","customers","orders","order_items","inbox","guard_verdicts",
            "outbox","purchase_orders","refunds","payment_links","plans","step_runs","audit_log"} <= names

def test_negative_stock_rejected(mem_conn):  # CHECK(stock >= 0)
    with pytest.raises(sqlite3.IntegrityError): insert_product(mem_conn, stock=-1)

def test_bad_order_status_rejected(mem_conn): ...  # status='lost' -> IntegrityError

def test_audit_append_only(mem_conn):
    mem_conn.execute("insert into audit_log(id,ts,kind,payload_json) values('a1','t','plan','{}')")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem_conn.execute("update audit_log set kind='x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem_conn.execute("delete from audit_log")

def test_double_undo_blocked(mem_conn):  # unique partial index on ref_id where kind='undo'
    ...  # second insert of kind='undo', ref_id='a1' -> IntegrityError

@pytest.mark.parametrize("sid", ["", "../../etc/passwd", "a"*2000, "x"*42, "x"*43 + "/"])
def test_store_path_rejects_bad_ids(sid, tmp_data_dir):
    with pytest.raises(InvalidSession): store_path(sid, get_settings())

def test_store_path_inside_data_dir(tmp_data_dir):
    p = store_path(secrets.token_urlsafe(32), get_settings())
    assert p.parent == tmp_data_dir and p.suffix == ".db" and len(p.stem) == 32

def test_get_db_missing_raises(tmp_data_dir):
    with pytest.raises(FileNotFoundError): get_db(secrets.token_urlsafe(32)).__enter__()

def test_get_db_rolls_back_on_error(tmp_store): ...  # insert then raise -> row absent

def test_sweep_ttl_and_cap(tmp_data_dir, monkeypatch):
    # 3 fresh files + 2 files with mtime 25h old, MAX_SESSIONS=3
    assert sweep_sessions() == 3   # 2 expired + 1 oldest to leave room for a new one
    assert len(list(tmp_data_dir.glob("*.db"))) == 2
```

- [ ] **Step 3: Run** `pytest tests/test_config.py tests/test_db.py -v` → FAIL (imports).
- [ ] **Step 4: Implement `app/config.py`** — `field_validator` on `stripe_secret_key` (empty, `sk_test_` or `rk_test_` prefix, message contains `sk_test_`); `model_validator(mode="after")` requires `anthropic_api_key` when `app_env=="prod"`. Settings built with plain `Settings(**{k.lower(): v for k, v in env.items() if k.lower() in Settings.model_fields})`. No pydantic-settings (one less dep).
- [ ] **Step 5: Implement `app/db.py`** — DDL as one `SCHEMA` string run with `executescript`; triggers and indexes exactly as spec §3. Tests here use `mem_conn`/`tmp_data_dir` only; `test_get_db_rolls_back_on_error` builds its file with `init_schema` directly so it does not wait for Task 3's seed.
- [ ] **Step 6: Run** tests → PASS; `ruff check .` clean.
- [ ] **Step 7: Commit** `feat: settings and per-session sqlite store`.

### Task 3: Deterministic seed data

Wave: W1 · Depends-on: Task 2 · Owns-files: `app/seed/generate.py`, `tests/seed/test_generate.py` · Est: 4 h

> **R4 overrides the algorithm and constants below:** implement resolutions §4 (P3 demand recipe, `RNG_SEED=4680`, 20 products, ~2,700 orders over 180 d, planted A1–A4 + D1, E002 text from spec 04 §4.6, damaged order ≤ 20,000 cents at `anchor−4`, all `note` NULL). Constants: `RNG_SEED`, `STORE_NAME`, `HERO_PRODUCT_ID`, `AT_RISK_PRODUCT_IDS`, `PLANTED_ANOMALY_ORDER_IDS` (8), `DECOY_ORDER_IDS`, `DAMAGED_ORDER_ID`, `DAMAGED_EMAIL_ID`, `INJECTION_EMAIL_ID`, `WISMO_EMAIL_ID`. Tests below keep their intent: counts become products == 20, customers >= 300, orders in 2,400–3,000 (and identical across runs); dates in `[anchor-180, anchor)`; `test_fast_stockouts` uses `AT_RISK_PRODUCT_IDS`; add `test_damaged_order_within_caps` (total ≤ 20,000, created ≥ anchor−30) and `test_no_order_notes`.

**Interfaces:**
- Consumes: `init_schema(conn)`, `create_store(session_id, anchor)` from Task 2.
- Produces:
  - `def seed_store(conn: sqlite3.Connection, anchor: date, rng_seed: int = RNG_SEED) -> None`  (`RNG_SEED = 4680`, R4)
  - Constants (test-only truth, never written to the DB): `PLANTED_ANOMALY_ORDER_IDS: tuple[str, ...]` (4 ids), `DAMAGED_EMAIL_ID = "E001"`, `INJECTION_EMAIL_ID = "E002"`, `DAMAGED_ORDER_ID: str`, `FAST_STOCKOUT_SKUS: tuple[str, ...]` (3 SKUs).

Algorithm (not determined by the tests, so fixed here):
1. `rng = random.Random(rng_seed)`; never touch the global `random` or wall clock.
2. Day weight for day `d` in `[anchor-90, anchor-1]`: `w = (1.4 if weekend else 1.0) * (1 + 0.25 * max(0, (d - (anchor-30)).days) / 30)`. Sample exactly 200 order days with `rng.choices(days, weights=w, k=200)`, then sort; time of day `rng.randint(8*3600, 22*3600)` seconds.
3. Force ≥ 5 of the 200 onto `anchor-1` (move the latest non-yesterday orders) so "ship yesterday's orders" has work.
4. Items: 1–3 lines per order; product drawn with Zipf-like weights `1/(rank**0.9)`; qty 1–2. Products ranked 25–30 are intermittent (weight × 0.15).
5. Status by age: `anchor-1` and `anchor-2` → `paid`; older → `shipped` with `tracking_number = f"1Z{rng.randrange(10**10):010d}"`; 6 older orders → `refunded`.
6. Stock: for each product `stock = round(velocity_30d * cover_days)` with `cover_days = rng.uniform(20, 60)`, except `FAST_STOCKOUT_SKUS` get `cover_days ∈ {3, 4, 6}`.
7. Planted anomalies, appended as orders 197–200 with explicit values: (a) qty 40 of one mug; (b) total ≥ 185000 cents, one line; (c) `ship_country` ≠ customer `country`, new customer, total ≥ 60000; (d) a new customer with 5 orders inside 10 minutes on `anchor-2` (counts as one planted id = the 5th order).
8. Inbox: `E001` damaged (customer of `DAMAGED_ORDER_ID`, a shipped order from `anchor-4`, body names the order id); `E002` injection from `support-desk@sh0ppilot-admin.example`, body exactly the text in spec §4; `E003` "where is my order" (benign); `E004` wholesale enquiry (benign).
9. `meta`: `schema_version=1`, `anchor`, `rng_seed`.

- [ ] **Step 1: Failing tests** `tests/seed/test_generate.py`

```python
def test_counts(seeded):  # seeded = in-memory conn + init_schema + seed_store(anchor=2026-10-15)
    assert count(seeded, "products") == 30
    assert count(seeded, "customers") >= 60
    assert count(seeded, "orders") == 200
    assert count(seeded, "inbox") == 4

def test_deterministic(anchor):
    assert dump(seed(anchor)) == dump(seed(anchor))   # dump = iterdump() joined

def test_dates_in_window(seeded, anchor):
    lo, hi = min_max(seeded, "orders", "created_at")
    assert lo >= f"{anchor - timedelta(90)}" and hi < f"{anchor}"

def test_weekly_seasonality(seeded):
    assert mean_daily_orders(seeded, weekend=True) > 1.2 * mean_daily_orders(seeded, weekend=False)

def test_trend(seeded, anchor):
    assert orders_in(seeded, last_days=30) > orders_in(seeded, first_days=30)

def test_yesterday_has_unshipped(seeded, anchor):
    assert paid_orders_on(seeded, anchor - timedelta(1)) >= 5

def test_fast_stockouts(seeded):
    for sku in FAST_STOCKOUT_SKUS:
        assert stock(seeded, sku) / velocity_30d(seeded, sku) < 7

def test_planted_anomalies_are_extreme(seeded):
    median = median_total(seeded)
    assert any(total(seeded, o) > 20 * median for o in PLANTED_ANOMALY_ORDER_IDS)
    ...  # one qty>=40 line; one ship_country != customer.country

def test_damaged_email_points_to_shipped_order(seeded):
    body = inbox_body(seeded, DAMAGED_EMAIL_ID)
    assert DAMAGED_ORDER_ID in body and order_status(seeded, DAMAGED_ORDER_ID) == "shipped"

def test_injection_email_present(seeded):
    assert "ignore" in inbox_body(seeded, INJECTION_EMAIL_ID).lower()

def test_create_store_atomic(tmp_data_dir, anchor):
    sid = secrets.token_urlsafe(32); create_store(sid, anchor)
    assert store_exists(sid) and not list(tmp_data_dir.glob("*.tmp"))

def test_seed_fast(anchor):
    t = time.perf_counter(); seed(anchor); assert time.perf_counter() - t < 0.5
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** per algorithm. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: deterministic seeded store with planted anomalies and inbox`.

### Task 4: Tool registry

Wave: W1 · Depends-on: Task 1 · Owns-files: `app/tools/registry.py`, `tests/tools/test_registry.py` · Est: 1.5 h

**Interfaces:**
- Produces (frozen names from the brief, plus three helpers):
  - `ToolSpec`, `ToolResult` exactly as the brief.
  - `@dataclass(frozen=True) class Ctx: session_id: str; db: sqlite3.Connection; now: datetime; today: date` (`now` UTC tz-aware wall clock; `today` = store date `meta.anchor`, R3; tests pass fixed values).
  - `@dataclass(frozen=True) class Registered: spec: ToolSpec; run; preview; undo`
  - `def register(spec, run, preview, undo=None) -> None` — raises `ValueError` on: duplicate name; name not `^[a-z][a-z0-9_]{0,63}$`; invalid JSON Schema (`Draft202012Validator.check_schema`); top-level not `type: object` with `additionalProperties: false`; `moves_money and not destructive`; `undoable != (undo is not None)`.
  - `def get_tools() -> list[ToolSpec]` (registration order).
  - `def get_tool(name: str) -> Registered` (raises `KeyError`).
  - `def validate_args(name: str, args: dict) -> str | None` — `None` if valid, else first error message (`best_match`).
  - `def claude_tool_defs() -> list[dict]` → `[{"name","description","input_schema","strict": True}]`.
  - `def load_tools() -> None` — `pkgutil.iter_modules(app.tools.__path__)`, `importlib.import_module` each module except `registry`; idempotent (skips already-imported modules). Called from the app lifespan (Task 6).
  - `def _reset_for_tests() -> None`.
- `DiffItem` is referenced only under `TYPE_CHECKING` (no runtime import from `app.agent`).

- [ ] **Step 1: Failing tests** `tests/tools/test_registry.py` (autouse fixture calls `_reset_for_tests`)

```python
SCHEMA = {"type":"object","properties":{"order_id":{"type":"string"}},
          "required":["order_id"],"additionalProperties":False}

def test_register_and_list(): register(spec("mark_shipped"), run, preview, undo); assert [t.name for t in get_tools()] == ["mark_shipped"]
def test_duplicate_rejected(): ...  # ValueError "already registered"
def test_non_strict_schema_rejected(): ...  # additionalProperties missing -> ValueError
def test_money_must_be_destructive(): ...  # moves_money=True, destructive=False -> ValueError
def test_undoable_needs_undo_fn(): ...
def test_validate_args():
    assert validate_args("mark_shipped", {"order_id": "O0001"}) is None
    assert "order_id" in validate_args("mark_shipped", {})
    assert validate_args("mark_shipped", {"order_id": "O1", "x": 1}) is not None
def test_unknown_tool(): pytest.raises(KeyError, get_tool, "nope")
def test_claude_defs_strict(): assert claude_tool_defs()[0]["strict"] is True
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (module-level `_TOOLS: dict[str, Registered] = {}`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: strict tool registry`.

### Task 5: Audit log with undo

Wave: W1 · Depends-on: Tasks 2, 4 · Owns-files: `app/agent/audit.py`, `tests/agent/test_audit.py` · Est: 2 h

> **R22/R38 additions:** every insert sets `prev_hash` (previous row's `row_hash`, genesis `"0"*64`) and `row_hash = sha256(prev_hash\nid\nts\nkind\ncanonical_json(payload))`; add `def verify_chain(ctx) -> bool` + `test_audit_chain_detects_edit`. `UndoError` codes add `changed_since` (tool undo returned `error="changed_since"` → 409). `list_actions` rows: `{id, ts, kind, plan_id, step_id, tool, summary, can_undo, undone, undone_at}` (`summary` from payload). No `undo_rejected` row.

**Interfaces:**
- Consumes: `Ctx`, `get_tool`, `ToolResult` (Task 4); `audit_log` table (Task 2).
- Produces:
  - `AUDIT_KINDS = frozenset({"session","plan","guard_block","validate","confirm","execute","undo","error"})`
  - `def log_action(ctx: Ctx, kind: str, payload: dict, *, plan_id: str | None = None, step_id: str | None = None, tool: str | None = None, undo_token: str | None = None, ref_id: str | None = None) -> str` — frozen positional signature kept; keywords added. Returns `"aud_" + secrets.token_hex(6)`. Raises `ValueError` on unknown kind; `TypeError` if payload not JSON-serialisable (`json.dumps(payload, default=None)`).
  - `def list_actions(ctx: Ctx, limit: int = 200) -> list[dict]` — newest first; each row has `undone: bool` (exists an `undo` row with `ref_id = id`) and `can_undo: bool`. Never returns `undo_token`.
  - `class UndoError(Exception): code: str` with codes `not_found`, `not_undoable`, `already_undone`, `undo_failed`.
  - `def undo_action(ctx: Ctx, audit_id: str) -> ToolResult` — loads row (`not_found`), requires `kind=="execute"` and `undo_token` (`not_undoable`), calls `get_tool(tool).undo(token, ctx)`; on `ok` logs `undo` with `ref_id=audit_id` (unique index → `IntegrityError` → `already_undone`); on not ok raises `undo_failed`.

- [ ] **Step 1: Failing tests** `tests/agent/test_audit.py` (uses `ctx` fixture over a seeded temp store and a fake `bump` tool registered with an undo that decrements a counter)

```python
def test_log_returns_id_and_persists(ctx):
    aid = log_action(ctx, "plan", {"request": "ship"}); assert aid.startswith("aud_")
    assert list_actions(ctx)[0]["id"] == aid

def test_unknown_kind(ctx): pytest.raises(ValueError, log_action, ctx, "hack", {})
def test_unserialisable_payload(ctx): pytest.raises(TypeError, log_action, ctx, "plan", {"x": object()})
def test_token_not_exposed(ctx): ...  # list_actions rows have no "undo_token" key

def test_undo_once(ctx):
    aid = log_action(ctx, "execute", {}, tool="bump", undo_token="t1")
    assert undo_action(ctx, aid).ok
    with pytest.raises(UndoError) as e: undo_action(ctx, aid)
    assert e.value.code == "already_undone"
    assert counter == 0   # undo fn ran exactly once

def test_undo_not_undoable(ctx): ...  # kind="plan" -> code "not_undoable"
def test_undo_missing(ctx): ...      # "aud_nope" -> code "not_found"
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Undo-row insert happens **before** calling the tool's undo inside the same transaction (so a concurrent second request hits the unique index first); if the tool's undo returns not ok, raise `UndoError("undo_failed")` and let `get_db` roll back. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: append-only audit log with single-shot undo`.

### Task 6: HTTP skeleton — sessions, store, audit, undo, guards

Wave: W1 · Depends-on: Tasks 2, 3, 5 · Owns-files: `app/main.py`, `tests/test_main.py`, `tests/test_sessions.py` · Est: 3 h

**Interfaces:**
- Consumes: everything above.
- Produces (W2 builds on these names):
  - `def current_session(request: Request) -> str` (FastAPI dependency): reads `sp_session`; bad/missing → `HTTPException(401, "no_session")`; valid but file missing → `create_store(sid, today_utc)` and `request.state.store_reset = True`; else `touch_store(sid)`.
  - `def session_ctx(sid: str = Depends(current_session)) -> Iterator[Ctx]` — `with get_db(sid) as db: yield Ctx(sid, db, datetime.now(UTC), today=<meta.anchor as date>)` (R3).
  - `def rate_limit(bucket: str, per_minute: int)` → dependency factory; key = (`bucket`, client IP from `request.client.host`); in-memory `dict[key, deque[float]]` with a `threading.Lock`; over limit → 429 `rate_limited`. Limits (R36): `session` 10/min/IP; `plan` 10/min **per session** + 60/min per IP + per-session hourly cap `llm_max_plans_per_session_hour`; everything else 120/min/IP.
  - Middleware adding headers: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.
  - Exception handlers → error envelope: `HTTPException`, `RequestValidationError` (422 `bad_request`, no input echo), `UndoError` (404/409/422 by code), `ImportError`/`NotImplementedError` (501 `not_built`), generic `Exception` (500 `internal`, logs traceback server-side with session hash only).
  - Routes:
    - `POST /api/session` body `{"reset": bool = false}` → `{"created": bool, "store_name", "anchor", "llm_mode", "stripe_mode"}` (R26; never the session id); runs `sweep_sessions()` before creating; sets cookie per Global Constraints; logs `session` audit row.
    - `GET /api/store` → `{"store_name", "anchor", "store_reset", "llm_mode", "stripe_mode", "products": [...], "orders": [newest 100, each with `items`], "orders_total": int, "customers": [...]}` (R26).
    - `GET /api/audit` → `{"chain_ok": verify_chain(ctx), "actions": list_actions(ctx)}` (R26).
    - `POST /api/undo/{audit_id}` → `ToolResult`; path param validated `^aud_[0-9a-f]{12}$`.
    - `GET /api/inbox`, `POST /api/plan`, `POST /api/execute`, `GET /api/outbox`, `GET /api/export/{kind}`: wired with **lazy imports inside the handler** of the frozen functions (`make_plan`, `validate_plan`, `dry_run`, `execute`, `screen`, outbox/export helpers). Until W2 lands they return 501 `not_built`. Bodies and response shapes per resolutions §7: `/api/plan` = `make_plan → validate_plan → dry_run → save_plan` (R32); `/api/execute` = `claim_plan → execute`, results without `undo_token` (R1); `/api/inbox` = `screen_inbox(ctx)` (R24). Request models: `PlanRequest{request: constr(min_length=1, max_length=2000), replay: bool = False}` (R8), `ExecuteRequest{plan_id: constr(pattern=r"^plan_[0-9a-f]{12}$"), approved_step_ids: list[constr(max_length=32)] (max 20)}`.

- [ ] **Step 1: Failing tests** `tests/test_sessions.py`

```python
def test_session_cookie_flags(client):
    r = client.post("/api/session", json={})
    c = r.headers["set-cookie"]
    assert "sp_session=" in c and "httponly" in c.lower() and "samesite=lax" in c.lower()
    assert "max-age=86400" in c.lower()
    assert r.json()["created"] is True

def test_no_cookie_401(client):
    r = client.get("/api/store"); assert r.status_code == 401
    assert r.json() == {"error": {"code": "no_session", "message": ANY}}

@pytest.mark.parametrize("bad", ["../../etc/passwd", "a"*2000, ""])
def test_tampered_cookie_401(client, bad, tmp_data_dir):
    client.cookies.set("sp_session", bad)
    assert client.get("/api/store").status_code == 401
    assert list(tmp_data_dir.iterdir()) == []

def test_store_snapshot(session_client):
    j = session_client.get("/api/store").json()
    assert len(j["products"]) == 20 and len(j["orders"]) == 100 and j["orders_total"] > 2000 and j["store_reset"] is False

def test_isolation(two_session_clients):
    a, b = two_session_clients
    sid_a = a.cookies["sp_session"]
    with get_db(sid_a) as db: db.execute("update products set stock=0")
    assert all(p["stock"] == 0 for p in a.get("/api/store").json()["products"])
    assert any(p["stock"] > 0 for p in b.get("/api/store").json()["products"])

def test_missing_file_reseeds(session_client):
    store_path(session_client.cookies["sp_session"], get_settings()).unlink()
    assert session_client.get("/api/store").json()["store_reset"] is True

def test_reset_reseeds(session_client): ...   # mutate, POST reset=true, stock restored
def test_session_rate_limit(client): ...      # 11th POST /api/session in a minute -> 429 rate_limited
def test_session_cap(client, monkeypatch): ...# MAX_SESSIONS=3, create 5 -> <=3 *.db files
```

`tests/test_main.py` additions:

```python
def test_security_headers(client):
    h = client.get("/healthz").headers
    assert "default-src 'self'" in h["content-security-policy"] and h["x-content-type-options"] == "nosniff"

def test_unbuilt_route_501(session_client):
    r = session_client.post("/api/plan", json={"request": "ship"})
    assert r.status_code in (200, 501)   # 501 until W2 agent core lands; W3 tightens to 200

def test_plan_body_validated(session_client):
    assert session_client.post("/api/plan", json={"request": ""}).status_code == 422
    assert session_client.post("/api/plan", json={"request": "x"*2001}).status_code == 422

def test_execute_plan_id_validated(session_client):
    r = session_client.post("/api/execute", json={"plan_id": "../x", "approved_step_ids": []})
    assert r.status_code == 422

def test_undo_unknown_404(session_client): ...   # /api/undo/aud_000000000000 -> 404 not_found
def test_undo_bad_id_422(session_client): ...    # /api/undo/../../x -> 404 or 422, never 500
def test_audit_lists_session_row(session_client): ...  # first row kind == "session"
def test_500_hides_details(session_client, monkeypatch): ...  # forced error -> {"error":{"code":"internal"}} and no traceback text
```

- [ ] **Step 2: Run** `pytest tests/test_sessions.py tests/test_main.py -v` → FAIL.
- [ ] **Step 3: Implement** in `app/main.py`. Lifespan: `get_settings()`, `mkdir(data_dir, exist_ok=True, mode=0o700)`, `sweep_sessions()`, `load_tools()`. Also `_reset_rate_limits() -> None` (clears the limiter dict; used by conftest). Uvicorn runs with `--proxy-headers` so `request.client.host` is the real IP behind Render's proxy.
- [ ] **Step 4: Run** full suite `pytest && ruff check . && ruff format --check .` → PASS.
- [ ] **Step 5: Verify in Docker** — rebuild, `curl -c jar -X POST localhost:8000/api/session -H 'content-type: application/json' -d '{}'` then `curl -b jar localhost:8000/api/store | head -c 300` → JSON with products.
- [ ] **Step 6: Commit** `feat: session-scoped HTTP skeleton with audit and undo`; push; CI green; redeploy (Task 1D host) and repeat Step 5 against the public URL.

---

## Hand-off to W2 (what other plans may rely on)

| Need | Use |
|---|---|
| DB access inside a tool | `ctx.db` (already in a transaction; do not commit/close) |
| Register a tool | Create `app/tools/<tool_name>.py` that calls `register(...)` at import time. `load_tools()` imports every module in `app/tools/` at startup; no shared list to edit |
| Log | `log_action(ctx, kind, payload, plan_id=..., step_id=..., tool=..., undo_token=...)` — executor only; tools never log or commit (R23) |
| Stored plans | `plans` + `step_runs` tables; per-step execute with lock-then-check `UPDATE ... WHERE status IN ('proposed','executing')` (R1) |
| New env var | add to `Settings` via integrator; do not read `os.environ` directly |
| Fixtures | `ctx`, `seeded`, `session_client`, `anchor`, `tmp_data_dir` from `tests/conftest.py` |

## Self-review notes

- Coverage gate (`--cov-fail-under=80`) is **not** set in W1 CI: W2 stubs would fail it. W3 integration task turns it on.
- `tests/conftest.py` is Task 1's file only. Task-specific helpers (`count`, `dump`, `insert_product`, fake `bump` tool) live in each task's own test file.
- Total estimate (amended): W0 3.5 h (Task 1; 1D dropped), W1 15 h (Tasks 2–6). Critical path: 1 → 2 → 3 → 5 → 6 (Task 4 runs parallel with 2–3).
