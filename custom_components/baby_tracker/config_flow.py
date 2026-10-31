"""Config flow for Baby Tracker integration."""
import logging
import os
import uuid

import voluptuous as vol
from homeassistant import config_entries, core, exceptions
from homeassistant.core import callback

from .const import (
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_SYSTEM,
    CONFIG_ENTRY_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_SYSTEM,
    DOMAIN,
    UNIT_SYSTEM_IMPERIAL,
    UNIT_SYSTEM_METRIC,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=1)),
        vol.Optional(CONF_UNIT_SYSTEM, default=DEFAULT_UNIT_SYSTEM): vol.In(
            [UNIT_SYSTEM_IMPERIAL, UNIT_SYSTEM_METRIC]
        ),
    }
)


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect, and download the account's data."""
    from .client import AuthenticationError, BabyTracker

    db_path = os.path.join(hass.config.path(), "baby_tracker.db")
    baby_tracker = BabyTracker(db_path=db_path, time_zone=hass.config.time_zone)

    try:
        result = await hass.async_add_executor_job(
            baby_tracker.authenticate, data[CONF_EMAIL], data[CONF_PASSWORD], data[CONF_DEVICE_UUID]
        )
    except AuthenticationError as err:
        raise InvalidAuth(str(err)) from err

    if result.get("status") != "success":
        raise CannotConnect(result.get("message", "Authentication failed"))

    babies = await hass.async_add_executor_job(baby_tracker.get_all_babies)
    names = " & ".join(b.name for b in babies) or "Baby"
    return {"title": f"Baby Tracker ({names})"}


async def validate_login(hass: core.HomeAssistant, email, password, device_uuid):
    """Check credentials only (used when re-authenticating an existing entry)."""
    from .client import AuthenticationError, BabyTrackerAPI

    api = BabyTrackerAPI(time_zone=hass.config.time_zone)
    try:
        await hass.async_add_executor_job(api.login, email, password, device_uuid)
    except AuthenticationError as err:
        raise InvalidAuth(str(err)) from err
    except Exception as err:
        raise CannotConnect(str(err)) from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Baby Tracker."""

    VERSION = CONFIG_ENTRY_VERSION  # 2: each entry stores its own device_uuid (see async_migrate_entry)
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # One entry per account
            await self.async_set_unique_id(user_input[CONF_EMAIL])
            self._abort_if_unique_id_configured()

            # Register this integration as its own device on the sync server,
            # and keep that identity for the life of the entry
            user_input = {**user_input, CONF_DEVICE_UUID: str(uuid.uuid4())}
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data):
        """The server rejected the saved password (e.g. it was changed in the app)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await validate_login(self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD],
                                     entry.data.get(CONF_DEVICE_UUID))
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Change the update interval and unit system without re-adding the integration."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        entry = self.config_entry
        current = lambda key, default: entry.options.get(key, entry.data.get(key, default))  # noqa: E731
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=current(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                    vol.All(int, vol.Range(min=1)),
                vol.Optional(CONF_UNIT_SYSTEM, default=current(CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)):
                    vol.In([UNIT_SYSTEM_IMPERIAL, UNIT_SYSTEM_METRIC]),
            }),
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
