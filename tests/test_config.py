import pytest

from app.config import load_settings, session_hash


def test_defaults():
    s = load_settings({})
    assert s.app_env == "dev" and s.max_sessions == 100 and s.session_ttl_hours == 24
    assert s.llm_mode == "live" and s.planner_effort == "medium" and s.stripe_mode == "auto"
    assert s.stripe_max_writes_per_session == 20 and s.llm_daily_budget_usd == 5.0


def test_test_env_defaults_to_replay():
    assert load_settings({"APP_ENV": "test"}).llm_mode == "replay"
    assert load_settings({"APP_ENV": "test", "LLM_MODE": "record"}).llm_mode == "record"


@pytest.mark.parametrize("key", ["sk_live_abc", "rk_live_abc", "garbage"])
def test_bad_stripe_key_rejected(key):
    with pytest.raises(ValueError, match="sk_test_"):
        load_settings({"STRIPE_SECRET_KEY": key})


@pytest.mark.parametrize("key", ["", "sk_test_abc", "rk_test_abc"])
def test_ok_stripe_key(key):
    load_settings({"STRIPE_SECRET_KEY": key})


def test_prod_requires_selected_provider_key():
    prod = {"APP_ENV": "prod"}
    for bad in (
        {"ANTHROPIC_API_KEY": "k"},
        {"GOOGLE_API_KEY": "k"},  # no project
        {"GOOGLE_CLOUD_PROJECT": "p"},  # no credential
    ):
        with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
            load_settings({**prod, **bad})
    s = load_settings({**prod, "GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_API_KEY": "k"})
    assert s.google_cloud_location == "global"
    load_settings(
        {**prod, "GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_APPLICATION_CREDENTIALS_JSON": '{"a": 1}'}
    )
    with pytest.raises(ValueError, match="JSON object"):
        load_settings({"GOOGLE_APPLICATION_CREDENTIALS_JSON": "not json"})
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        load_settings({**prod, "LLM_PROVIDER": "anthropic", "GOOGLE_API_KEY": "k"})
    load_settings({"APP_ENV": "prod", "LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"})


def test_secret_not_in_repr():
    s = load_settings(
        {
            "ANTHROPIC_API_KEY": "sk-ant-xyz",
            "GOOGLE_API_KEY": "AIzaXyz",
            "GOOGLE_APPLICATION_CREDENTIALS_JSON": '{"private_key": "PkSecret"}',
            "STRIPE_SECRET_KEY": "sk_test_zzz",
        }
    )
    assert (
        "sk-ant-xyz" not in repr(s)
        and "sk_test_zzz" not in repr(s)
        and "AIzaXyz" not in repr(s)
        and "PkSecret" not in repr(s)
    )


def test_session_hash():
    h = session_hash("abc")
    assert len(h) == 16 and h == session_hash("abc") and h != session_hash("abd")


@pytest.mark.parametrize(
    "env",
    [
        {"STRIPE_SECRET_KEY": "sk_live_Zq9Leak"},
        {"APP_ENV": "prod", "STRIPE_SECRET_KEY": "rk_test_Zq9Leak"},
    ],
)
def test_boot_error_hides_secret(env):
    with pytest.raises(ValueError) as e:
        load_settings(env)
    assert "Zq9Leak" not in str(e.value)


@pytest.mark.parametrize(
    "field",
    [
        "LLM_DAILY_BUDGET_USD",
        "LLM_SESSION_BUDGET_USD",
        "SESSION_TTL_HOURS",
        "MAX_SESSIONS",
        "PLAN_TTL_MINUTES",
        "LLM_MAX_PLANS_PER_SESSION_HOUR",
        "STRIPE_MAX_WRITES_PER_SESSION",
    ],
)
@pytest.mark.parametrize("val", ["nan", "inf", "0", "-1"])
def test_limits_must_be_positive_finite(field, val):
    with pytest.raises(ValueError):
        load_settings({field: val})


def test_cheap_model_defaults_per_provider():
    s = load_settings({})
    assert s.llm_provider == "gemini"
    assert (s.planner_model, s.judge_model) == ("gemini-3.8-flash", "gemini-3.1-flash-lite")
    o = load_settings({"PLANNER_MODEL": "gemini-3.1-flash-lite"})  # env override still works
    assert o.planner_model == "gemini-3.1-flash-lite"
    a = load_settings({"LLM_PROVIDER": "anthropic", "PLANNER_MODEL": ""})
    assert a.planner_model == a.judge_model == "claude-haiku-5-5"
    assert s.llm_daily_budget_usd <= 5.0 and s.llm_session_budget_usd <= 0.25


@pytest.mark.parametrize(
    "env",
    [
        {"PLANNER_MODEL": "claude-sonnet-5-5"},
        {"PLANNER_MODEL": "claude-haiku-5-5"},  # wrong provider for the gemini default
        {"LLM_PROVIDER": "anthropic", "JUDGE_MODEL": "gemini-3.1-flash-lite"},
        {"JUDGE_MODEL": "gemini-2.5-flash"},
    ],
)
def test_expensive_or_mismatched_model_rejected(env):
    with pytest.raises(ValueError, match="cheap models"):
        load_settings(env)


def test_every_cheap_model_is_priced():
    from app.config import CHEAP_MODELS
    from app.llm.budget import PRICES

    assert {m for ms in CHEAP_MODELS.values() for m in ms} <= set(PRICES)
