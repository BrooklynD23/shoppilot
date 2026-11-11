"""Settings from env. Secrets are SecretStr so they never show in repr/logs."""

import functools
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

# Spend guard: only these cheap models may serve live calls, per provider. Every model here
# needs a price in app/llm/budget.py. User decisions: 2026-11-02 Haiku only; 2026-11-10 Gemini
# is the default provider; the judgment-heavy planner gets a stronger model (3.5 Flash-Lite
# scored 22/24 on the offline eval, 3.8 Flash 24/24), cheap Flash-Lite serves the rest.
CHEAP_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"),
    "anthropic": ("claude-haiku-5-5",),
}
# Default model per provider and stage. judge_model also serves the router and inbound guard.
DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "gemini": {"planner_model": "gemini-3.8-flash", "judge_model": "gemini-3.1-flash-lite"},
    "anthropic": {"planner_model": "claude-haiku-5-5", "judge_model": "claude-haiku-5-5"},
}


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)  # never echo secrets

    app_env: Literal["dev", "test", "prod"] = "dev"
    data_dir: Path = Path("/tmp/shoppilot")  # noqa: S108 - disposable demo stores
    session_ttl_hours: int = Field(24, gt=0)
    max_sessions: int = Field(100, gt=0)
    plan_ttl_minutes: int = Field(15, gt=0)
    llm_provider: Literal["gemini", "anthropic"] = "gemini"
    # Gemini runs on Vertex AI (GCP credits). Auth: a Vertex API key (express mode) or a
    # service-account JSON (written to a temp file for ADC on the first live call).
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    google_api_key: SecretStr | None = None
    google_application_credentials_json: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Empty -> the provider's default for that stage (see DEFAULT_MODELS).
    planner_model: str = ""
    judge_model: str = ""
    planner_effort: Literal["low", "medium", "high"] = "medium"
    llm_mode: Literal["live", "replay", "record"] = "live"
    llm_daily_budget_usd: float = Field(5.0, gt=0, allow_inf_nan=False)
    llm_session_budget_usd: float = Field(0.25, gt=0, allow_inf_nan=False)
    llm_max_plans_per_session_hour: int = Field(20, gt=0)
    stripe_secret_key: SecretStr | None = None
    stripe_mode: Literal["auto", "mock"] = "auto"
    stripe_max_writes_per_session: int = Field(20, gt=0)

    @model_validator(mode="before")
    @classmethod
    def _provider_defaults(cls, data):
        if not isinstance(data, dict):
            return data
        provider = data.get("llm_provider") or "gemini"
        out = {**data, "llm_provider": provider}
        defaults = DEFAULT_MODELS.get(provider, {})
        for k in ("planner_model", "judge_model"):
            out[k] = data.get(k) or defaults.get(k, "")
        return out

    @field_validator(
        "google_cloud_project",
        "google_api_key",
        "google_application_credentials_json",
        "anthropic_api_key",
        "stripe_secret_key",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v):
        return None if v == "" else v

    @field_validator("google_cloud_location", mode="before")
    @classmethod
    def _default_location(cls, v):
        return v or "global"

    @field_validator("google_application_credentials_json")
    @classmethod
    def _sa_json_object(cls, v: SecretStr | None):
        if v is None:
            return v
        try:
            ok = isinstance(json.loads(v.get_secret_value()), dict)
        except ValueError:
            ok = False
        if not ok:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON must be a JSON object")
        return v

    @field_validator("stripe_secret_key")
    @classmethod
    def _test_key_only(cls, v: SecretStr | None):
        if v is not None and not v.get_secret_value().startswith(("sk_test_", "rk_test_")):
            raise ValueError("STRIPE_SECRET_KEY must be empty or start with sk_test_ or rk_test_")
        return v

    @model_validator(mode="after")
    def _cheap_models_only(self):
        allowed = CHEAP_MODELS[self.llm_provider]
        for m in (self.planner_model, self.judge_model):
            if m not in allowed:
                raise ValueError(
                    f"Only cheap models are allowed for LLM_PROVIDER={self.llm_provider} "
                    f"(API spend limit): {', '.join(allowed)}"
                )
        return self

    @model_validator(mode="after")
    def _prod_needs_key(self):
        if self.app_env != "prod":
            return self
        if self.llm_provider == "anthropic" and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when APP_ENV=prod")
        if self.llm_provider == "gemini" and (
            self.google_cloud_project is None
            or (self.google_api_key is None and self.google_application_credentials_json is None)
        ):
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT and one of GOOGLE_API_KEY or "
                "GOOGLE_APPLICATION_CREDENTIALS_JSON are required when APP_ENV=prod"
            )
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
