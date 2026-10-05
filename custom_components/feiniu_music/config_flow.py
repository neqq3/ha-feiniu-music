"""Configure a regular music account, without NAS administrator access."""

import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import create_client
from .client import AuthenticationError, FeiNiuError, NetworkError, RateLimitError
from .const import CONF_ACCOUNT_ID, CONF_DEVICE_ID, DOMAIN
from .output import OutputBinding, OutputValidationError, validate_output
from .players import CONF_OUTPUTS, AccountPlayers, bindings
from .runtime import normalize_url
from .support import safe_address

_LOGGER = logging.getLogger(__name__)


class FeiNiuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Manage independent music entries and password-only reconfiguration."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self._device_id = uuid4().hex
        self._account_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up an account without storing a failed login or echoing its password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
                _LOGGER.debug("Config login begin address=%s", safe_address(url))
                username = user_input[CONF_USERNAME].strip()
                if not username or not user_input[CONF_PASSWORD]:
                    raise ValueError("Missing credentials")
                self._async_abort_entries_match({CONF_URL: url, CONF_USERNAME: username})
                data = {
                    CONF_URL: url,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_DEVICE_ID: self._device_id,
                }
                async with create_client(self.hass, url) as client:
                    user = await client.login(username, data[CONF_PASSWORD], self._device_id)
                if not isinstance(user.get("guid"), str) or not user["guid"]:
                    _LOGGER.debug("Config login rejected stage=account_identity")
                    errors["base"] = "invalid_response"
                else:
                    data[CONF_ACCOUNT_ID] = user["guid"]
                    self._account_data = data
                    _LOGGER.debug("Config login complete")
                    return await self.async_step_outputs()
            except ValueError:
                errors["base"] = "invalid_input"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (NetworkError, RateLimitError):
                errors["base"] = "cannot_connect"
            except FeiNiuError:
                errors["base"] = "invalid_response"
            _LOGGER.debug("Config login result=%s", errors.get("base", "unknown"))
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FeiNiuOptionsFlow()

    async def async_step_outputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                selected = select_outputs(self.hass, user_input.get(CONF_OUTPUTS, []), {})
                return self.async_create_entry(
                    title=f"FeiNiu Music — {self._account_data[CONF_USERNAME]}",
                    data=self._account_data,
                    options={CONF_OUTPUTS: selected},
                )
            except OutputValidationError as err:
                errors["base"] = err.reason
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.debug(
                    "Output validation reason=invalid_output category=%s", type(err).__name__
                )
                errors["base"] = "invalid_output"
        return self.async_show_form(step_id="outputs", errors=errors, data_schema=output_schema([]))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start HA's normal password recovery flow for an existing source."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update credentials for the same account."""
        return await self._password_step("reauth_confirm", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Keep server/account identity fixed; an empty password keeps the saved value."""
        return await self._password_step("reconfigure", user_input)

    async def _password_step(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = (
            self._get_reauth_entry() if step == "reauth_confirm" else self._get_reconfigure_entry()
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if (
                    normalize_url(user_input.get(CONF_URL, entry.data[CONF_URL]))
                    != entry.data[CONF_URL]
                    or user_input.get(CONF_USERNAME, entry.data[CONF_USERNAME]).strip()
                    != entry.data[CONF_USERNAME]
                ):
                    return self.async_abort(reason="identity_change")
                password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
                _LOGGER.debug(
                    "Config password login begin address=%s", safe_address(entry.data[CONF_URL])
                )
                async with create_client(self.hass, entry.data[CONF_URL]) as client:
                    user = await client.login(
                        entry.data[CONF_USERNAME], password, entry.data[CONF_DEVICE_ID]
                    )
                if user.get("guid") != entry.data[CONF_ACCOUNT_ID]:
                    _LOGGER.debug("Config password login rejected stage=account_identity")
                    return self.async_abort(reason="identity_change")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )
            except ValueError:
                return self.async_abort(reason="identity_change")
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (NetworkError, RateLimitError):
                errors["base"] = "cannot_connect"
            except FeiNiuError:
                errors["base"] = "invalid_response"
            _LOGGER.debug("Config password login result=%s", errors.get("base", "unknown"))
        return self.async_show_form(
            step_id=step,
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
        )


def output_schema(selected: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_OUTPUTS, default=selected): EntitySelector(
                EntitySelectorConfig(
                    filter={
                        "domain": "media_player",
                        "supported_features": ["media_player.MediaPlayerEntityFeature.PLAY_MEDIA"],
                    },
                    multiple=True,
                )
            )
        }
    )


def select_outputs(hass, entities: list[str], options: dict) -> list[dict[str, str]]:
    existing = bindings(options)
    result = {}
    for entity_id in entities:
        prior = next(
            (
                item
                for item in existing.values()
                if entity_id in {item.entity_id, item.resolve(hass)}
            ),
            None,
        )
        binding = prior or OutputBinding.from_entity(hass, entity_id)
        validate_output(hass, binding, existing=prior is not None)
        result[binding.key] = binding.snapshot()
    return list(result.values())


class FeiNiuOptionsFlow(config_entries.OptionsFlow):
    """Manage outputs and their saved playback profiles without reloading the account."""

    def __init__(self) -> None:
        super().__init__()
        self._output_key: str | None = None
        self._profile_defaults: dict[str, Any] = {}
        self._profile_pending: dict[str, Any] = {}
        self._unconfirmed_default = "manual"

    def _manager(self) -> AccountPlayers | None:
        manager = self.hass.data.get(DOMAIN, {}).get("players", {}).get(self.config_entry.entry_id)
        return manager if manager and not manager.closed else None

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["outputs", "playback"])

    async def async_step_outputs(self, user_input=None) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        errors = {}
        if user_input is not None:
            try:
                selected = select_outputs(self.hass, user_input.get(CONF_OUTPUTS, []), options)
                return self.async_create_entry(title="", data={**options, CONF_OUTPUTS: selected})
            except OutputValidationError as err:
                errors["base"] = err.reason
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.debug(
                    "Output validation reason=invalid_output category=%s", type(err).__name__
                )
                errors["base"] = "invalid_output"
        selected_ids = [
            item.resolve(self.hass) or item.entity_id for item in bindings(options).values()
        ]
        return self.async_show_form(
            step_id="outputs", errors=errors, data_schema=output_schema(selected_ids)
        )

    async def async_step_playback(self, user_input=None) -> ConfigFlowResult:
        """Select only proxies belonging to this account, including offline outputs."""
        manager = self._manager()
        if manager is None:
            return self.async_abort(reason="not_loaded")
        if not manager.entities:
            return self.async_abort(reason="no_outputs")
        if user_input is not None:
            key = user_input.get("output")
            if key not in manager.entities:
                return self.async_abort(reason="output_removed")
            self._output_key = key
            return await self.async_step_playback_profile()
        choices: list[SelectOptionDict] = [
            {"value": key, "label": f"{player.name} ({player.entity_id})"}
            for key, player in manager.entities.items()
        ]
        return self.async_show_form(
            step_id="playback",
            data_schema=vol.Schema(
                {
                    vol.Required("output"): SelectSelector(
                        SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    async def async_step_playback_profile(self, user_input=None) -> ConfigFlowResult:
        """Edit the existing saved session, never a duplicate set of config-entry options."""
        manager = self._manager()
        if manager is None:
            return self.async_abort(reason="not_loaded")
        player = manager.entities.get(self._output_key or "")
        if player is None or player.session is None or player.session.closed:
            return self.async_abort(reason="output_removed")
        if manager.storage.corrupt:
            return self.async_abort(reason="storage_unavailable")
        errors = {}
        if user_input is not None:
            try:
                # Preserve fields changed elsewhere while this form was open.
                changes = {k: v for k, v in user_input.items() if v != self._profile_defaults[k]}
                if (
                    user_input.get("feedback_mode", self._profile_defaults["feedback_mode"])
                    == "compatibility"
                ):
                    self._profile_pending = changes
                    return await self.async_step_unconfirmed_end()
                if changes.get("feedback_mode") == "standard":
                    changes["unconfirmed_end"] = "manual"
                player.set_playback_profile(changes)
                await manager.storage.flush()
                return self.async_create_entry(title="", data=dict(self.config_entry.options))
            except ValueError:
                errors["base"] = "invalid_profile"
        else:
            self._profile_defaults = asdict(player.control.profile)
        defaults = user_input or self._profile_defaults
        return self.async_show_form(
            step_id="playback_profile",
            description_placeholders={"player": player.name, "entity_id": player.entity_id},
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "feedback_mode", default=defaults["feedback_mode"]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["standard", "compatibility"],
                            translation_key="feedback_mode",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("confirmation", default=defaults["confirmation"]): SelectSelector(
                        SelectSelectorConfig(
                            options=["delivery", "reported"],
                            translation_key="confirmation",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("end_state", default=defaults["end_state"]): SelectSelector(
                        SelectSelectorConfig(
                            options=["idle", "paused", "off"],
                            translation_key="end_state",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("play_once", default=defaults["play_once"]): BooleanSelector(),
                    vol.Required("weak_end", default=defaults["weak_end"]): BooleanSelector(),
                }
            ),
        )

    async def async_step_unconfirmed_end(self, user_input=None) -> ConfigFlowResult:
        """Only offered after choosing compatibility; save both steps together."""
        manager = self._manager()
        if manager is None:
            return self.async_abort(reason="not_loaded")
        player = manager.entities.get(self._output_key or "")
        if player is None or player.session is None or player.session.closed:
            return self.async_abort(reason="output_removed")
        if manager.storage.corrupt:
            return self.async_abort(reason="storage_unavailable")
        errors = {}
        if user_input is not None:
            try:
                current = asdict(player.control.profile)
                baseline = {**self._profile_defaults, "unconfirmed_end": self._unconfirmed_default}
                changes = dict(self._profile_pending)
                selected = user_input["unconfirmed_end"]
                if selected != self._unconfirmed_default:
                    changes["unconfirmed_end"] = selected
                # Unedited fields keep their latest value; conflicting edits require
                # reopening instead of silently replacing another entry point's save.
                if any(
                    current[key] not in (baseline[key], value) for key, value in changes.items()
                ):
                    errors["base"] = "profile_changed"
                elif (
                    changes.get("feedback_mode", current["feedback_mode"]) == "standard"
                    and changes.get("unconfirmed_end", current["unconfirmed_end"]) != "manual"
                ):
                    errors["base"] = "profile_changed"
                else:
                    player.set_playback_profile(changes)
                    await manager.storage.flush()
                    return self.async_create_entry(title="", data=dict(self.config_entry.options))
            except ValueError:
                errors["base"] = "invalid_profile"
        else:
            self._unconfirmed_default = player.control.profile.unconfirmed_end
        return self.async_show_form(
            step_id="unconfirmed_end",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "unconfirmed_end",
                        default=user_input["unconfirmed_end"]
                        if user_input is not None
                        else self._unconfirmed_default,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["manual", "estimated_duration", "duration_fallback"],
                            translation_key="unconfirmed_end",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
