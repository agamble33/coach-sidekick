"""Settings loaded from environment variables.

A provider counts as configured only when everything it needs is present.
Key values are never included in repr() or str() output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

BASETEN_DEFAULT_URL = "https://inference.baseten.co/v1"
BASETEN_DEFAULT_MODEL = "meta-models/muse-spark-open-1026"


class ConfigError(ValueError):
    """Raised when a setting is present but invalid."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _https_url(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"{name} must be an https URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    meta_api_key: str | None = field(default=None, repr=False)
    meta_base_url: str | None = None
    baseten_api_key: str | None = field(default=None, repr=False)
    baseten_base_url: str = BASETEN_DEFAULT_URL
    baseten_model: str = BASETEN_DEFAULT_MODEL

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_api_key and self.meta_base_url)

    @property
    def baseten_configured(self) -> bool:
        return bool(self.baseten_api_key)

    def providers(self) -> dict[str, bool]:
        return {
            "meta_model_api": self.meta_configured,
            "baseten_muse_spark_open": self.baseten_configured,
        }


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from a mapping (defaults to os.environ)."""
    env = os.environ if env is None else env
    return Settings(
        meta_api_key=_clean(env.get("META_API_KEY")),
        meta_base_url=_https_url("META_BASE_URL", _clean(env.get("META_BASE_URL"))),
        baseten_api_key=_clean(env.get("BASETEN_API_KEY")),
        baseten_base_url=_https_url(
            "BASETEN_BASE_URL", _clean(env.get("BASETEN_BASE_URL"))
        )
        or BASETEN_DEFAULT_URL,
        baseten_model=_clean(env.get("BASETEN_MODEL")) or BASETEN_DEFAULT_MODEL,
    )
