# 03 — Layer 2: classical ML as agent actions (spec)

Planner P3, 2026-10-30. Reads `00-shared-brief.md` (frozen). Plan: `../plans/03-ml-plan.md`.

**Verdict: zero new dependencies.** Both models are written in pure Python stdlib (`math`, `statistics`, `datetime`). They are about 250 lines in total, add 0 MB to the image, need no import warm-up, and score in under 30 ms. statsforecast, PyOD and scikit-learn were each measured and rejected (section 4).

## 1. Scope

| Owns | Purpose |
|---|---|
| `app/ml/forecast.py` | `forecast_demand(product_id, ctx, horizon_days=14) -> dict` plus pure `forecast_series(...)` |
| `app/ml/anomaly.py` | `flag_anomalies(ctx) -> list[dict]` plus pure `score_orders(...)` |
| `app/ml/evaluate.py` | backtest MAE, band coverage, anomaly precision/recall (used by tests and by the README) |
| `app/tools/forecast_demand.py` | read-only tool, single product or "all at risk" |
| `app/tools/create_restock_po.py` | destructive, undoable tool that writes a purchase order |
| `app/tools/flag_anomalies.py` | read-only tool |
| `tests/ml/*`, `tests/tools/test_{forecast_demand,create_restock_po,flag_anomalies}.py` | tests |

Out of scope: holding or voiding orders, supplier emails (the planner chains `send_email`), and the chart code itself (P-UI renders the shapes in §5).

## 2. Algorithms

### 2.1 Forecast (`forecast.py`)

1. **Series.** Daily units sold per product, taken from `order_items` joined to `orders`, excluding `status='cancelled'`. The series runs from the product's first sale (or 180 days ago, whichever is later) to **yesterday**. Today is excluded because it is a partial day. Missing days count as 0.
2. **Guards.** These run in order. Each returns a result instead of raising:

| Case | `method` | Output |
|---|---|---|
| Unknown `product_id` | — | raise `ValueError("unknown product")`; the tool turns it into `ToolResult(ok=False)` |
| `horizon_days` outside 1–60 | — | raise `ValueError` |
| Rows with NULL, NaN or negative qty | (continues) | dropped and counted in `warnings` |
| `on_hand` NULL or negative | — | raise `ValueError("bad on_hand")` (data bug, fail loud) |
| No sales ever, or none in the last 60 days | `no_demand` | rate 0, `days_to_stockout=None`, `reorder_qty=0` |
| Fewer than 14 days since first sale | `insufficient_history` | `days_to_stockout=None`, `reorder_qty=None`; the explanation asks for an explicit qty |
| `on_hand == 0` | (normal method) | `days_to_stockout=0`, range `[0,0]` |

3. **Classify** using Syntetos–Boylan–Croston: ADI is the number of days divided by the number of non-zero days. **ADI ≥ 1.32 means intermittent → Croston-SBA**. Otherwise use **SES × day-of-week index**. The CV² cut-off (0.49) is not used, because both "lumpy" and "intermittent" go to SBA anyway.
4. **SES × DOW.** The DOW index is the mean of each weekday over the last 56 days divided by the overall mean, then renormalised to mean 1. It is all 1s if history is under 28 days. The series is deseasonalised, then fitted with SES using α picked from {0.05, 0.1, 0.2, 0.3, 0.5} by lowest one-step SSE. The forecast is `level × index[weekday]`.
5. **Croston-SBA.** α=0.1. Rate = `(1 − α/2) · z / p`, where z is the smoothed non-zero size and p is the smoothed interval. The forecast is flat.
6. **Band (80%).** σ is the std of the last 56 one-step in-sample residuals, and z₀.₉ = `NormalDist().inv_cdf(0.9)` = 1.2816.
   - Daily band: `lo = max(0, mean − zσ)`, `hi = mean + zσ`.
   - Cumulative demand band to day k: `cum_mean ± zσ√k`.
   - `# ponytail: assumes independent daily errors; switch to a residual bootstrap if coverage drifts below 70%.`
