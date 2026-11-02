"""scripts/create_platform_price.py is idempotent: it creates only what is missing."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_platform_price.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("create_platform_price", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_client(products=(), prices=()):
    """Platform-level products/prices services that record creates."""
    made = []

    def create(kind, prefix):
        def _create(params, options=None):
            made.append((kind, params))
            return SimpleNamespace(id=f"{prefix}_New{len(made)}")

        return _create

    v1 = SimpleNamespace(
        products=SimpleNamespace(
            list=lambda params=None, options=None: SimpleNamespace(data=list(products)),
            create=create("product", "prod"),
        ),
        prices=SimpleNamespace(
            list=lambda params=None, options=None: SimpleNamespace(data=list(prices)),
            create=create("price", "price"),
        ),
    )
    return SimpleNamespace(v1=v1), made


def tagged(pid="prod_Tagged1", tag="1"):
    return SimpleNamespace(id=pid, metadata=SimpleNamespace(shoppilot_platform=tag))


def test_first_run_creates_the_product_and_the_monthly_price(script):
    client, made = fake_client(products=[tagged("prod_Other1", tag="0")])
    assert script.ensure_platform_price(client) == ("price_New2", True)
    (kind1, product), (kind2, price) = made
    assert kind1 == "product" and product["metadata"] == {"shoppilot_platform": "1"}
    assert kind2 == "price" and price == {
        "product": "prod_New1",
        "currency": "usd",
        "unit_amount": 900,
        "recurring": {"interval": "month"},
        "lookup_key": "shoppilot_pro_monthly",
    }


def test_rerun_reuses_the_price_and_creates_nothing(script):
    client, made = fake_client(prices=[SimpleNamespace(id="price_Existing1")])
    assert script.ensure_platform_price(client) == ("price_Existing1", False)
    assert made == []


def test_reuses_the_tagged_product_when_only_the_price_is_missing(script):
    client, made = fake_client(products=[tagged()])
    assert script.ensure_platform_price(client) == ("price_New1", True)
    assert made == [("price", {**made[0][1], "product": "prod_Tagged1"})]


@pytest.mark.parametrize("key", ["", "  ", "sk_live_x", "pk_test_x"])
def test_main_refuses_a_missing_or_non_sandbox_key(script, monkeypatch, capsys, key):
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    assert script.main() == 2
    err = capsys.readouterr().err
    assert "STRIPE_SECRET_KEY" in err and "sk_live_x" not in err
