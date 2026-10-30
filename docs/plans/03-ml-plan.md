# 03 — ML actions implementation plan

> Amended by 00-contract-resolutions.md (2026-10-30): R3, R4, R5, R6, R18, R22, R23, R27, R30, R37

> For the implementer: work task by task with TDD. Spec: `../specs/03-ml-actions.md`. Contract: `../specs/00-shared-brief.md` (frozen).

**Goal.** Ship `forecast_demand`, `create_restock_po` and `flag_anomalies` as agent tools. They are backed by stdlib Croston-SBA / SES×DOW forecasting and modified-z + rule anomaly scoring.

**Architecture.** Each ML module has a pure core function, which every unit test targets, plus one thin DB wrapper with the frozen name. The tools call the wrappers and never touch the math. No new dependencies.

**Tech.** Python 3.12 stdlib (`math`, `statistics`, `datetime`, `sqlite3`) and pytest.

## Global Constraints

1. **No new dependencies.** `pyproject.toml` gets no entry from this layer. If someone wants numpy, `app/ml` still must not import it (spec §4).
2. **Frozen names.**
   - `forecast_demand(product_id, ctx, horizon_days=14) -> dict`
   - `flag_anomalies(ctx, since_days=7) -> list[dict]`, where the kwarg is additive (spec §9.1)
   - tool names `forecast_demand`, `create_restock_po`, `flag_anomalies`
3. **Deterministic.** No randomness in `app/ml`. "Today" comes from `ctx.today` (store date = seed anchor, R3; always present, no wall-clock fallback).
4. **The LLM never computes a number.** Quantities, days and scores come from tool output. `explanation` and `reason` are Python templates.
5. **Every edge case returns a typed result or raises `ValueError`:**
   - zero history
   - all-zero demand
   - NaN, NULL or negative qty
   - `on_hand=0`
   - MAD=0
   - fewer than 30 orders
   - unknown product

   Tools convert exceptions into `ToolResult(ok=False, error=...)` and never let a traceback reach the UI.
6. **Size.** Each file stays under 250 lines and each function under 50.
7. **Placeholders.** Columns and table names follow P1's schema as amended (R5): `products.stock` (= on_hand), `products.cost_cents` (= unit cost), `products.active`; bill country = `customers.country`; `purchase_orders(id, product_id, qty, unit_cost_cents, status open|received|cancelled, forecast_json, created_at, expected_at)`. The only SQL lives in `_load_series()` (forecast.py), `_load_orders()` (anomaly.py) and the PO insert/cancel (create_restock_po.py).

## Review Focus

1. Check SBA bias factor `(1 − α/2)` and the ADI ≥ 1.32 branch.
2. Check the band math: cumulative σ√k, lo clipped at 0, and the stockout earliest/latest not swapped (earliest uses `+zσ√k`).
3. `create_restock_po` must reject `qty` when `qty_source="forecast"` and must require it when `qty_source="user"`.
4. Undo must be idempotent (cancelling twice is `ok=False`, not a crash) and must refuse POs that are already `received`.
5. Velocity must be computed per customer by sorting, not by an O(n²) scan.

## External dependencies (other planners)

| Need | From | Used by |
|---|---|---|
| `get_db(session_id)`, schema incl. `purchase_orders`, product columns (spec §7) | P1 `app/db.py` (W1) | ML-1, ML-2, ML-4 |
| Seed generator honouring spec §7 plus constants `HERO_PRODUCT_ID`, `AT_RISK_PRODUCT_IDS`, `PLANTED_ANOMALY_ORDER_IDS`, `DECOY_ORDER_IDS` | P1 `app/seed/` (W1) | ML-6 |
| `register`, `ToolSpec`, `ToolResult`, `DiffItem` | `app/tools/registry.py`, `app/agent/*` (W1) | ML-3, ML-4, ML-5 |
| `log_action(ctx, kind, payload)` | `app/agent/audit.py` (W1) | ML-4 |
| `Ctx` with `.db`, `.today` | P1-T4 `app/tools/registry.py` (R3) | all |

## Task table

