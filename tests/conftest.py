"""Synthetic HA fixtures. No NAS, account, or production HA is required."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.runtime import FeiNiuRuntime

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    """Allow the local integration to be loaded by HA itself."""


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic music",
        data={
            "url": "http://music.invalid/music/",
            "username": "synthetic-user",
            "password": "SYNTHETIC_PASSWORD",
            "device_id": "a" * 32,
            "account_id": "account-one",
        },
    )


@pytest.fixture
def client():
    result = MagicMock()
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=None)
    for name in ("login", "detail", "page", "related", "playlists", "search", "cover", "lyrics"):
        setattr(result, name, AsyncMock())
    result.login.return_value = {"guid": "account-one"}
    return result


@pytest.fixture
def runtime(hass, entry, client):
    entry.add_to_hass(hass)
    value = FeiNiuRuntime(hass, entry, client)
    entry.runtime_data = value
    hass.data[DOMAIN] = {"entries": {entry.entry_id: value}}
    return value


def track(guid="track-one", **kwargs):
    return {
        "guid": guid,
        "title": "Synthetic track",
        "accessStatus": 0,
        "audioSpec": {"format": "flac"},
        **kwargs,
    }
