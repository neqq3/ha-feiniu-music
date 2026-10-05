"""Authenticated, bounded queue and lyric snapshots for the optional HA card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .client import FeiNiuError
from .const import DOMAIN
from .media import thumbnail
from .media_player import FeiNiuPlayer
from .queue import QueueError, RevisionConflict


def player_for(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    entity_id: str,
    *,
    control: bool = False,
) -> FeiNiuPlayer:
    """Registry/model IDs in a request cannot grant access to another account's entity."""
    policy = POLICY_CONTROL if control else POLICY_READ
    if not connection.user.permissions.check_entity(entity_id, policy):
        raise Unauthorized(entity_id=entity_id)
    for manager in hass.data[DOMAIN].get("players", {}).values():
        for player in manager.entities.values():
            if player.entity_id == entity_id and player.session and not player.session.closed:
                if (
                    control
                    and player.output.entity_id
                    and not connection.user.permissions.check_entity(
                        player.output.entity_id, POLICY_CONTROL
                    )
                ):
                    raise Unauthorized(entity_id=player.output.entity_id)
                return player
    raise HomeAssistantError("Queue player is unavailable")


def failure(connection: websocket_api.ActiveConnection, msg: dict, err: Exception) -> None:
    if isinstance(err, Unauthorized):
        code = "unauthorized"
    elif isinstance(err, RevisionConflict):
        code = "revision_conflict"
    else:
        code = "queue_unavailable"
    # Exception text from network/device services is not part of this API.
    connection.send_error(msg["id"], code, type(err).__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "feiniu_music/queue",
        vol.Required("entity_id"): str,
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=25): vol.All(int, vol.Range(min=1, max=100)),
        vol.Optional("revision"): int,
    }
)
@websocket_api.async_response
async def get_queue(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    try:
        player = player_for(hass, connection, msg["entity_id"])
        queue = player.control.queue
        revision = queue.revision
        if "revision" in msg:
            queue.check_revision(msg["revision"])
        keys = queue.order[msg["offset"] : msg["offset"] + msg["limit"]]
        records = []
        for key in keys:
            item = queue.items[key]
            record: dict[str, Any] = {
                "item_id": key,
                "track_id": item.track_id,
                "current": key == queue.current_id,
            }
            try:
                row = await player.runtime.display_track(item.track_id)
                record.update(
                    title=row.get("title") or "Untitled track",
                    artist=" / ".join(
                        a["name"]
                        for a in row.get("artists", [])
                        if isinstance(a, dict) and isinstance(a.get("name"), str)
                    ),
                    thumbnail=thumbnail(player.runtime, "track", row),
                    available=True,
                )
            except FeiNiuError as err:
                record.update(title="Unavailable track", available=False, reason=type(err).__name__)
            queue.check_revision(revision)
            records.append(record)
        connection.send_result(
            msg["id"],
            {
                "revision": revision,
                "offset": msg["offset"],
                "total": len(queue.order),
                "current_id": queue.current_id,
                "position": queue.position,
                "items": records,
                "diagnostics": player.control.diagnostics(),
            },
        )
    except (HomeAssistantError, FeiNiuError, QueueError) as err:
        failure(connection, msg, err)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "feiniu_music/edit_queue",
        vol.Required("entity_id"): str,
        vol.Required("action"): vol.In(["jump", "move", "remove", "clear"]),
        vol.Required("revision"): int,
        vol.Optional("item_id"): str,
        vol.Optional("before_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def edit_queue(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    try:
        player = player_for(hass, connection, msg["entity_id"], control=True)
        player.async_set_context(connection.context(msg))
        await player.edit_queue(
            msg["action"], msg["revision"], msg.get("item_id"), msg.get("before_id")
        )
        connection.send_result(msg["id"], {"revision": player.control.queue.revision})
    except (HomeAssistantError, FeiNiuError, QueueError) as err:
        failure(connection, msg, err)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "feiniu_music/lyrics",
        vol.Required("entity_id"): str,
        vol.Required("round"): int,
        vol.Required("item_id"): str,
    }
)
@websocket_api.async_response
async def get_lyrics(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    try:
        player = player_for(hass, connection, msg["entity_id"])
        session = player.control
        item = session.queue.current
        if not item or item.item_id != msg["item_id"] or session.round_id != msg["round"]:
            raise RevisionConflict("Track changed")
        result = await player.runtime.lyrics(item.track_id)
        if (
            session.closed
            or item.item_id != session.queue.current_id
            or session.round_id != msg["round"]
        ):
            raise RevisionConflict("Track changed")
        connection.send_result(
            msg["id"], {**result, "round": msg["round"], "item_id": item.item_id}
        )
    except (HomeAssistantError, FeiNiuError, QueueError) as err:
        failure(connection, msg, err)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "feiniu_music/preferences",
        vol.Required("entity_id"): str,
        vol.Optional("lyric_offset"): vol.All(vol.Coerce(float), vol.Range(min=-30, max=30)),
        vol.Optional("profile"): {
            vol.Optional("feedback_mode"): vol.In(["standard", "compatibility"]),
            vol.Optional("unconfirmed_end"): vol.In(
                ["manual", "estimated_duration", "duration_fallback"]
            ),
            vol.Optional("confirmation"): vol.In(["delivery", "reported"]),
            vol.Optional("play_once"): bool,
            vol.Optional("end_state"): vol.In(["idle", "paused", "off"]),
            vol.Optional("weak_end"): bool,
        },
    }
)
@websocket_api.async_response
async def preferences(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    try:
        player = player_for(hass, connection, msg["entity_id"], control=True)
        if "profile" in msg:
            if not connection.user.is_admin:
                raise Unauthorized
            player.set_playback_profile(msg["profile"])
        if "lyric_offset" in msg:
            player.saved.lyric_offset = msg["lyric_offset"]
        player._changed()
        connection.send_result(msg["id"], {"saved": True})
    except (HomeAssistantError, ValueError) as err:
        failure(connection, msg, err)


@callback
def register(hass: HomeAssistant) -> None:
    for command in (get_queue, edit_queue, get_lyrics, preferences):
        websocket_api.async_register_command(hass, command)
