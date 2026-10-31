"""Record eval recordings live (P2-T11). Needs ANTHROPIC_API_KEY; costs about $1.

    uv run python -m tests.eval.record [--only c04_refund_damaged] [--out DIR]

Fresh seeded temp store per case (anchor 2026-10-15), LLM_MODE=record, make_plan writes
app/llm/recordings/<key>.json. Guard verdicts for seed E001/E003/E004 are recorded first
(R25) so replay never fail-closes the damaged email.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from secrets import token_urlsafe


def _record_guard() -> None:
    from app.db import create_store, get_db
    from app.safety import inbound_guard
    from app.tools.registry import Ctx
    from tests.eval.test_eval import ANCHOR, NOW

    inbound_guard._cache.clear()  # force real calls so guard_<key>.json files get written
    sid = token_urlsafe(32)
    create_store(sid, ANCHOR)
    with get_db(sid) as db:
        for e in inbound_guard.screen_inbox(Ctx(sid, db, NOW, ANCHOR)):
            print(f"guard {e['id']}: {e['verdict']['label']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.eval.record")
    ap.add_argument("--only", help="record one case id")
    ap.add_argument("--out", type=Path, help="recordings dir (default app/llm/recordings)")
    a = ap.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (use the shoppilot-dev key).", file=sys.stderr)
        return 2
    os.environ["LLM_MODE"] = "record"
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="shoppilot-eval-"))

    import app.llm.client as llm
    from app.config import get_settings
    from tests.eval.test_eval import CASES, run_case

    get_settings.cache_clear()
    if a.out:
        llm.RECORDINGS_DIR = a.out
    cases = [c for c in CASES if a.only in (None, c["id"])]
    if not cases:
        print(f"unknown case id: {a.only}", file=sys.stderr)
        return 2
    if a.only is None:
        _record_guard()
    total, passed = 0.0, 0
    print(f"{'case':34} {'result':6} {'calls':>5} {'cost':>8}")
    for c in cases:
        plan, fails = run_case(c)
        cost = plan.usage.get("total_cost_usd", 0.0)
        total, passed = total + cost, passed + (not fails)
        print(
            f"{c['id']:34} {'PASS' if not fails else 'FAIL':6} "
            f"{len(plan.usage.get('calls', [])):>5} {cost:>8.4f}"
        )
        for f in fails:
            print(f"    {plan.status}: {f}")
    print(f"{passed}/{len(cases)} passed, total ${total:.4f}, recordings in {llm.RECORDINGS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
