"""Two-step profile edits against changing state, without a running HA instance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.feiniu_music.config_flow import FeiNiuOptionsFlow
from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.media_player import FeiNiuPlayer
from custom_components.feiniu_music.output import OutputBinding, OutputLeases
from custom_components.feiniu_music.queue import QueueModel
from custom_components.feiniu_music.session import OutputProfile
from custom_components.feiniu_music.storage import SavedSession


@pytest.fixture
def options():
    entry = SimpleNamespace(entry_id="synthetic", title="Synthetic", options={})
    runtime = SimpleNamespace(hass=None, entry=entry)
    saved = SavedSession(
        OutputBinding("entity:media_player.synthetic", "media_player.synthetic"),
        QueueModel(),
        OutputProfile(),
    )
    player = FeiNiuPlayer(runtime, saved, OutputLeases(), Mock())
    player.entity_id = "media_player.feiniu_synthetic"
    player.output = SimpleNamespace(state=None)
    player.session = SimpleNamespace(profile=OutputProfile(), closed=False)
    player._changed = Mock()
    manager = SimpleNamespace(
        closed=False,
        entities={saved.binding.key: player},
        storage=SimpleNamespace(corrupt=False, flush=AsyncMock()),
    )
    flow = FeiNiuOptionsFlow()
    flow.handler = entry.entry_id
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry),
        data={DOMAIN: {"players": {entry.entry_id: manager}}},
    )
    flow._output_key = saved.binding.key
    return flow, player, manager.storage


@pytest.mark.parametrize(
    "external",
    [{"unconfirmed_end": "estimated_duration"}, {"feedback_mode": "standard"}],
)
async def test_second_step_preserves_unedited_concurrent_strategies(options, external):
    flow, player, storage = options
    player.set_playback_profile({"feedback_mode": "compatibility"})
    first = await flow.async_step_playback_profile()
    second = await flow.async_step_playback_profile(first["data_schema"]({}))
    original_toggle = second["data_schema"]({})
    player.set_playback_profile(external)
    expected = player.control.profile
    result = await flow.async_step_unconfirmed_end(original_toggle)
    assert result["type"] == "create_entry"
    assert player.control.profile == expected
    storage.flush.assert_awaited_once()


async def test_second_step_baseline_is_the_value_shown_on_entering_that_step(options):
    flow, player, _ = options
    player.set_playback_profile({"feedback_mode": "compatibility"})
    first = await flow.async_step_playback_profile()
    player.set_playback_profile({"unconfirmed_end": "estimated_duration"})
    second = await flow.async_step_playback_profile(first["data_schema"]({}))
    assert second["data_schema"]({}) == {"estimated": True}
    result = await flow.async_step_unconfirmed_end({"estimated": False})
    assert result["type"] == "create_entry"
    assert player.control.profile.unconfirmed_end == "manual"


async def test_explicit_first_step_mode_edit_is_pending_until_second_step_save(options):
    flow, player, storage = options
    original = player.control.profile
    first = await flow.async_step_playback_profile()
    second = await flow.async_step_playback_profile(
        {**first["data_schema"]({}), "feedback_mode": "compatibility", "play_once": True}
    )
    assert second["step_id"] == "unconfirmed_end"
    assert player.control.profile == original  # Abandoning this form writes nothing.
    storage.flush.assert_not_awaited()
    result = await flow.async_step_unconfirmed_end({"estimated": True})
    assert result["type"] == "create_entry"
    assert player.control.profile == OutputProfile(
        feedback_mode="compatibility", unconfirmed_end="estimated_duration", play_once=True
    )


@pytest.mark.parametrize("conflict", ["same_field", "strategy_combination"])
async def test_second_step_conflict_requires_reopening_without_partial_save(options, conflict):
    flow, player, storage = options
    player.set_playback_profile({"feedback_mode": "compatibility"})
    first = await flow.async_step_playback_profile()
    await flow.async_step_playback_profile(
        {**first["data_schema"]({}), "end_state": "paused", "play_once": True}
    )
    player.set_playback_profile(
        {"end_state": "off"} if conflict == "same_field" else {"feedback_mode": "standard"}
    )
    expected = player.control.profile
    result = await flow.async_step_unconfirmed_end({"estimated": True})
    assert result["type"] == "form" and result["errors"] == {"base": "profile_changed"}
    assert result["data_schema"]({}) == {"estimated": True}
    assert player.control.profile == expected
    storage.flush.assert_not_awaited()


async def test_second_step_same_concurrent_value_is_not_a_conflict(options):
    flow, player, storage = options
    player.set_playback_profile({"feedback_mode": "compatibility"})
    first = await flow.async_step_playback_profile()
    await flow.async_step_playback_profile({**first["data_schema"]({}), "end_state": "off"})
    player.set_playback_profile({"end_state": "off", "unconfirmed_end": "estimated_duration"})
    result = await flow.async_step_unconfirmed_end({"estimated": True})
    assert result["type"] == "create_entry"
    assert player.control.profile.end_state == "off"
    assert player.control.profile.unconfirmed_end == "estimated_duration"
    storage.flush.assert_awaited_once()
