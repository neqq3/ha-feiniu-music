"""Native account diagnostics, built from allowlisted operational fields only."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .output import OutputBinding, output_info
from .runtime import FeiNiuConfigEntry
from .support import private_id, safe_address


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FeiNiuConfigEntry) -> dict:
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("players", {}).get(entry.entry_id)
    runtime = getattr(entry, "runtime_data", None)
    integration = await async_get_integration(hass, DOMAIN)
    sessions = []
    invalid_bindings = 0
    # Configured outputs remain visible even if their registry/proxy/runtime is missing.
    for saved in entry.options.get("outputs", []):
        try:
            binding = OutputBinding.restore(saved)
        except ValueError:
            invalid_bindings += 1
            continue
        player = manager.entities.get(binding.key) if manager else None
        session = player.session if player else None
        sessions.append(
            {
                **output_info(hass, binding),
                "saved_entity_id": binding.entity_id,
                "resolved_entity_id": binding.resolve(hass),
                "player_created": player is not None,
                "session": session.diagnostics() if session else {"phase": "not_initialized"},
            }
        )
    return async_redact_data(
        {
            "integration_version": str(integration.version) if integration.version else None,
            "ha_version": HA_VERSION,
            "entry": {
                "ref": private_id(entry.entry_id),
                "state": entry.state.value,
                "version": entry.version,
                "minor_version": entry.minor_version,
            },
            "server": safe_address(entry.data.get(CONF_URL, "")),
            "runtime": {
                "initialized": runtime is not None,
                "registered": entry.entry_id in domain_data.get("entries", {}),
                "closed": runtime.closed if runtime else None,
                "client_ref": runtime.client.debug_ref if runtime else None,
                "generation": runtime.generation if runtime else None,
                "active_audio_rounds": len(runtime.audio_rounds) if runtime else 0,
                "active_stream_requests": sum(
                    len(route.tasks) for route in runtime.audio_rounds.values()
                )
                if runtime
                else 0,
            },
            "players_initialized": manager is not None,
            "players_closed": manager.closed if manager else None,
            "queue_storage_corrupt": manager.storage.corrupt if manager else None,
            "invalid_bindings": invalid_bindings,
            "sessions": sessions,
        },
        {"saved_entity_id", "resolved_entity_id"},
    )
