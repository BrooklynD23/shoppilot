# Offline eval (P2-T11)

24 cases in `cases.json` (spec 02 §8 + chip prompts c05/c23/c24, R33). Pass bar: >= 22/24 and c04-c07 (injection set) green.

## Record (needs the dev key, about $1)

```bash
ANTHROPIC_API_KEY=sk-ant-... uv run python -m tests.eval.record          # all cases + guard E001/E003/E004
ANTHROPIC_API_KEY=sk-ant-... uv run python -m tests.eval.record --only c04_refund_damaged
ANTHROPIC_API_KEY=sk-ant-... uv run python -m tests.eval.record --out /tmp/rec_low   # scratch dir (P2-T13)
```

Writes `app/llm/recordings/<recording_key>.json` and `guard_<sha16>.json`, prints case / result / calls / cost and the total.
A single `--only` run skips the guard pass; run the full set once first.

## Replay

```bash
uv run pytest tests/eval -v
```

Without recordings, the replay tests skip and only the loader and scorer tests run. Any prompt edit changes `PROMPT_VERSION`, so `test_recordings_fresh` fails until you re-record.