7. **Days to stockout** is the first day k (1-based, from tomorrow) where cumulative demand ≥ `on_hand`:
   - **point** uses `cum_mean`.
   - **earliest** uses `cum_mean + zσ√k`.
   - **latest** uses `cum_mean − zσ√k`.
   - If there is no hit within the horizon, the value is `None` and the text says "not within N days". Incoming POs are ignored here; see reorder.
8. **Reorder qty** uses classic safety stock: `L = lead_time_days`, `C = 14` cover days, `qty = ceil(max(0, cum_mean(L+C) + zσ√(L+C) − on_hand − on_order))`, where `on_order` is the sum of open PO qty. Because open POs are subtracted, a second "restock" request does not double-order.
9. **Gap warning.** If `days_to_stockout < lead_time_days`, the explanation adds "out of stock for about N days before the PO arrives".

### 2.2 Anomalies (`anomaly.py`)

Modified z-score (Iglewicz–Hoaglin, NIST 1.3.5.17): `M = 0.6745·(x − median)/MAD`, flag at |M| ≥ 3.5. It is combined with three business rules scored on the same scale, so a single number and a single reason come out.

| Signal | Value | Score | Reason template |
|---|---|---|---|
| `total` | log1p(order total) | \|M\| | "Order total $X is N× the typical $Y" |
| `units` | units in the order | M (upper tail only) | "N units in one order; typical is Y" |
| `price` | min(paid unit price / catalog price) across lines | `10·(1−ratio)` if ratio < 0.5, else 0 | "Paid $X for an item listed at $Y (Z% of price)" |
| `velocity` | orders by the same customer within ±60 min | `3.5 + (n−3)` if n ≥ 3, else 0 | "1 of N orders from this customer within an hour" |
| `new_mismatch` | first order AND ship country ≠ bill country | **+1.5 boost**, never on its own | "first order, ships to US but billed in CA" |

- `score = max(signals) + boost`. The order is flagged if `score ≥ 3.5`.
- `reason` = the top signal's text, plus the second one if it is also ≥ 3.5, plus the boost text.
- The baseline is **all** orders (180 days). The report window defaults to the **last 7 days** (`since_days`).
- **Guards:**
  - **MAD == 0:** fall back to `(x − med)/(1.253314·MeanAD)`; if that is also 0, M = 0.
  - **Fewer than 30 orders:** raise `InsufficientData`; the tool returns `ok=True` with "too few orders to judge".
  - **Lines with NULL price, catalog price 0, or deleted product:** skip that signal and add a warning.
  - **NaN or negative totals:** the order is skipped and counted.

Why rules rather than IsolationForest alone: on the prototype seed, IsolationForest put only **3 of 8** planted orders in its top 8 and missed the whole velocity burst. It also gives no per-feature reason. Robust z plus rules found **8 of 8** with **0** false positives out of 2,700 (§6).

## 3. Interfaces and shapes

### 3.1 `forecast_demand(product_id, ctx, horizon_days=14) -> dict` (frozen name)

```jsonc
{
  "product_id": "p_hero", "sku": "MUG-BLK", "name": "Black mug",
  "method": "ses_dow",               // ses_dow | croston_sba | no_demand | insufficient_history
  "as_of": "2026-10-29",             // last day of history (yesterday)
  "history_days": 180,
  "on_hand": 30, "on_order": 0, "lead_time_days": 5,
  "avg_daily": 8.3,                  // forecast mean over horizon
  "days_to_stockout": 4,             // int | null (null = not within horizon / no forecast)
  "stockout_range": [3, 6],          // [earliest, latest] | null
  "band": {                          // daily demand, horizon long, column arrays (chart-friendly)
    "level": 0.8,
    "dates": ["2026-10-30", "..."],
    "mean": [9.8, "..."], "lo": [5.1, "..."], "hi": [14.5, "..."]
  },
  "stock": {                         // projected on-hand, same dates
    "mean": [20.2, "..."], "lo": [15.5, "..."], "hi": [24.9, "..."]   // may go negative = shortfall
  },
  "history": {"dates": ["..28 days.."], "units": [7, "..."]},
  "reorder_qty": 96,                 // int | null (null only for insufficient_history)
  "reorder_cost_cents": 115200,
  "explanation": "Sells about 8.3/day, more on weekends. 30 in stock runs out in about 4 days (80% range 3–6). Lead time is 5 days, so order now: 96 units covers the lead time plus 14 days.",
  "warnings": []                     // e.g. "dropped 2 rows with missing qty"
}
```

