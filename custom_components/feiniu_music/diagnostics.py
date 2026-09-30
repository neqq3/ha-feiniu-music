"""Redacted account diagnostics. No content, URLs, credentials, or raw responses."""

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .runtime import FeiNiuConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FeiNiuConfigEntry) -> dict:
    manager = hass.data[DOMAIN].get("players", {}).get(entry.entry_id)
    sessions = []
    if manager:
        registry = er.async_get(hass)
        for player in manager.entities.values():
            registered = (
                registry.async_get(player.output.entity_id) if player.output.entity_id else None
            )
            sessions.append(
                {
                    "binding": "registry"
                    if player.saved.binding.key.startswith("registry:")
                    else "entity_id",
                    "output_platform": registered.platform if registered else "unregistered",
                    "output_available": player.output.available,
                    "session": player.control.diagnostics()
                    if player.session and not player.session.closed
                    else {"phase": "disabled"},
                }
            )
    return {
        "integration_version": "1.0.1",
        "ha_version": HA_VERSION,
        "queue_storage_corrupt": manager.storage.corrupt if manager else None,
        "sessions": sessions,
    }
