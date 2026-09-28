"""Make the bundled card available in the dashboard card picker."""

import logging
from hashlib import sha256
from pathlib import Path

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

CARD_URL = "/feiniu_music/feiniu-music-card.js"
CARD_FILE = Path(__file__).parent / "www" / "feiniu-music-card.js"

_LOGGER = logging.getLogger(__name__)


def _card_version() -> str:
    """Change the browser cache key whenever the shipped card changes."""
    return sha256(CARD_FILE.read_bytes()).hexdigest()[:16]


async def async_register_card(hass: HomeAssistant) -> None:
    """Register once globally; keep dashboard placement and YAML user-managed."""
    resources = hass.data[LOVELACE_DATA].resources
    if not isinstance(resources, ResourceStorageCollection):
        _LOGGER.info("YAML dashboard resources: add %s as a JavaScript module", CARD_URL)
        return

    try:
        version = await hass.async_add_executor_job(_card_version)
        url = f"{CARD_URL}?v={version}"
        # Resource storage is loaded lazily, including on the first HA startup.
        await resources.async_get_info()
        for resource in resources.async_items():
            if resource["url"].split("?", 1)[0] == CARD_URL:
                if resource["url"] != url or resource["type"] != "module":
                    await resources.async_update_item(
                        resource["id"], {"url": url, "res_type": "module"}
                    )
                return
        await resources.async_create_item({"url": url, "res_type": "module"})
    except HomeAssistantError, OSError:
        # The optional card must not prevent media browsing or audio playback.
        _LOGGER.exception("Could not register the FeiNiu Music card resource %s", CARD_URL)
