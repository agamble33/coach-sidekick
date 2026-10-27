"""Offline health check: reports which providers are configured. No network calls."""

from __future__ import annotations

from typing import Mapping

from . import __version__
from .config import ConfigError, load_settings


def health_report(env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """Return (exit_code, text). Exit 0 if at least one provider is configured."""
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        return 2, f"muse-replay {__version__}: config error: {exc}"

    lines = [f"muse-replay {__version__}"]
    for name, ok in settings.providers().items():
        lines.append(f"  {name}: {'configured' if ok else 'missing'}")
    code = 0 if any(settings.providers().values()) else 1
    if code:
        lines.append("  no model provider configured; see .env.example")
    return code, "\n".join(lines)
