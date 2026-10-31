"""ML fixtures. `ctx` (seeded store, today=2026-10-15) comes from tests/conftest.py (R30)."""

import math
import random

import pytest

WEEKDAY_MULT = (0.8, 0.9, 0.95, 1.0, 1.25, 1.4, 1.2)


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


@pytest.fixture
def synth():
    """synth(base, trend=0, n=180, seed=4680) -> daily Poisson units with DOW multipliers."""
    from datetime import date, timedelta

    def make(
        base: float,
        trend: float = 0.0,
        n: int = 180,
        seed: int = 4680,
        first: date = date(2026, 4, 18),
    ) -> list[float]:
        rng = random.Random(seed)  # noqa: S311 - deterministic test data
        out = []
        for i in range(n):
            wd = WEEKDAY_MULT[(first + timedelta(i)).weekday()]
            lam = base * wd * (1 + trend * i / max(n - 1, 1))
            out.append(float(_poisson(rng, lam)))
        return out

    return make
