"""Config flow for Baby Tracker integration."""
import functools
import logging
import os
import uuid

import voluptuous as vol
from homeassistant import config_entries, core, exceptions
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_FEEDING_OVERDUE_HOURS,
    CONF_FEVER_THRESHOLD,
    CONF_LOW_WET_MINIMUM,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_START_HOUR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SLEEP_GAP_MINUTES,
    CONF_SLEEP_MIN_MINUTES,
    CONF_SLEEP_SOURCE_ASLEEP_STATES,
    CONF_SLEEP_SOURCE_ENTITY,
    CONF_SLEEP_SOURCES,
    CONF_UNIT_SYSTEM,
    CONFIG_ENTRY_VERSION,
    DEFAULT_FEEDING_OVERDUE_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLEEP_ASLEEP_STATES,
    DEFAULT_SLEEP_GAP_MINUTES,
    DEFAULT_SLEEP_MIN_MINUTES,
    DEFAULT_UNIT_SYSTEM,
    DOMAIN,
    LOW_WET_THRESHOLD,
    NIGHT_END_HOUR,
    NIGHT_START_HOUR,
    UNIT_SYSTEM_IMPERIAL,
    UNIT_SYSTEM_METRIC,
)

_LOGGER = logging.getLogger(__name__)

# Fever thresholds outside these are mistakes (e.g. 38 typed while the entry is in Fahrenheit)
FEVER_THRESHOLD_RANGE = {UNIT_SYSTEM_IMPERIAL: (95.0, 110.0), UNIT_SYSTEM_METRIC: (35.0, 43.0)}

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
        # Sign in, join the group and fetch the seed database only. Replaying the
        # account's history can take a while, so the first refresh does that once
        # the entry exists, instead of this dialog appearing to hang.
        result = await hass.async_add_executor_job(
            functools.partial(baby_tracker.authenticate, data[CONF_EMAIL], data[CONF_PASSWORD],
                              data[CONF_DEVICE_UUID], sync_history=False)
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
    """Change the update interval, unit system, alert thresholds and sleep sources without re-adding the integration."""

    def __init__(self):
        self._options = {}  # what the first step collected
        self._sleep_sources = {}  # {baby_id: settings} being collected, one baby per step
        self._babies_left = []  # [(baby_id, name)] still to ask about

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        errors = {}

        if user_input is not None:
            low, high = FEVER_THRESHOLD_RANGE[user_input.get(CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)]
            fever = user_input.get(CONF_FEVER_THRESHOLD)
            if fever is not None and not low <= fever <= high:
                errors[CONF_FEVER_THRESHOLD] = "invalid_fever_threshold"
            else:
                return await self._async_start_sleep_sources(user_input)

        def current(key, default):
            """What the form shows: what was just submitted (after an error), else what is saved."""
            if user_input is not None:
                return user_input.get(key, default)
            return entry.options.get(key, entry.data.get(key, default))

        fever = current(CONF_FEVER_THRESHOLD, None)
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=current(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                    vol.All(int, vol.Range(min=1)),
                vol.Optional(CONF_UNIT_SYSTEM, default=current(CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)):
                    vol.In([UNIT_SYSTEM_IMPERIAL, UNIT_SYSTEM_METRIC]),
                # 0 uses the baby's age (3.5 hours for a newborn, up to 6 for older babies)
                vol.Optional(CONF_FEEDING_OVERDUE_HOURS,
                             default=current(CONF_FEEDING_OVERDUE_HOURS, DEFAULT_FEEDING_OVERDUE_HOURS)):
                    vol.All(vol.Coerce(float), vol.Range(min=0, max=24)),
                vol.Optional(CONF_LOW_WET_MINIMUM, default=current(CONF_LOW_WET_MINIMUM, LOW_WET_THRESHOLD)):
                    vol.All(int, vol.Range(min=1, max=20)),
                vol.Optional(CONF_NIGHT_START_HOUR, default=current(CONF_NIGHT_START_HOUR, NIGHT_START_HOUR)):
                    vol.All(int, vol.Range(min=0, max=23)),
                vol.Optional(CONF_NIGHT_END_HOUR, default=current(CONF_NIGHT_END_HOUR, NIGHT_END_HOUR)):
                    vol.All(int, vol.Range(min=0, max=23)),
                # Blank uses 100.4 F (38.0 C)
                vol.Optional(CONF_FEVER_THRESHOLD,
                             description={"suggested_value": fever} if fever is not None else None):
                    vol.Coerce(float),
            }),
        )


    async def _async_start_sleep_sources(self, options):
        """After the general settings: one step per baby for the sleep source, if the account has babies."""
        self._options = options
        self._sleep_sources = dict(self.config_entry.options.get(CONF_SLEEP_SOURCES) or {})
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        babies = (getattr(coordinator, "data", None) or {}).get("babies") or []
        self._babies_left = [(baby.object_id, baby.name) for baby in babies]
        return await self._async_next_baby()

    async def _async_next_baby(self):
        if self._babies_left:
            return await self.async_step_sleep_source()
        data = dict(self._options)
        if self._sleep_sources:
            data[CONF_SLEEP_SOURCES] = self._sleep_sources
        return self.async_create_entry(data=data)

    async def async_step_sleep_source(self, user_input=None):
        """Take one baby's sleep from another entity (leave the entity empty for none)."""
        baby_id, baby_name = self._babies_left[0]
        errors = {}

        if user_input is not None:
            if not user_input.get(CONF_SLEEP_SOURCE_ENTITY):
                self._sleep_sources.pop(baby_id, None)
            elif not user_input.get(CONF_SLEEP_SOURCE_ASLEEP_STATES):
                errors[CONF_SLEEP_SOURCE_ASLEEP_STATES] = "no_asleep_states"
            else:
                self._sleep_sources[baby_id] = user_input
            if not errors:
                self._babies_left.pop(0)
                return await self._async_next_baby()

        saved = user_input if user_input is not None else self._sleep_sources.get(baby_id, {})
        entity = saved.get(CONF_SLEEP_SOURCE_ENTITY)
        return self.async_show_form(
            step_id="sleep_source",
            errors=errors,
            description_placeholders={"baby": baby_name},
            data_schema=vol.Schema({
                vol.Optional(CONF_SLEEP_SOURCE_ENTITY, description={"suggested_value": entity} if entity else None):
                    selector.EntitySelector(selector.EntitySelectorConfig()),
                vol.Optional(CONF_SLEEP_SOURCE_ASLEEP_STATES,
                             default=saved.get(CONF_SLEEP_SOURCE_ASLEEP_STATES, DEFAULT_SLEEP_ASLEEP_STATES)):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=DEFAULT_SLEEP_ASLEEP_STATES, custom_value=True, multiple=True)),
                vol.Optional(CONF_SLEEP_GAP_MINUTES,
                             default=saved.get(CONF_SLEEP_GAP_MINUTES, DEFAULT_SLEEP_GAP_MINUTES)):
                    vol.All(int, vol.Range(min=0, max=180)),
                vol.Optional(CONF_SLEEP_MIN_MINUTES,
                             default=saved.get(CONF_SLEEP_MIN_MINUTES, DEFAULT_SLEEP_MIN_MINUTES)):
                    vol.All(int, vol.Range(min=0, max=180)),
            }),
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