| ID | Title | Wave | Depends-on | Owns-files | Est. h |
|---|---|---|---|---|---|
| ML-1 | Forecast core + DB wrapper | W2 | P1 db+seed (W1) | `app/ml/forecast.py`, `tests/ml/conftest.py`, `tests/ml/test_forecast.py` (package `__init__`s come from P1-T1, R30) | 3.5 |
| ML-2 | Anomaly core + DB wrapper | W2 | P1 db+seed (W1) | `app/ml/anomaly.py`, `tests/ml/test_anomaly.py` | 2.5 |
| ML-3 | `forecast_demand` tool | W2 | ML-1, registry (W1) | `app/tools/forecast_demand.py`, `tests/tools/test_forecast_demand.py` | 1 |
| ML-4 | `create_restock_po` tool (+preview, undo) | W2 | ML-1, registry (W1), P4-T2 `RESTOCK_QTY_MAX` | `app/tools/create_restock_po.py`, `tests/tools/test_create_restock_po.py` | 2 |
| ML-5 | `flag_anomalies` tool | W2 | ML-2, registry (W1) | `app/tools/flag_anomalies.py`, `tests/tools/test_flag_anomalies.py` | 1 |
| ML-6 | Evaluation gates on the real seed | W3 | ML-1, ML-2, P1 seed constants | `app/ml/evaluate.py`, `tests/ml/test_evaluate.py` | 1.5 |

Total: **11.5 h**. ML-1 and ML-2 run in parallel. ML-3, ML-4 and ML-5 run in parallel once their core is done.

---

## ML-1 — Forecast core + DB wrapper

**Wave** W2 · **Depends-on** P1 db+seed · **Est.** 3.5 h

**Files.** Create `app/ml/forecast.py`, `tests/ml/conftest.py`, `tests/ml/test_forecast.py`.

**Interfaces**

```python
Z80 = NormalDist().inv_cdf(0.9)          # 1.2816
COVER_DAYS = 14
MIN_HISTORY_DAYS = 14
DEAD_AFTER_DAYS = 60
ALPHAS = (0.05, 0.1, 0.2, 0.3, 0.5)

def forecast_series(units: list[float], first_date: date, on_hand: int, on_order: int,
                    lead_time_days: int, horizon_days: int = 14) -> dict   # pure; spec §3.1 keys
def forecast_demand(product_id: str, ctx, horizon_days: int = 14) -> dict  # frozen; DB → forecast_series → add product meta
def _load_series(ctx, product_id: str) -> tuple[dict, list[float], date, list[str]]  # product row, units, first_date, warnings
```

`conftest.py` reuses P1's `ctx` fixture (real `Ctx`, seeded temp store, `today=date(2026,10,15)`, R30) and provides and `synth(base, trend=0, n=180, seed=4680)`. The latter makes a deterministic Poisson series with the spec's DOW multipliers using `random.Random`.

**TDD steps**

1. **RED.** Write `tests/ml/test_forecast.py`:
   - `test_regular_series_uses_ses_dow`: `forecast_series(synth(6), …)` gives `method == "ses_dow"` and `len(band["mean"]) == 14`.
   - `test_weekend_higher`: the Saturday mean is greater than the Monday mean.
   - `test_intermittent_uses_croston`: a series with 1 sale every ~6 days gives `"croston_sba"` and a flat mean.
   - `test_all_zero_is_no_demand`: `[0.0]*180` gives `method == "no_demand"`, `days_to_stockout is None`, `reorder_qty == 0`.
   - `test_short_history`: 5 days gives `"insufficient_history"` and `reorder_qty is None`.
   - `test_zero_on_hand`: gives `days_to_stockout == 0` and `stockout_range == [0, 0]`.
   - `test_nan_negative_dropped`: NaN and −3 in units are treated as 0, with `len(warnings) == 1`.
   - `test_band_ordering`: `lo ≤ mean ≤ hi` elementwise, `lo ≥ 0`, and `stockout_range[0] ≤ days_to_stockout ≤ stockout_range[1]`.
   - `test_no_stockout_in_horizon`: a huge `on_hand` gives `days_to_stockout is None` and `"not within"` in the explanation.
   - `test_reorder_subtracts_on_order`: the qty with `on_order=50` equals `max(0, qty0 − 50)`.
   - `test_gap_warning`: when `days_to_stockout < lead_time_days`, `"before the PO arrives"` is in the explanation.
   - `test_horizon_bounds`: 0 and 61 raise `ValueError`.
   - `test_unknown_product`: `forecast_demand("nope", ctx)` raises `ValueError`.
   - `test_hero_from_seed`: `forecast_demand(HERO_PRODUCT_ID, ctx)["days_to_stockout"] in range(3, 6)`.