`forecast_series(units: list[float], first_date: date, on_hand: int, on_order: int, lead_time_days: int, horizon_days: int) -> dict` is the pure core and returns the same keys, minus the product metadata. Every test that does not need a database targets it.

### 3.2 `flag_anomalies(ctx, since_days: int = 7) -> list[dict]` (frozen name; `since_days` is an additive kwarg, see Contract conflicts)

Sorted by score descending:

```jsonc
{ "order_id": "o_2611", "score": 9.8, "threshold": 3.5,
  "reason": "Paid $0.98 for an item listed at $49.00 (2% of price).",
  "signals": {"total": 1.9, "units": 0.0, "price": 9.8, "velocity": 0, "boost": 0},
  "created_at": "2026-10-28T19:04:00Z", "customer_id": "c_118", "total_cents": 98 }
```

### 3.3 Tools (registered via `register(...)`; `ToolSpec` fields as frozen)

| Tool | input_schema (strict, `additionalProperties:false`) | destructive | moves_money | undoable |
|---|---|---|---|---|
| `forecast_demand` | `product_id?: string`; `horizon_days: int 1–60 = 14`; `only_at_risk: bool = true` | no | no | no |
| `create_restock_po` | `product_id: string`; `qty_source: "forecast" \| "user"`; `qty?: int 1–10000` (required only if `qty_source="user"`, forbidden if `"forecast"`) | **yes** | no | **yes** |
| `flag_anomalies` | `since_days: int 1–90 = 7`; `limit: int 1–50 = 10` | no | no | no |

- **`forecast_demand` without `product_id`** loops over active products. It returns `data.items` (each a 3.1 dict), sorted by `days_to_stockout`. With `only_at_risk` it keeps only items whose `days_to_stockout ≤ horizon_days`. `summary` reads: "3 products run out within 7 days: Black mug (4d), …".
- **`create_restock_po`**
  - **`qty_source="forecast"`:** the qty is computed by the tool, so the LLM never writes the number. This is the main prompt-engineering safety hook. If `reorder_qty` is None or 0, `ok=False`, with the explanation as the error.
  - **`preview` → `DiffItem`:**
    - `before`: `{product, on_hand, on_order, days_to_stockout, forecast: <3.1 dict>}`. The UI charts it if `forecast` is present.
    - `after`: `{po: "new", qty, unit_cost_cents, arrives_on, status: "open"}`.
    - `amount_cents`: `qty × unit_cost_cents`.
  - **`run`:** inserts the `purchase_orders` row, then `log_action`, then returns `undo_token=po_id`.
  - **`undo`:** sets the PO to `cancelled` if it is still `open`; if it is already received, returns `ok=False`.
  - Destructive because it commits spend. `moves_money=False` because no Stripe call is made, but `amount_cents` is still shown.
- **Tool `description` text** (the planner sees it):
  - `forecast_demand`: "Forecast daily demand and days until stockout with an 80% range. Use before any restock. Read-only. Quote `explanation`; never compute quantities yourself."
  - `create_restock_po`: "Create a purchase order. Use qty_source='forecast' unless the user stated an exact number."

### 3.4 Words: how the planner explains results

1. All numbers come from `explanation` / `reason`, which are deterministic templates in Python.
2. The planner prompt rule (P2 owns the prompt): "When a step uses forecast or anomaly output, put its `explanation` or `reason` in `Step.rationale` verbatim; do not restate numbers in your own words."
3. Templates per method:
   - `croston_sba`: "Sells rarely: about 1 sale every 6 days, ~1.8 units each (≈0.3/day)…"
   - `no_demand`: "No sales in the last 60 days, so no restock suggested."
   - `insufficient_history`: "Only 5 days of sales, too little to forecast. Tell me a quantity to order."

## 4. Footprint (measured 2026-10-30)

Measured on WSL2, Python 3.12.3, `uv` venvs under the scratch dir. Each script was run twice: run 1 is a cold disk cache, run 2 is warm. RSS is `ru_maxrss` after import plus one workload. The workload is 40 series × 180 days (forecast) or 600×5 (anomaly).

