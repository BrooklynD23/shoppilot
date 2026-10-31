"""Settings from env. Secrets are SecretStr so they never show in repr/logs."""

import functools
import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)  # never echo secrets

    app_env: Literal["dev", "test", "prod"] = "dev"
    data_dir: Path = Path("/tmp/shoppilot")  # noqa: S108 - disposable demo stores
    session_ttl_hours: int = Field(24, gt=0)
    max_sessions: int = Field(100, gt=0)
    plan_ttl_minutes: int = Field(15, gt=0)
    anthropic_api_key: SecretStr | None = None
    planner_model: str = "claude-sonnet-5-5"
    judge_model: str = "claude-haiku-5-5"
    planner_effort: Literal["low", "medium", "high"] = "medium"
    llm_mode: Literal["live", "replay", "record"] = "live"
    llm_daily_budget_usd: float = Field(5.0, gt=0, allow_inf_nan=False)
    llm_session_budget_usd: float = Field(0.5, gt=0, allow_inf_nan=False)
    llm_max_plans_per_session_hour: int = Field(20, gt=0)
    stripe_secret_key: SecretStr | None = None
    stripe_mode: Literal["auto", "mock"] = "auto"
    stripe_max_writes_per_session: int = Field(20, gt=0)

    @field_validator("anthropic_api_key", "stripe_secret_key", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if v == "" else v

    @field_validator("stripe_secret_key")
    @classmethod
    def _test_key_only(cls, v: SecretStr | None):
        if v is not None and not v.get_secret_value().startswith(("sk_test_", "rk_test_")):
            raise ValueError("STRIPE_SECRET_KEY must be empty or start with sk_test_ or rk_test_")
        return v

    @model_validator(mode="after")
    def _prod_needs_key(self):
        if self.app_env == "prod" and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when APP_ENV=prod")
        return self


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    vals = {k.lower(): v for k, v in env.items() if k.lower() in Settings.model_fields}
    if "llm_mode" not in vals and vals.get("app_env") == "test":
        vals["llm_mode"] = "replay"
    return Settings(**vals)


@functools.cache
def get_settings() -> Settings:
    return load_settings()


def session_hash(session_id: str) -> str:
    """Safe-to-log id (R21). The raw session id never leaves the server."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:16]
