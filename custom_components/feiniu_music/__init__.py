"""Native, read-only FeiNiu Music media source for Home Assistant."""

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError

from .api import create_client
from .client import AuthenticationError, FeiNiuError, NetworkError, ProtocolError, RateLimitError
from .const import DOMAIN
from .http import FeiNiuArtworkView, FeiNiuAudioView, FeiNiuImageView
from .lyrics import parse_lyrics
from .media import valid_id
from .runtime import FeiNiuConfigEntry, FeiNiuRuntime


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register HA-owned HTTP resources and a read-only lyric action once."""
    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.http.register_view(FeiNiuAudioView(hass))
    hass.http.register_view(FeiNiuImageView(hass))
    hass.http.register_view(FeiNiuArtworkView(hass))

    async def lyrics(call: ServiceCall) -> dict:
        runtime = hass.data[DOMAIN]["entries"].get(call.data["entry_id"])
        if runtime is None:
            raise HomeAssistantError("Music source is unavailable")
        try:
            guid = valid_id(call.data["track_id"])
            await runtime.detail("track", guid)
            return parse_lyrics(await runtime.call(lambda: runtime.client.lyrics(guid)))
        except FeiNiuError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        "get_lyrics",
        lyrics,
        schema=vol.Schema({vol.Required("entry_id"): str, vol.Required("track_id"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FeiNiuConfigEntry) -> bool:
    """Authenticate a music account and expose it to the shared media source."""
    client = create_client(hass, entry.data[CONF_URL])
    await client.__aenter__()
    runtime = FeiNiuRuntime(hass, entry, client)
    try:
        await runtime.login()
    except AuthenticationError as err:
        await runtime.close()
        raise ConfigEntryAuthFailed("Music account login failed") from err
    except (NetworkError, RateLimitError, ProtocolError) as err:
        await runtime.close()
        raise ConfigEntryNotReady(str(err)) from err
    except BaseException:
        await runtime.close()
        raise
    entry.runtime_data = runtime
    hass.data[DOMAIN]["entries"][entry.entry_id] = runtime
    try:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.MEDIA_PLAYER])
    except BaseException:
        hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
        await runtime.close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[FeiNiuRuntime]) -> bool:
    """Close only this account; invalidate its signed paths without logging out others."""
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.MEDIA_PLAYER]):
        return False
    runtime = hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    if runtime:
        await runtime.close()
    return True
