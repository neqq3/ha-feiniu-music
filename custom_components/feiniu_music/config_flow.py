"""Configure a regular music account, without NAS administrator access."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import create_client
from .client import AuthenticationError, FeiNiuError, NetworkError, RateLimitError
from .const import CONF_ACCOUNT_ID, CONF_DEVICE_ID, DOMAIN
from .runtime import normalize_url


class FeiNiuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Manage independent music entries and password-only reconfiguration."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._device_id = uuid4().hex

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up an account without storing a failed login or echoing its password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
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
                    errors["base"] = "invalid_response"
                else:
                    data[CONF_ACCOUNT_ID] = user["guid"]
                    return self.async_create_entry(title=f"FeiNiu Music — {username}", data=data)
            except ValueError:
                errors["base"] = "invalid_input"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NetworkError, RateLimitError:
                errors["base"] = "cannot_connect"
            except FeiNiuError:
                errors["base"] = "invalid_response"
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
                async with create_client(self.hass, entry.data[CONF_URL]) as client:
                    user = await client.login(
                        entry.data[CONF_USERNAME], password, entry.data[CONF_DEVICE_ID]
                    )
                if user.get("guid") != entry.data[CONF_ACCOUNT_ID]:
                    return self.async_abort(reason="identity_change")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )
            except ValueError:
                return self.async_abort(reason="identity_change")
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NetworkError, RateLimitError:
                errors["base"] = "cannot_connect"
            except FeiNiuError:
                errors["base"] = "invalid_response"
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
