"""Exercise actual HA config flows, including failed initial setup and password updates."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.feiniu_music.client import AuthenticationError, NetworkError
from custom_components.feiniu_music.config_flow import FeiNiuConfigFlow
from custom_components.feiniu_music.const import DOMAIN


@pytest.mark.parametrize("options", [False, True])
@pytest.mark.parametrize(
    "reason",
    [
        "output_not_media_player",
        "output_self",
        "output_missing_registry",
        "output_unavailable",
        "output_no_play_media",
        "output_wrapper_loop",
        "output_wrapped_feiniu",
        "invalid_output",
    ],
)
async def test_output_reasons_survive_both_native_flows(hass, entry, options, reason, caplog):
    from custom_components.feiniu_music.output import OutputValidationError

    entry.add_to_hass(hass)
    if options:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "outputs"}
        )
    else:
        # Error paths do not depend on credentials or actually creating an account.
        flow = FeiNiuConfigFlow()
        flow.hass = hass
    error = (
        ValueError("PRIVATE_FAILURE_PAYLOAD")
        if reason == "invalid_output"
        else OutputValidationError(reason)
    )
    with patch("custom_components.feiniu_music.config_flow.select_outputs", side_effect=error):
        if options:
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], {"outputs": ["media_player.output"]}
            )
        else:
            result = await flow.async_step_outputs({"outputs": ["media_player.output"]})
    assert result["errors"] == {"base": reason}
    assert "PRIVATE_FAILURE_PAYLOAD" not in str(result) + caplog.text


def test_native_selector_uses_feature_filter_without_rejecting_saved_offline_ids():
    from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature

    from custom_components.feiniu_music.config_flow import output_schema

    schema = output_schema(["media_player.saved_offline"])
    selector = next(iter(schema.schema.values()))
    assert selector.config["multiple"] is True
    assert selector.config["filter"] == [
        {
            "domain": ["media_player"],
            "supported_features": [int(Feature.PLAY_MEDIA)],
        }
    ]
    # Filtering suggestions must not clear existing defaults, even without live states.
    assert schema({}) == {"outputs": ["media_player.saved_offline"]}
    assert schema({"outputs": ["media_player.saved_offline"]})["outputs"] == [
        "media_player.saved_offline"
    ]


async def test_login_debug_never_formats_credentials_or_exception_payload(hass, client, caplog):
    import logging

    from custom_components.feiniu_music.client import ProtocolError

    caplog.set_level(logging.DEBUG, logger="custom_components.feiniu_music")
    client.login.side_effect = ProtocolError("SECRET_PAYLOAD authSig=SECRET_COOKIE")
    flow = FeiNiuConfigFlow()
    flow.hass = hass
    with patch("custom_components.feiniu_music.config_flow.create_client", return_value=client):
        result = await flow.async_step_user(
            {
                "url": "http://secret-host.invalid:5666/music/",
                "username": "SECRET_ACCOUNT",
                "password": "SECRET_PASSWORD",
            }
        )
    assert result["errors"] == {"base": "invalid_response"}
    records = [r for r in caplog.records if r.name.startswith("custom_components.feiniu_music")]
    assert any("invalid_response" in r.getMessage() for r in records)
    assert "SECRET_" not in str([(r.msg, r.args, r.exc_info) for r in records])
    assert "secret-host" not in " ".join(r.getMessage() for r in records)


def test_output_error_translations_exist_in_both_languages_and_steps():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components/feiniu_music"
    source = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    for file in (root / "translations").glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        for section in ("config", "options"):
            assert data[section]["error"].keys() == source[section]["error"].keys()
            assert "PLAY_MEDIA" in data[section]["error"]["output_no_play_media"]
        assert ":5666/music/" in data["config"]["step"]["user"]["description"]


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
