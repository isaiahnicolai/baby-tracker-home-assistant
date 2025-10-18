"""Config flow for Baby Tracker integration."""
import logging
import os
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
    }
)

async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect."""
    from .baby_tracker import BabyTracker

    db_path = os.path.join(hass.config.path(), "baby_tracker.db")
    baby_tracker = BabyTracker(db_path=db_path)

    # Authenticate with Baby Tracker
    result = await hass.async_add_executor_job(
        baby_tracker.authenticate, data[CONF_EMAIL], data[CONF_PASSWORD]
    )

    if result.get("status") != "success":
        raise InvalidAuth(result.get("message", "Authentication failed"))

    # Extract baby info for title
    baby_info = await hass.async_add_executor_job(baby_tracker.get_baby_info)
    baby_name = baby_info.name if baby_info else "Baby"
    
    return {"title": f"Baby Tracker ({baby_name})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Baby Tracker."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Check if an entry with this email already exists
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"], data=user_input
                )
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

    async def async_step_import(self, user_input):
        """Import a config entry."""
        return await self.async_step_user(user_input)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""