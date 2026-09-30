"""Bundled card installation through HA's real resource storage and HTTP route."""

from hashlib import sha256
from unittest.mock import patch

import pytest
from homeassistant.components.lovelace import const as lovelace_const
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.frontend import CARD_FILE, CARD_URL, async_register_card

# HA renamed this YAML setting after 2025.12; exercise each installed HA's real schema.
RESOURCE_MODE_KEY = getattr(lovelace_const, "CONF_RESOURCE_MODE", "mode")


def card_resources(hass):
    return [
        item
        for item in hass.data[LOVELACE_DATA].resources.async_items()
        if item["url"].split("?", 1)[0] == CARD_URL
    ]


async def test_fresh_install_registers_served_bundle_without_manual_resource(hass, hass_client):
    assert await async_setup_component(hass, DOMAIN, {})
    (resource,) = card_resources(hass)
    assert resource["type"] == "module"
    client = await hass_client()
    response = await client.get(resource["url"])
    assert response.status == 200
    bundle = await response.read()
    assert bundle == await hass.async_add_executor_job(CARD_FILE.read_bytes)
    assert resource["url"] == f"{CARD_URL}?v={sha256(bundle).hexdigest()[:16]}"


async def test_new_bundle_updates_saved_resource_in_place(hass, hass_storage):
    unrelated = {"id": "other", "url": "/local/another-card.js", "type": "module"}
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "data": {
            "items": [
                {"id": "feiniu", "url": f"{CARD_URL}?v=previous-build", "type": "module"},
                unrelated,
            ]
        },
    }
    assert await async_setup_component(hass, DOMAIN, {})
    (resource,) = card_resources(hass)
    assert resource["id"] == "feiniu"
    assert resource["url"] != f"{CARD_URL}?v=previous-build"
    assert unrelated in hass.data[LOVELACE_DATA].resources.async_items()

    # Exercise a second release, without relying on a separately maintained version.
    with patch("custom_components.feiniu_music.frontend._card_version", return_value="new-build"):
        await async_register_card(hass)
    (resource,) = card_resources(hass)
    assert resource == {"id": "feiniu", "url": f"{CARD_URL}?v=new-build", "type": "module"}


async def test_unchanged_bundle_does_not_rewrite_or_duplicate_resource(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    resources = hass.data[LOVELACE_DATA].resources
    before = resources.async_items()
    with (
        patch.object(resources, "async_create_item", wraps=resources.async_create_item) as create,
        patch.object(resources, "async_update_item", wraps=resources.async_update_item) as update,
    ):
        await async_register_card(hass)
        await async_register_card(hass)
    create.assert_not_called()
    update.assert_not_called()
    assert resources.async_items() == before


async def test_multiple_accounts_and_reload_share_one_card(hass, entry, client):
    second = MockConfigEntry(domain=DOMAIN, title="Second music account", data=dict(entry.data))
    entry.add_to_hass(hass)
    second.add_to_hass(hass)
    with patch("custom_components.feiniu_music.create_client", return_value=client):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        assert len(hass.data[DOMAIN]["entries"]) == 2
        before = card_resources(hass)
        assert len(before) == 1
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert card_resources(hass) == before
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert card_resources(hass) == before
        assert await hass.config_entries.async_unload(second.entry_id)


async def test_yaml_resource_mode_is_not_modified(hass):
    configured = [{"url": "/local/user-owned.js", "type": "module"}]
    assert await async_setup_component(
        hass, DOMAIN, {"lovelace": {RESOURCE_MODE_KEY: "yaml", "resources": configured}}
    )
    assert hass.data[LOVELACE_DATA].resources.async_items() == configured
    assert hass.services.has_service(DOMAIN, "get_lyrics")


async def test_yaml_dashboard_with_storage_resources_still_registers(hass):
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            "lovelace": {
                RESOURCE_MODE_KEY: "storage",
                "dashboards": {
                    "music-page": {"mode": "yaml", "filename": "music.yaml", "title": "Music"}
                },
            }
        },
    )
    assert len(card_resources(hass)) == 1
    assert "music-page" in hass.data[LOVELACE_DATA].dashboards


@pytest.mark.parametrize(
    ("target", "error"),
    [
        (
            "homeassistant.components.lovelace.resources.ResourceStorageCollection.async_create_item",
            HomeAssistantError("Store unavailable"),
        ),
        ("custom_components.feiniu_music.frontend._card_version", OSError("Read failed")),
    ],
)
async def test_resource_failure_does_not_block_backend(hass, caplog, target, error):
    with patch(target, side_effect=error):
        assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "get_lyrics")
    assert "Could not register the FeiNiu Music card resource" in caplog.text
