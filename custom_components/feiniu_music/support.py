"""Small privacy helpers for native diagnostics and DEBUG logs; no stored identifiers."""

import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.diagnostics import REDACTED, async_redact_data

_SALT = secrets.token_bytes(32)


def private_id(value: str | None) -> str | None:
    """Correlate observations only within this HA process, without exporting identities."""
    return hmac.new(_SALT, value.encode(), hashlib.sha256).hexdigest()[:12] if value else None


def safe_address(value: str) -> dict[str, Any]:
    """Keep routing hints, never userinfo, queries, fragments or custom path contents."""
    try:
        parsed = urlsplit(value)
        return async_redact_data(
            {
                "scheme": parsed.scheme if parsed.scheme in {"http", "https"} else "other",
                "host": parsed.hostname,
                "host_ref": private_id(parsed.hostname),
                "port": parsed.port,
                "path": parsed.path if parsed.path in {"", "/", "/music", "/music/"} else REDACTED,
            },
            {"host"},
        )
    except ValueError:
        return {"valid": False}


def safe_state(value: str | None) -> str:
    """Third-party entity states can contain arbitrary text."""
    if value is None:
        return "missing"
    return (
        value
        if value
        in {
            "playing",
            "paused",
            "idle",
            "off",
            "on",
            "buffering",
            "standby",
            "unavailable",
            "unknown",
        }
        else "other"
    )
