"""Create an isolated, HA-managed HTTP session for one music account."""

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import FeiNiuClient
from .protocol import PROFILE


def create_client(hass: HomeAssistant, url: str) -> FeiNiuClient:
    """Inject HA's session factory while retaining explicit entry unload cleanup."""
    return FeiNiuClient(
        url,
        PROFILE,
        session_factory=lambda: async_create_clientsession(
            hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
        ),
    )
