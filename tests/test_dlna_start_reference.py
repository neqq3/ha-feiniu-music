"""Isolated reproduction against the installed HA, with no UPnP/network device attached."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from async_upnp_client.profiles.dlna import TransportState
from homeassistant.components.dlna_dmr.media_player import DlnaDmrEntity
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.parametrize("cached_state_refreshes", [False, True])
async def test_dlna_stop_set_uri_play_depends_on_cached_transport_state(
    hass, cached_state_refreshes
):
    """Only this isolated core test injects a device double; integration code never does."""
    calls = []
    device = SimpleNamespace(
        can_stop=True,
        transport_state=TransportState.PLAYING,
        profile_device=SimpleNamespace(available=True),
    )

    async def stop():
        calls.append("stop")
        if cached_state_refreshes:
            device.transport_state = TransportState.STOPPED

    async def set_uri(*args):
        calls.append("set_uri")

    async def play():
        calls.append("play")

    device.async_stop = AsyncMock(side_effect=stop)
    device.async_set_transport_uri = AsyncMock(side_effect=set_uri)
    device.async_play = AsyncMock(side_effect=play)
    device.construct_play_media_metadata = AsyncMock(return_value="synthetic metadata")
    device.async_wait_for_can_play = AsyncMock()
    entity = DlnaDmrEntity(
        "uuid:synthetic",
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "Synthetic",
        0,
        None,
        False,
        "http://output.invalid/description",
        None,
        False,
        MockConfigEntry(domain="dlna_dmr"),
    )
    entity.hass = hass
    entity._device = device
    await entity.async_play_media("audio/mpeg", "http://ha.invalid/synthetic.mp3")
    assert calls == (["stop", "set_uri", "play"] if cached_state_refreshes else ["stop", "set_uri"])
    if not cached_state_refreshes:
        # The ordinary HA media_play method is sufficient to request the missing Play;
        # whether a real device starts is a separate, explicitly unclaimed observation.
        await entity.async_media_play()
        assert calls == ["stop", "set_uri", "play"]
