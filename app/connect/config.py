"""Connect settings, the feature flag and the "helpful error" helpers (spec 10 §5).

Read lazily on the first /api/connect request, never at boot: a missing or bad value turns
Connect into a 503 that names the variable, and can never stop the demo app from starting.
Logs and errors name variables, never their values.
"""

import functools
import logging
import os
import re
from collections.abc import Mapping
from typing import NoReturn

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

log = logging.getLogger(__name__)

ON_VALUES = frozenset({"1", "true", "yes", "on"})
BASE_URL_RE = re.compile(r"\Ahttps?://[A-Za-z0-9.-]+(:\d{1,5})?\Z")  # no path, query or slash
PRICE_ID_RE = re.compile(r"\Aprice_[A-Za-z0-9]+\Z")

# What to do when a value is missing. require() puts this in the 503 and in the server log.
HINTS = {
    "STRIPE_SECRET_KEY": "add your sandbox secret key (sk_test_...) to .env",
    "PUBLIC_BASE_URL": "set it to this server's address, e.g. http://localhost:8000",
    "STRIPE_PLATFORM_PRICE_ID": (
        "run scripts/create_platform_price.py and put the price_... id it prints in .env"
    ),
    "STRIPE_CONNECT_THIN_WEBHOOK_SECRET": (
        "copy the whsec_... printed by the thin-events `stripe listen` (docs/connect-setup.md)"
    ),
    "STRIPE_BILLING_WEBHOOK_SECRET": (
        "copy the whsec_... printed by the billing `stripe listen` (docs/connect-setup.md)"
    ),
}


def flag_on() -> bool:
    """CONNECT_ENABLED, read raw on every request, so a broken setting can't turn "off" into 503."""
    return os.environ.get("CONNECT_ENABLED", "").strip().lower() in ON_VALUES


class ConnectSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)  # never echo a value

    app_env: str = "dev"  # APP_ENV (already validated by app.config); prod needs https below
    # PLACEHOLDER: PUBLIC_BASE_URL=http://localhost:8000 locally,
    #              https://<service>.onrender.com on Render. Stripe redirects back here.
    public_base_url: str | None = None
    # PLACEHOLDER: STRIPE_CONNECT_THIN_WEBHOOK_SECRET=whsec_... from the thin-events listener
    #              (`stripe listen --thin-events ...`) or the thin event destination.
    stripe_connect_thin_webhook_secret: SecretStr | None = None
    # PLACEHOLDER: STRIPE_BILLING_WEBHOOK_SECRET=whsec_... from the billing listener
    #              (`stripe listen --events customer.subscription...`) or the snapshot destination.
    stripe_billing_webhook_secret: SecretStr | None = None
    # PLACEHOLDER: STRIPE_PLATFORM_PRICE_ID=price_... printed by scripts/create_platform_price.py.
    #              Not a secret: it is the monthly "ShopPilot+ Pro" platform plan.
    stripe_platform_price_id: str | None = None
    # Optional: the platform's fee on each storefront sale, in cents (the brief's sample is 123).
    connect_application_fee_cents: int = Field(123, ge=0, le=10_000)

    @field_validator("public_base_url")
    @classmethod
    def _base_url(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is not None and not BASE_URL_RE.fullmatch(v):
            raise ValueError("expected scheme://host[:port] with no path or trailing slash")
        if v is not None and info.data.get("app_env") == "prod" and not v.startswith("https://"):
            raise ValueError("must be https when APP_ENV=prod")
        return v

    @field_validator("stripe_connect_thin_webhook_secret", "stripe_billing_webhook_secret")
    @classmethod
    def _whsec(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and not v.get_secret_value().startswith("whsec_"):
            raise ValueError("must start with whsec_")
        return v

    @field_validator("stripe_platform_price_id")
    @classmethod
    def _price(cls, v: str | None) -> str | None:
        if v is not None and not PRICE_ID_RE.fullmatch(v):
            raise ValueError("must look like price_...")
        return v


def load_connect_settings(env: Mapping[str, str] = os.environ) -> ConnectSettings:
    """Strip every value (a CRLF .env leaves a hidden \\r) and treat an empty one as unset."""
    vals = {}
    for name in ConnectSettings.model_fields:
        raw = env.get(name.upper(), "").strip()
        if raw:
            vals[name] = raw
    return ConnectSettings(**vals)


@functools.cache
def connect_settings() -> ConnectSettings:
    """Parsed once per process. A bad value -> 503 connect_misconfigured that names it."""
    try:
        return load_connect_settings()
    except ValidationError as e:
        names = ", ".join(sorted({str(x["loc"][0]).upper() for x in e.errors() if x["loc"]}))
        log.error("invalid Connect setting: %s (see .env.example for the format)", names)
        fail(503, "connect_misconfigured", f"Invalid Connect setting: {names}. See .env.example.")


def fail(status: int, code: str, message: str) -> NoReturn:
    """Raise the app's JSON error envelope: {"error": {"code", "message"}}."""
    from app.main import ApiError  # lazy: app.main imports this package (like safety/web.py)

    raise ApiError(status, code, message)


def require[T](value: T | None, name: str) -> T:
    """The brief's helpful error: a missing value -> 503 + a log line saying how to fill it in."""
    if value is None:
        log.warning("%s is not set: %s", name, HINTS[name])
        fail(503, "connect_not_configured", f"{name} is not set: {HINTS[name]}.")
    return value