| Option | Installed site-packages | Import (cold / warm) | Peak RSS | Workload time | Notes |
|---|---|---|---|---|---|
| **stdlib only (chosen)** | **0 MB** | ~0 s | 12 MB (bare interpreter 9 MB) | 0.0075 s for 40 series × 5 α plus a 2,700-row MAD (pure Python, measured) | Zero deps |
| numpy only | 60 MB (numpy + numpy.libs) | 0.09 s | 25 MB | — | Fallback if another layer already ships numpy |
| numpy + pandas | 105 MB | 1.53 / 0.31 s | 67–80 MB | 0.002–0.007 s | |
| + scikit-learn 1.9.1 (IsolationForest) | 252 MB (+scipy 111 MB, sklearn 32 MB) | 4.41 / 1.03 s | 152–162 MB | fit+score 0.08–0.10 s | No per-feature reasons; 3/8 planted |
| statsforecast 2.1.1 | 437 MB (pyarrow 162 MB via fugue, statsmodels 44 MB, scipy) | 1.35 / 1.27 s | 207 MB | **1.41–1.46 s per call** (AutoETS + CrostonOptimized, 40 series) | **Pins `pandas<3`** (current pandas 3.1.0). **No longer uses numba** (removed in PR #1099, merged 2026-02-24) |
| PyOD 3.6.7 (ECOD + IForest) | 472 MB (llvmlite 172 MB, numba, matplotlib, sklearn, scipy) | 5.19 / 1.29 s | 258–277 MB | 0.37–0.69 s | Still hard-requires numba + matplotlib |

Reading the table:
1. The brief's premise was "statsforecast pulls numba". That is outdated for 2.1.1. The real costs are now pyarrow (162 MB), a 1.4 s forecast call, and a pandas<3 pin that would fight any other module wanting pandas 3.
2. On a 512 MB container, PyOD (≈270 MB RSS) or statsforecast (≈210 MB) plus FastAPI plus the LLM client fits, but only barely. One request burst could cause an OOM kill. Stdlib leaves the full headroom to the rest of the app.
3. Credibility comes from named methods (Croston-SBA, SES with a seasonal index, the Iglewicz–Hoaglin modified z), a printed backtest against baselines, and band coverage. It does not come from an import line. The README shows the §6 table.

## 5. UI rendering (hand-off to P-UI; vanilla JS + inline SVG, no chart lib)

| Data | Draw |
|---|---|
| `history.units` (28 d) | grey bars |
| `band.mean` / `band.lo`–`band.hi` | line plus shaded area to the right of a "today" rule |
| `stock.mean` (+ lo/hi) | second line on the right axis, dashed below 0 |
| `days_to_stockout`, `stockout_range` | red dot on the x-axis, label "out in 4 d (3–6)" |
| `explanation` | caption under the chart |
| anomaly list | table with columns order · score bar (0–10, tick at 3.5) · reason; click opens the order |

The restock card is `DiffItem.before.forecast` and the anomaly table is `ToolResult.data.items`. Both are plain dicts that need no extra API route.

## 6. Evaluation (prototype numbers; the gates run in `tests/ml/test_evaluate.py` on P1's real seed)

| Metric | How | Prototype result | Gate |
|---|---|---|---|
| Daily MAE (units/day) | rolling origin, 2 folds × 14 d, 12 products (8 regular, 4 slow) | model **1.55**, seasonal-naive 1.77, 28-day mean 1.56 | model ≤ seasonal-naive AND ≤ 1.05 × mean28 |
| 80% band coverage, daily | share of held-out days inside [lo, hi] | **0.84** | 0.70–0.95 |
| 80% band coverage, cumulative | share of days inside the cum band | **0.78** | 0.70–0.95 |
| Anomaly recall on planted | planted orders with score ≥ 3.5 | **8/8** (4 cases, velocity = 5 orders) | 100% |
| Anomaly precision | planted flagged ÷ all flagged, full 180 d | **8/8 = 1.00** (0 FP in 2,700) | ≥ 0.8 |
| Decoy not flagged | big-but-legit order | score **3.19** < 3.5 | < 3.5 |
| Hero stockout | `days_to_stockout` for the demo product | 3 (proto, on_hand 25 ≈ 3 days of demand; range 2–5) | ∈ [3, 5] on P1's seed |
| Speed | `forecast_demand` all products plus `flag_anomalies` | <0.03 s | < 0.5 s |

Honest caveat: the model only ties the 28-day mean on this synthetic data (1.55 vs 1.56). It beats seasonal-naive by 12%. Present it that way. Its real advantage is the weekly shape and the band, not raw MAE.

## 7. Seed-data requirements (for P1's `app/seed/`)

**RNG.** One `random.Random(4680)` (or numpy `default_rng(4680)`) seeded once. No wall-clock randomness.
- Dates are relative to `today` at session creation. History covers `[today−180, today−1]`.
- The same values are produced every session, so every grader sees the same store.

**Required columns** (names are P1's choice; ML adapts in one SQL function per module):

| Table | Columns ML reads/writes |
|---|---|
| products | id, sku, name, price_cents, unit_cost_cents, on_hand, lead_time_days (3–14), supplier_email (`@example.com`), active |
| orders | id, customer_id, created_at (ISO UTC, realistic hours), status, total_cents, ship_country, bill_country |
| order_items | order_id, product_id, qty, unit_price_cents |
| **purchase_orders** (new) | id, product_id, qty, unit_cost_cents, status (`open`/`received`/`cancelled`), created_at, expected_at |

**Demand.** Generate per-product daily units first, then pack them into orders of 1–3 lines. Average about 15 orders/day, about 2,700 orders total. There are 20 products:

1. **12 regular sellers.** Base 1.5–8 units/day, Poisson.
   - Weekday multipliers Mon..Sun = `[0.8, 0.9, 0.95, 1.0, 1.25, 1.4, 1.2]`.
   - Linear trend across 180 d of −30% to +50%: at least 2 rising, 1 falling.
2. **Promo spike.** 3 consecutive days at 3× on 2 regular products, around `today−40`.
3. **5 slow sellers.** A sale happens on a day with probability 0.10–0.25, qty 1–3, so ADI ≥ 1.32.
4. **1 new product.** First sale at `today−5`, to exercise `insufficient_history`.
5. **1 dead product.** No sales in the last 90 days, to exercise `no_demand`.
6. **Normal noise.**
   - 10% of orders carry a 20% coupon (`unit_price = 0.8 × price`).
   - 2% of orders have ship ≠ bill country, all on returning customers.
   - Qty is mostly 1–2 per line.

**Stock** (calibrate `on_hand` from the generated last-28-day mean `m`):

| Product | on_hand | Expected |
|---|---|---|
| HERO regular (~8/day, lead 5 d) | `round(4·m)` | out in 3–5 d, the demo "runs out in 4 days" |
| 2nd regular | `round(6·m)` | out in about 6 d |
| 1 slow seller | 1 | wide range, shows the Croston path |
| 1 regular | 0 | "already out" |
| all others | ≥ `45·m` | safe |

Record `HERO_PRODUCT_ID` and `AT_RISK_PRODUCT_IDS` as constants in the seed module.

**Planted anomalies.** All are in the last 7 days. Export `PLANTED_ANOMALY_ORDER_IDS` and `DECOY_ORDER_IDS`.

| ID | Case | Shape |
|---|---|---|
| A1 | bulk | 25 units of a product normally bought 1–2, yesterday |
| A2 | price glitch | one line at 2% of the catalog price ($0.98 for $49.00) |
| A3 | velocity | a new customer, 5 normal-sized orders within 40 minutes |
| A4 | new + high + mismatch | first order, 9 × $49 (≥ 6× the median total), ship ≠ bill country |
| D1 | decoy (must NOT flag) | returning customer, 4 units at full price |

## 8. Free vs paid

| Option | Cost | Status (2026-10-30) | Use? |
|---|---|---|---|
| stdlib Croston/SES + robust z (chosen) | $0 | — | **yes** |
| statsforecast / scikit-learn / PyOD | $0 (OSS) | measured above | no: footprint |
| Nixtla TimeGPT API | 30-day trial; paid tiers reported at $99/$399 per month (search-only) | trial terms conflict between pages | no: closed model, a key, a network hop in the demo path |
| Amazon Forecast | n/a | closed to new customers since 2024-07-29 | no |
| Azure AI Anomaly Detector | n/a | retired 2026-10-01 | no |
| BigQuery ML ARIMA_PLUS (sandbox) | free sandbox: 1 TiB queries/mo, no card; ARIMA_PLUS in sandbox unverified | — | no: per-session SQLite would need an export to BigQuery |
| HF Inference Providers (Chronos) | $0 included credit on free accounts; PRO $2/mo credit | — | no |

The ML layer has a monthly cost of **$0**. There is no paid item, so no free alternative needs to be listed.

## 9. Contract conflicts

1. **`flag_anomalies(ctx)`** needs a window. I add the optional kwarg `since_days: int = 7`. Same name, backward compatible. The integrator should confirm.
2. **The frozen comment "statsforecast… numba"** (shortlist and brief) is outdated. statsforecast 2.1.1 has no numba, and this layer uses neither. Docs that cite "statsforecast" or "PyOD" (`00-shortlist.md` layer table) should say "Croston-SBA / SES / modified z, stdlib".
3. **`Ctx`** is unspecified. ML needs `ctx.db` (a sqlite3 connection or a `get_db` handle) and `ctx.today` (a `date`; tests inject it). If `today` is missing, the fallback is `datetime.now(UTC).date()`.
4. **A `purchase_orders` table** and the product columns `unit_cost_cents`, `lead_time_days`, `supplier_email`, `on_hand` are not in any frozen list. P1 must add them, or `create_restock_po` has nowhere to write.
5. **`create_restock_po` sets `moves_money=False` but fills `DiffItem.amount_cents`.** The validator and UI must show the amount whenever `amount_cents` is not None, not only when `moves_money` is set.

## 10. Sources (all accessed 2026-10-30 unless dated)

1. statsforecast 2.1.1 metadata (pandas<3, no numba), uploaded 2026-07-16: https://pypi.org/pypi/statsforecast/2.1.1/json
2. statsforecast numba removal, PR #1099, merged 2026-02-24: https://github.com/Nixtla/statsforecast/pull/1099 ; older numba compile of about 22.8 s (issue #753, 2024-01-22): https://github.com/Nixtla/statsforecast/issues/753
3. numba 0.68.1 (3.9 MB wheel, 2026-10-27): https://pypi.org/pypi/numba/0.68.1/json ; llvmlite 0.50.0 (59.7 MB wheel, 2026-09-29): https://pypi.org/pypi/llvmlite/0.50.0/json
4. PyOD 3.6.7 deps (numba, matplotlib, sklearn, scipy, joblib), 2026-10-12: https://pypi.org/pypi/pyod/json
5. scikit-learn 1.9.1 (9.2 MB wheel, 2026-09-10): https://pypi.org/pypi/scikit-learn/1.9.1/json ; scipy 1.18.1 (35.3 MB wheel, 2026-08-21): https://pypi.org/pypi/scipy/1.18.1/json
6. Modified z-score, 0.6745, threshold 3.5: https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm (Iglewicz & Hoaglin 1993)
7. ADI 1.32 / CV² 0.49 classification: Syntetos, Boylan, Croston 2005, JORS 56(5) https://eprints.lancs.ac.uk/id/eprint/73095 (search-only); SBA/TSB: Teunter, Syntetos, Babai 2011, EJOR 214(3) https://econpapers.repec.org/RePEc:eee:ejores:v:214:y:2011:i:3:p:606-615 (search-only)
8. TimeGPT plans: https://www.nixtla.io/docs/introduction/timegpt_subscription_plans ; Amazon Forecast: https://docs.aws.amazon.com/forecast/latest/dg/what-is-forecast.html ; Azure Anomaly Detector retirement (page updated 2026-10-05): https://learn.microsoft.com/en-us/previous-versions/azure/ai-services/anomaly-detector/overview ; BigQuery sandbox: https://docs.cloud.google.com/bigquery/docs/sandbox ; HF pricing: https://huggingface.co/docs/inference-providers/pricing
9. Local measurements: the scripts are in the P3 scratch dir and are not part of the repo. Rerun recipe: plan appendix "re-measure the footprint".