2. Run `pytest tests/ml/test_forecast.py -q`. It is expected to FAIL with ImportError.
3. **GREEN.** Implement in this order:
   1. sanitise
   2. guards
   3. ADI classify
   4. `_ses_dow` and `_croston_sba` (each returning `mean[], residuals[]`)
   5. `_band`
   6. `_stockout`
   7. `_reorder`
   8. `_explain`
   9. `forecast_demand`, which calls `_load_series`, `forecast_series` and the product meta

   Add `# ponytail: assumes independent daily errors; residual bootstrap if coverage < 0.70` on `_band`.
4. Run `pytest tests/ml/test_forecast.py -q`. All tests should pass.
5. Run `python -c "import time,app.ml.forecast"`. There must be no third-party imports (`grep -E "^(import|from) (numpy|pandas|scipy|sklearn)" app/ml/*.py` returns nothing).

## ML-2 — Anomaly core + DB wrapper

**Wave** W2 · **Depends-on** P1 db+seed · **Est.** 2.5 h

**Files.** Create `app/ml/anomaly.py` and `tests/ml/test_anomaly.py`. Reuse `tests/ml/conftest.py` from ML-1 read-only. If ML-1 has not landed yet, copy the 6-line `ctx` fixture into the test file and delete it on merge.

**Interfaces**

```python
THRESHOLD = 3.5
MIN_ORDERS = 30
class InsufficientData(ValueError): ...

def modified_z(xs: list[float]) -> list[float]          # MAD; MeanAD fallback; all-equal → zeros
def score_orders(orders: list[dict], report_since: datetime) -> list[dict]   # pure; spec §3.2 items, score ≥ THRESHOLD, sorted desc
def flag_anomalies(ctx, since_days: int = 7) -> list[dict]                  # frozen name; DB → score_orders
def _load_orders(ctx) -> tuple[list[dict], list[str]]   # each: id, customer_id, created_at, total_cents, ship/bill country, lines[{qty, unit_price_cents, price_cents}]
```

**TDD steps**

1. **RED.** Write `tests/ml/test_anomaly.py`. A local `base_orders(n=300)` builds normal orders (`random.Random(4680)`).
   - `test_modified_z_known`: `modified_z([1,2,3,4,100])[-1] > 3.5` and the middle value is 0.
   - `test_mad_zero_fallback`: `[5]*20 + [50]` flags the last value. `[5]*21` gives all zeros, with no ZeroDivisionError.
   - `test_bulk_flagged`, `test_price_glitch_flagged`, `test_velocity_flags_all_burst` (5 orders, all 5 flagged, reason contains "1 of 5"), `test_new_mismatch_boost_only`: a mismatch on a normal order is NOT flagged, while a mismatch on a high first order is flagged with a higher score than the same order without the mismatch.
   - `test_coupon_not_flagged`: a 20% discount gives price score 0.
   - `test_reason_human`: every item has `order_id`, `score`, `reason`, the reason contains `$`, and there is no raw float noise (`score == round(score, 1)`).
   - `test_too_few_orders`: 10 orders raise `InsufficientData`.
   - `test_bad_rows_skipped`: a NULL `unit_price_cents` or `price_cents=0` line skips the price signal without crashing.
   - `test_window`: an outlier older than `report_since` is excluded from the output but still counts in the baseline.
   - `test_seed_planted_found`: `flag_anomalies(ctx)` ids ⊇ `PLANTED_ANOMALY_ORDER_IDS` and are disjoint from `DECOY_ORDER_IDS`. Report window is measured from `ctx.today` (R37).
2. Run `pytest tests/ml/test_anomaly.py -q`. It is expected to FAIL.
3. **GREEN.** Implement:
   1. `modified_z`
   2. the four signal functions
   3. velocity via `sorted(orders, key=(customer_id, created_at))` with a two-pointer 60-min window
   4. the boost
   5. the reason templates
   6. `score_orders`
   7. `flag_anomalies`
4. Run `pytest tests/ml -q`. All tests should pass.

## ML-3 — `forecast_demand` tool

**Wave** W2 · **Depends-on** ML-1, registry · **Est.** 1 h

**Files.** Create `app/tools/forecast_demand.py` and `tests/tools/test_forecast_demand.py`.

