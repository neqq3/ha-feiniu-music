"""Native diagnostics retain failures and operational evidence, never account/content data."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.diagnostics import REDACTED
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.helpers import entity_registry as er

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.diagnostics import async_get_config_entry_diagnostics
from custom_components.feiniu_music.output import OutputAdapter, OutputBinding, OutputLeases
from custom_components.feiniu_music.queue import QueueItem
from custom_components.feiniu_music.runtime import normalize_url
from custom_components.feiniu_music.session import PlaybackSession
from custom_components.feiniu_music.support import private_id, safe_address


@pytest.mark.parametrize(
    "case",
    [
        "capable",
        "unsupported",
        "offline",
        "unknown",
        "missing_state",
        "missing_registry",
        "disabled",
        "renamed",
    ],
)
async def test_diagnostics_covers_configured_outputs_without_runtime(hass, entry, case):
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registered = registry.async_get_or_create(
        "media_player", "synthetic", "SECRET_DEVICE_ID", suggested_object_id="secret_speaker"
    )
    binding = OutputBinding.from_entity(hass, registered.entity_id)
    flags = Feature.PLAY_MEDIA | Feature.PAUSE | Feature.SEEK | Feature.PLAY | Feature.VOLUME_SET
    if case == "unsupported":
        flags = Feature.PAUSE
    if case == "renamed":
        registered = registry.async_update_entity(
            registered.entity_id, new_entity_id="media_player.secret_new_name"
        )
    hass.states.async_set(
        registered.entity_id,
        {"offline": "unavailable", "unknown": "unknown"}.get(case, "idle"),
        {"supported_features": flags, "device_class": "speaker", "xiaoai_id": "SECRET_XIAOAI"},
    )
    if case in {"missing_state", "missing_registry", "disabled"}:
        hass.states.async_remove(registered.entity_id)
    if case == "missing_registry":
        registry.async_remove(registered.entity_id)
    if case == "disabled":
        registry.async_update_entity(
            registered.entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )
    hass.config_entries.async_update_entry(entry, options={"outputs": [binding.snapshot()]})
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert not result["runtime"]["initialized"] and not result["players_initialized"]
    (output,) = result["sessions"]
    assert output["registry_exists"] is (case != "missing_registry")
    assert output["resolved"] is (case != "missing_registry")
    assert output["registry_disabled"] is (
        True if case == "disabled" else None if case == "missing_registry" else False
    )
    assert output["renamed"] is (case == "renamed")
    assert output["available"] is (case in {"capable", "unsupported", "renamed"})
    assert output["features"]["PLAY_MEDIA"] is (
        case in {"capable", "offline", "unknown", "renamed"}
    )
    assert output["saved_entity_id"] == REDACTED
    assert output["session"]["phase"] == "not_initialized"
    assert output["binding_ref"] == private_id(binding.key)
    assert "secret_" not in json.dumps(result)
    assert "SECRET_" not in json.dumps(result)


async def test_diagnostics_redacts_credentials_urls_metadata_and_bounded_history(
    hass, runtime, entry
):
    sentinel = "PRIVATE_SENTINEL"
    signed = f"https://{sentinel}.invalid/audio?authSig={sentinel}"
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "url": f"https://{sentinel}:{sentinel}@{sentinel}.invalid:5666/music/?authSig={sentinel}#{sentinel}",
            "password": sentinel,
            "username": sentinel,
            "account_id": sentinel,
            "device_id": sentinel,
            "cookie": sentinel,
            "token": sentinel,
            "Authorization": sentinel,
        },
    )
    entity_id = "media_player.private_sentinel"
    hass.states.async_set(
        entity_id,
        sentinel,
        {
            "supported_features": Feature.PLAY_MEDIA,
            "media_content_id": signed,
            "device_class": {"private": sentinel},
            "lyrics": sentinel,
            "MAC": sentinel,
            "DID": sentinel,
        },
    )
    binding = OutputBinding.from_entity(hass, entity_id)
    session = PlaybackSession(
        hass, OutputAdapter(hass, binding), OutputLeases(), AsyncMock(), Mock()
    )
    session.queue.replace([QueueItem.create(sentinel)])
    session._expected = signed
    session.identity = sentinel  # Defensive classification, not raw media identity.
    for _ in range(50):
        session.record("stream", "head")
    session.stream_counts = {"head": 50, "get": 0}
    runtime.client._token = sentinel
    runtime.scope = sentinel
    runtime._lyrics[sentinel] = (0, {"lyrics": sentinel})
    hass.data[DOMAIN]["players"] = {
        entry.entry_id: SimpleNamespace(
            entities={binding.key: SimpleNamespace(session=session)},
            closed=False,
            storage=SimpleNamespace(corrupt=False),
        )
    }
    hass.config_entries.async_update_entry(entry, options={"outputs": [binding.snapshot()]})
    try:
        result = await async_get_config_entry_diagnostics(hass, entry)
        encoded = json.dumps(result)
        for secret in (
            sentinel,
            entity_id,
            signed,
            "authSig",
            "cookie",
            "Authorization",
            "password",
            entry.entry_id,
        ):
            assert secret not in encoded
        assert result["server"]["host"] == REDACTED
        assert result["server"]["port"] == 5666
        assert result["server"]["path"] == "/music/"
        details = result["sessions"][0]["session"]
        assert len(details["events"]) == 32
        assert details["stream_events"] == {"head": 50, "get": 0}
        assert details["queue_length"] == 1 and details["queue_position"] == 0
        assert details["output_state"] == "other" and details["identity"] == "unknown"
        assert not details["has_duration"] and not details["has_position"]
        assert result["sessions"][0]["device_class"] == "other"
        await session.close()
        runtime.closed = True
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["runtime"]["closed"] and result["sessions"][0]["session"]["closed"]
    finally:
        await session.close()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://music.invalid:5666/music/", "http://music.invalid:5666/music/"),
        ("http://music.invalid:9876/music", "http://music.invalid:9876/music/"),
        ("https://proxy.invalid/music/", "https://proxy.invalid/music/"),
        ("https://proxy.invalid", "https://proxy.invalid/music/"),
        ("http://music.invalid:5666/", "http://music.invalid:5666/music/"),
        ("http://music.invalid", "http://music.invalid/music/"),
        ("https://proxy.invalid:9443", "https://proxy.invalid:9443/music/"),
    ],
)
def test_url_guidance_does_not_rewrite_valid_ports_or_proxy_origins(url, expected):
    assert normalize_url(url) == expected


def test_safe_address_excludes_userinfo_query_fragment_and_custom_path():
    result = safe_address("https://SECRET:SECRET@secret.invalid:8443/SECRET?token=SECRET#SECRET")
    assert result["scheme"] == "https" and result["port"] == 8443
    assert result["host"] == result["path"] == REDACTED
    assert "secret" not in str(result).lower()
    assert safe_address("http://invalid:SECRET") == {"valid": False}
    assert private_id("one") == private_id("one") != private_id("two")
