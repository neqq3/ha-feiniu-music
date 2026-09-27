"""Exercise actual HA config flows, including failed initial setup and password updates."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.feiniu_music.client import AuthenticationError, NetworkError
from custom_components.feiniu_music.config_flow import FeiNiuConfigFlow
from custom_components.feiniu_music.const import DOMAIN


async def test_initial_failure_can_change_identity_and_password_is_not_echoed(hass, client):
    with (
        patch("custom_components.feiniu_music.config_flow.create_client", return_value=client),
        patch("custom_components.feiniu_music.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        client.login.side_effect = AuthenticationError("invalid")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"url": "http://wrong.invalid", "username": "wrong", "password": "SENTINEL_PASSWORD"},
        )
        assert result["errors"] == {"base": "invalid_auth"}
        assert "SENTINEL_PASSWORD" not in repr(result)
        device = client.login.call_args.args[2]
        client.login.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"url": "http://right.invalid/music/", "username": "right", "password": "replacement"},
        )
        assert result["step_id"] == "outputs"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"outputs": []})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["url"] == "http://right.invalid/music/"
        assert result["data"]["device_id"] == device


@pytest.mark.parametrize("value", ["", "NEW_PASSWORD"])
async def test_password_reconfiguration_keeps_device_and_identity(hass, entry, client, value):
    entry.add_to_hass(hass)
    with (
        patch("custom_components.feiniu_music.config_flow.create_client", return_value=client),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        assert "SYNTHETIC_PASSWORD" not in repr(result)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": value}
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        client.login.assert_awaited_once_with(
            "synthetic-user", value or "SYNTHETIC_PASSWORD", "a" * 32
        )
        assert entry.data["device_id"] == "a" * 32
        assert entry.data["username"] == "synthetic-user"


@pytest.mark.parametrize("field,value", [("url", "http://other.invalid"), ("username", "other")])
async def test_server_rejects_identity_change_before_login(hass, entry, client, field, value):
    entry.add_to_hass(hass)
    flow = FeiNiuConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    with patch("custom_components.feiniu_music.config_flow.create_client", return_value=client):
        result = await flow.async_step_reconfigure({field: value, "password": "NEW"})
    assert result["reason"] == "identity_change"
    client.login.assert_not_called()
    assert entry.data["password"] == "SYNTHETIC_PASSWORD"


async def test_reauth_updates_same_account(hass, entry, client):
    entry.add_to_hass(hass)
    with (
        patch("custom_components.feiniu_music.config_flow.create_client", return_value=client),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new"}
        )
        assert result["reason"] == "reauth_successful"
        assert entry.data["password"] == "new"


async def test_network_error_is_actionable_not_empty_success(hass, client):
    with patch("custom_components.feiniu_music.config_flow.create_client", return_value=client):
        client.login.side_effect = NetworkError("offline")
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={"url": "http://music.invalid", "username": "one", "password": "secret"},
        )
        assert result["errors"] == {"base": "cannot_connect"}