**Interfaces.**
- `SPEC = ToolSpec(name="forecast_demand", destructive=False, moves_money=False, undoable=False, input_schema=…)`, strict schema per resolutions §3: `product_id` string|null, `horizon_days` int, `only_at_risk` bool, all required, `additionalProperties: false`; ranges checked in `run`.
- `run(args, ctx) -> ToolResult`
- `preview(args, ctx) -> DiffItem`, which returns `before={}` and `after={"read_only": True, "summary": …}`
- At module bottom: `register(SPEC, run, preview)`

**TDD steps**

1. **RED.**
   - `test_single_product`: `ok`, and `data["forecast"]["days_to_stockout"]` is present.
   - `test_all_at_risk_sorted`: with no `product_id` and `horizon_days=7`, the ids ⊆ `AT_RISK_PRODUCT_IDS`, the hero is included, and the list is sorted by days.
   - `test_unknown_product_error`: `ok is False` and `"unknown product" in error`.
   - `test_schema_rejects_extra`: `jsonschema`-style check through the registry's validator if exposed. Otherwise assert `SPEC.input_schema["additionalProperties"] is False`.
   - `test_summary_names_products`: the summary contains the hero name and `"d)"`.
2. Run `pytest tests/tools/test_forecast_demand.py -q`. It is expected to FAIL.
3. **GREEN.** Implement. Wrap each per-product call in `try/except ValueError`, so one bad product does not sink the batch. Bad products go into `data["skipped"]`.
4. Run `pytest tests/tools/test_forecast_demand.py -q`. All tests should pass.

## ML-4 — `create_restock_po` tool

**Wave** W2 · **Depends-on** ML-1, registry, audit · **Est.** 2 h

**Files.** Create `app/tools/create_restock_po.py` and `tests/tools/test_create_restock_po.py`.

**Interfaces.**
- `SPEC` with `destructive=True, moves_money=False, undoable=True`.
- `preview(args, ctx) -> DiffItem`, using the spec §3.3 before/after and `amount_cents = qty*unit_cost_cents`.
- Schema (R6): `product_id` string, `qty_source` enum[forecast,user], `qty` integer|null — all required (strict); `qty` must be null for `forecast`, 1–`policy.RESTOCK_QTY_MAX` (500) for `user`.
- `run(args, ctx) -> ToolResult`: inserts the PO and returns `undo_token=json({po_id, status:"open"})`. **No `log_action`, no commit (R23)**: the executor logs the step.
- `undo(token, ctx) -> ToolResult`
- `_resolve_qty(args, ctx) -> tuple[int, dict]` returns qty and the forecast. It is shared by `preview` and `run`, so the two cannot disagree.

**TDD steps**

1. **RED.**
   - `test_forecast_qty_matches_forecast`: `run({"product_id": HERO, "qty_source": "forecast"})` gives a qty equal to `forecast_demand(HERO, ctx)["reorder_qty"]`.
   - `test_forecast_source_rejects_qty`: `{"qty_source":"forecast","qty":5}` gives `ok False`.
   - `test_user_source_requires_qty`: a null qty gives `ok False`. `qty=0` and `qty=501` give `ok False` (R18).
   - `test_preview_shape`: `before["forecast"]["band"]["mean"]` has 14 entries, `amount_cents == qty*unit_cost`, and `after["arrives_on"] == today + lead_time`.
   - `test_preview_writes_nothing`: the PO count is unchanged after `preview`.
   - `test_no_double_order`: create once, then run with `qty_source="forecast"` again. This gives `ok False` ("already covered by open PO") because `reorder_qty == 0`.
   - `test_insufficient_history_needs_user_qty`: the new product with `qty_source="forecast"` gives `ok False`, and the error text asks for a quantity.
   - `test_undo_cancels`: after undo the status is `cancelled`. A second undo gives `ok False` and does not raise.
   - `test_undo_received_refused`: manually set `status='received'`, then undo gives `ok False`.
   - `test_tool_does_not_log_or_commit`: `log_action` is never called and `ctx.db.in_transaction` stays true after `run` (R23).
2. Run `pytest tests/tools/test_create_restock_po.py -q`. It is expected to FAIL.
3. **GREEN.** Implement. Do not open `with ctx.db:` (it commits); the request transaction from `get_db` owns commit/rollback (R23). `undo` returns `ok=False, error="changed_since"` if the PO is no longer `open` (R22).
4. Run `pytest tests/tools/test_create_restock_po.py -q`. All tests should pass.

## ML-5 — `flag_anomalies` tool

**Wave** W2 · **Depends-on** ML-2, registry · **Est.** 1 h

**Files.** Create `app/tools/flag_anomalies.py` and `tests/tools/test_flag_anomalies.py`.

**Interfaces.** `SPEC` is read-only; `run`, `preview` and `register` are as in ML-3. `data = {"items": [...][:limit], "total_flagged": n, "threshold": 3.5}`.

**TDD steps**

1. **RED.**
   - `test_finds_planted`: the items include every `PLANTED_ANOMALY_ORDER_IDS` (with `limit=50`).
   - `test_limit_respected`: `limit=2` gives 2 items, and `total_flagged ≥ 2`.
   - `test_too_few_orders_ok_true`: a ctx with 5 orders gives `ok True`, the summary contains "too few orders", and items is empty.
   - `test_since_days_bounds`: 0 and 91 give `ok False`.
   - `test_summary_human`: the summary reads like "4 suspicious orders this week; top: o_… (price 2% of list)".
2. Run `pytest tests/tools/test_flag_anomalies.py -q`. It is expected to FAIL.
3. **GREEN.** Implement.
4. Run `pytest tests/tools/test_flag_anomalies.py -q`. All tests should pass.

## ML-6 — Evaluation gates on the real seed

**Wave** W3 · **Depends-on** ML-1, ML-2, P1 seed constants · **Est.** 1.5 h

**Files.** Create `app/ml/evaluate.py` and `tests/ml/test_evaluate.py`.

**Interfaces**

```python
def backtest(ctx, folds: int = 2, h: int = 14) -> dict
    # {"mae": {"model","snaive","mean28"}, "coverage": {"daily","cumulative"}, "n_products"}
    # only products with ≥ 60 days history; uses forecast_series on truncated series
def anomaly_eval(ctx) -> dict
    # {"recall","precision","decoy_max_score","flagged"}
if __name__ == "__main__":  # python -m app.ml.evaluate → prints the spec §6 table as markdown for README
```

**TDD steps**

1. **RED.** `test_evaluate.py` holds the spec §6 gates:
   - `mae.model ≤ mae.snaive`
   - `mae.model ≤ 1.05*mae.mean28`
   - `0.70 ≤ coverage.* ≤ 0.95`
   - `recall == 1.0`
   - `precision ≥ 0.8`
   - `decoy_max_score < 3.5`
   - `test_speed`: `forecast_demand` for all products plus `flag_anomalies` takes under 0.5 s (`time.perf_counter`)
   - `test_at_risk_matches_seed` (R4): `forecast_demand` tool with `product_id=null, horizon_days=7, only_at_risk=true` returns exactly `AT_RISK_PRODUCT_IDS`, hero `days_to_stockout` ∈ [3, 5]
2. Run `pytest tests/ml/test_evaluate.py -q`. It is expected to FAIL (ImportError).
3. **GREEN.** Implement.
4. Run `pytest tests/ml/test_evaluate.py -q`. All tests should pass.
   - If a gate fails, fix the seed calibration (ask P1) or the model. Do not loosen the gate silently.
   - Paste the output of `python -m app.ml.evaluate` into the PR description. The README owner copies the table.

---

## Appendix — re-measure the footprint (optional, not a task)

```bash
d=$(mktemp -d); cd "$d"
for v in sk sf pyod; do uv venv -q -p 3.12 v-$v; done
uv pip install -q -p v-sk/bin/python scikit-learn
uv pip install -q -p v-sf/bin/python statsforecast
uv pip install -q -p v-pyod/bin/python pyod
for v in sk sf pyod; do du -sh v-$v/lib/python3.12/site-packages; done
v-sf/bin/python -I -c "import resource,statsforecast.models;print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024,'MB')"
```

## Done when

1. `pytest tests/ml tests/tools/test_forecast_demand.py tests/tools/test_create_restock_po.py tests/tools/test_flag_anomalies.py -q` is all green.
2. `grep -rE "^(import|from) (numpy|pandas|scipy|sklearn|statsforecast|pyod)" app/ml app/tools` returns nothing.
3. In the demo request "restock what will run out this week", the plan card shows the hero product, "runs out in about 4 days (3–6)" and the band chart data.
