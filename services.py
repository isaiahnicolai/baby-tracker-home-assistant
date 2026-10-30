"""Services for Baby Tracker integration."""
import logging
from datetime import datetime, timezone
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_UNIT_SYSTEM,
    DEFAULT_UNIT_SYSTEM,
    UNIT_SYSTEM_IMPERIAL,
    ALERT_TYPE_FEEDING_OVERDUE,
    ALERT_TYPE_NO_POOP,
    ALERT_TYPE_LOW_WET_DIAPERS,
    ALERT_TYPE_FEVER,
    ALERT_TYPE_LONG_SLEEP,
)

_LOGGER = logging.getLogger(__name__)

# Service schemas
DIAPER_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("pee", default=True): cv.boolean,
    vol.Optional("poo", default=False): cv.boolean,
    vol.Optional("pee_color", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("poo_color", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("texture", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("amount", default=2): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("note", default=""): cv.string,
})

NURSING_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("left_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("right_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("both_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("finish_side", default="Left"): vol.In(["Left", "Right", "Both"]),
    vol.Optional("note", default=""): cv.string,
})

FORMULA_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

PUMPED_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

TEMPERATURE_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("temperature"): vol.All(vol.Coerce(float)),
    vol.Optional("is_fahrenheit", default=True): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

BATH_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("bath_type"): vol.Any(None, vol.In(["Bubble Bath", "Sponge Bath", "Shower", "Washed Hair"])),
    vol.Optional("note", default=""): cv.string,
})

PUMP_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("left_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("right_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("left_amount", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("right_amount", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_scale", default=False): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

MEDICINE_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("medicine_name"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("note", default=""): cv.string,
})

SLEEP_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("is_start"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

GROWTH_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("weight", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("length", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("head", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_weight_scale", default=True): cv.boolean,
    vol.Optional("is_english_length_scale", default=True): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

MILESTONE_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("milestone_name"): cv.string,
    vol.Optional("note", default=""): cv.string,
})

DOCTOR_VISIT_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("is_appointment", default=True): cv.boolean,
    vol.Optional("visit_type", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("note", default=""): cv.string,
    vol.Optional("doctor_note", default=""): cv.string,
    vol.Optional("symptom", default=""): cv.string,
})

VACCINE_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("vaccine_name"): cv.string,
    vol.Optional("note", default=""): cv.string,
})

LIST_BABIES_SCHEMA = vol.Schema({})

SYNC_SCHEMA = vol.Schema({})

FORCE_RESYNC_SCHEMA = vol.Schema({})

DISMISS_ALERT_SCHEMA = vol.Schema({
    vol.Optional("entity_id"): cv.string,
    vol.Optional("baby_name"): cv.string,
    vol.Optional("alert_type"): vol.In([
        ALERT_TYPE_FEEDING_OVERDUE,
        ALERT_TYPE_NO_POOP,
        ALERT_TYPE_LOW_WET_DIAPERS,
        ALERT_TYPE_FEVER,
        ALERT_TYPE_LONG_SLEEP,
    ]),
})

DISMISS_ALL_ALERTS_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
})


async def async_register_services(hass: HomeAssistant):
    """Register services for Baby Tracker."""

    # Check if services are already registered
    if hass.services.has_service(DOMAIN, "add_formula"):
        _LOGGER.debug("Services already registered, skipping registration")
        return

    async def _get_baby_id(coordinator, data):
        """Resolve the target baby from baby_name, or the only baby if there is one."""
        baby_name = data.get("baby_name")

        if baby_name:
            baby = await hass.async_add_executor_job(
                coordinator.baby_tracker.get_baby_by_name,
                baby_name
            )
            if not baby:
                raise ServiceValidationError(f"Baby '{baby_name}' not found")
            return baby.object_id

        babies = (coordinator.data or {}).get("babies") or []
        if len(babies) == 1:
            return babies[0].object_id
        if not babies:
            raise ServiceValidationError("No babies found in Baby Tracker")
        names = ", ".join(b.name for b in babies)
        raise ServiceValidationError(f"baby_name is required when there are multiple babies ({names})")

    def _check(result, what):
        """Raise if a core write reported failure, so the caller sees the error."""
        ok = result.get("status") == "success" if isinstance(result, dict) else bool(result)
        if not ok:
            message = result.get("message") if isinstance(result, dict) else None
            raise HomeAssistantError(f"Failed to {what}: {message or 'unknown error'}")

    def _get_unit_system_from_config():
        """Get the configured unit system (imperial or metric)."""
        for entry_id, entry_data in hass.data[DOMAIN].items():
            if entry_id != "config" and hasattr(entry_data, "config_entry"):
                return entry_data.config_entry.data.get(CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)
        return DEFAULT_UNIT_SYSTEM

    def _is_imperial_config():
        """Check if the configured unit system is imperial (oz, lbs, F)."""
        return _get_unit_system_from_config() == UNIT_SYSTEM_IMPERIAL

    async def add_diaper(call: ServiceCall):
        """Add a diaper change record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_diaper,
            baby_id,
            None,  # time_str
            data.get("pee"),
            data.get("poo"),
            data.get("pee_color", 0),
            data.get("poo_color", 0),
            data.get("texture", 0),
            data.get("amount", 2),
            data.get("note", "")
        )

        _check(result, "add diaper")
        await coordinator.async_refresh()

    async def add_nursing(call: ServiceCall):
        """Add a nursing session record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        # Android NursingFinishSide: NotSet=0, Left=1, Right=2 ("Both" has no finish side)
        finish_side_map = {"Both": 0, "Left": 1, "Right": 2}
        finish_side = finish_side_map.get(data.get("finish_side", "Left"), 1)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_nursing,
            baby_id,
            None,  # time_str
            data.get("left_duration", 0),
            data.get("right_duration", 0),
            data.get("both_duration", 0),
            finish_side,
            data.get("note", "")
        )

        _check(result, "add nursing")
        await coordinator.async_refresh()

    async def add_formula(call: ServiceCall):
        """Add a formula feeding record."""
        await _add_formula(call.data)

    async def _add_formula(data):
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        # Use configured unit system as default if not explicitly provided
        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_formula,
            baby_id,
            None,  # time_str
            data.get("amount"),
            is_english,
            data.get("note", "")
        )

        _check(result, "add formula")
        await coordinator.async_refresh()

    async def add_pumped(call: ServiceCall):
        """Add a pumped milk record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        # Use configured unit system as default if not explicitly provided
        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_pumped,
            baby_id,
            None,  # time_str
            data.get("amount"),
            is_english,
            data.get("note", "")
        )

        _check(result, "add pumped milk")
        await coordinator.async_refresh()

    async def add_temperature(call: ServiceCall):
        """Add a temperature record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_temperature,
            baby_id,
            None,  # time_str
            data.get("temperature"),
            data.get("is_fahrenheit", True),
            data.get("note", "")
        )

        _check(result, "add temperature")
        await coordinator.async_refresh()

    async def log_bath(call: ServiceCall):
        """Log a bath record."""
        _LOGGER.debug(f"log_bath service called with data: {call.data}")
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_bath,
            baby_id,
            data.get("bath_type"),
            data.get("note", ""),
            None  # time (defaults to now)
        )
        _check(result, "log bath")

        _LOGGER.info(f"Logged bath: type={data.get('bath_type')}, note={data.get('note')}")
        await coordinator.async_refresh()

    async def log_pump(call: ServiceCall):
        """Log a pump session record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_pump,
            baby_id,
            data.get("left_duration", 0),
            data.get("right_duration", 0),
            data.get("left_amount", 0),
            data.get("right_amount", 0),
            data.get("is_english_scale", False),
            data.get("note", ""),
            None  # time (defaults to now)
        )

        _check(result, "log pump session")

        _LOGGER.info(f"Logged pump session: left={data.get('left_duration')}min/{data.get('left_amount')}, right={data.get('right_duration')}min/{data.get('right_amount')}")
        await coordinator.async_refresh()

    async def log_medicine(call: ServiceCall):
        """Log a medicine administration record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        # Get medicine name and look up the med_id
        medicine_name = data.get("medicine_name")

        # Get available medicines
        medicine_selections = await hass.async_add_executor_job(
            coordinator.baby_tracker.get_medicine_selections
        )

        # Find the medicine by name
        med_id = None
        for med in medicine_selections:
            if med.get("name", "").lower() == medicine_name.lower():
                med_id = med.get("id")
                break

        if not med_id:
            raise ServiceValidationError(f"Medicine '{medicine_name}' not found")

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_medicine,
            baby_id,
            None,  # time_str (defaults to now)
            med_id,
            data.get("amount"),
            data.get("note", "")
        )

        _check(result, "log medicine")

        _LOGGER.info(f"Logged medicine: {medicine_name}, amount={data.get('amount')}")
        await coordinator.async_refresh()

    async def log_sleep(call: ServiceCall):
        """Log a sleep start or end event."""
        _LOGGER.debug(f"log_sleep service called with data: {call.data}")
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        is_start = data.get("is_start", True)
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_sleep_event,
            baby_id,
            is_start,
            data.get("note", "")
        )
        _check(result, "start sleep" if is_start else "end sleep")

        _LOGGER.info(f"Logged sleep {'start' if is_start else 'end'}")
        await coordinator.async_refresh()

    async def log_growth(call: ServiceCall):
        """Log a growth measurement record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_growth,
            baby_id,
            data.get("weight", 0),
            data.get("length", 0),
            data.get("head", 0),
            data.get("is_english_weight_scale", True),
            data.get("is_english_length_scale", True),
            data.get("note", ""),
            None  # time (defaults to now)
        )

        _check(result, "log growth measurement")

        _LOGGER.info(f"Logged growth: weight={data.get('weight')}, length={data.get('length')}, head={data.get('head')}")
        await coordinator.async_refresh()

    async def log_milestone(call: ServiceCall):
        """Log a milestone achievement record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        baby_id = await _get_baby_id(coordinator, data)

        # Get milestone name and look up the milestone_selection_id
        milestone_name = data.get("milestone_name")

        # Get available milestones
        milestone_selections = await hass.async_add_executor_job(
            coordinator.baby_tracker.get_milestone_selections
        )

        # Find the milestone by name
        milestone_selection_id = None
        for milestone in milestone_selections:
            if milestone.get("name", "").lower() == milestone_name.lower():
                milestone_selection_id = milestone.get("id")
                break

        if not milestone_selection_id:
            raise ServiceValidationError(f"Milestone '{milestone_name}' not found")

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_milestone,
            baby_id,
            milestone_selection_id,
            data.get("note", ""),
            None  # time (defaults to now)
        )

        _check(result, "log milestone")

        _LOGGER.info(f"Logged milestone: {milestone_name}")
        await coordinator.async_refresh()

    async def log_doctor_visit(call: ServiceCall):
        """Log a doctor visit record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_doctor_visit,
            baby_id,
            data.get("is_appointment", True),
            data.get("visit_type", 0),
            data.get("note", ""),
            data.get("doctor_note", ""),
            data.get("symptom", ""),
            None  # time (defaults to now)
        )

        _check(result, "log doctor visit")

        _LOGGER.info(f"Logged doctor visit: type={data.get('visit_type')}, appointment={data.get('is_appointment')}")
        await coordinator.async_refresh()

    async def log_vaccine(call: ServiceCall):
        """Log a vaccine administration record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        baby_id = await _get_baby_id(coordinator, data)

        # Get vaccine name and look up the vacc_id
        vaccine_name = data.get("vaccine_name")

        # Get available vaccines
        vaccine_selections = await hass.async_add_executor_job(
            coordinator.baby_tracker.get_vaccine_selections
        )

        # Find the vaccine by name
        vacc_id = None
        for vaccine in vaccine_selections:
            if vaccine.get("name", "").lower() == vaccine_name.lower():
                vacc_id = vaccine.get("id")
                break

        if not vacc_id:
            raise ServiceValidationError(f"Vaccine '{vaccine_name}' not found")

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_vaccine,
            baby_id,
            vacc_id,
            data.get("note", ""),
            "",  # doc_visit_id (empty for now)
            None  # time (defaults to now)
        )

        _check(result, "log vaccine")

        _LOGGER.info(f"Logged vaccine: {vaccine_name}")
        await coordinator.async_refresh()

    async def list_babies(call: ServiceCall):
        """List all babies in the database."""
        coordinator = _get_coordinator(hass)

        babies = await hass.async_add_executor_job(
            coordinator.baby_tracker.get_all_babies
        )

        if not babies:
            _LOGGER.warning("No babies found in database")
            return

        # Log baby information
        baby_names = [baby.name for baby in babies]
        _LOGGER.info(f"Babies in database: {', '.join(baby_names)}")

        # Return baby information as service response
        return {
            "babies": [
                {
                    "name": baby.name,
                    "id": baby.object_id,
                    "dob": baby.dob[:10] if baby.dob else None,
                    "gender": baby.gender if hasattr(baby, 'gender') else None
                }
                for baby in babies
            ],
            "count": len(babies)
        }

    async def sync(call: ServiceCall):
        """Sync data with the server."""
        coordinator = _get_coordinator(hass)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.sync
        )

        _check(result, "sync")
        await coordinator.async_refresh()

    async def force_resync(call: ServiceCall):
        """Force a complete resync by deleting local database and re-downloading all data.

        This is useful when the group leader resets sync and all clients need to reconnect.
        WARNING: This will delete all local data and re-download from server.
        """
        coordinator = _get_coordinator(hass)

        _LOGGER.warning("Force resync initiated - this will delete local database and re-sync all data")

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.force_resync,
            coordinator.email,
            coordinator.password,
            coordinator.device_uuid
        )
        _check(result, "force resync")

        _LOGGER.info("Force resync completed successfully")

        # Refresh coordinator data first
        await coordinator.async_refresh()

        # Reload the config entry to trigger platform re-setup with new baby entities
        # This is necessary because entities are created during platform setup
        _LOGGER.info("Reloading config entry to create baby entities")
        for entry_id, entry_coordinator in hass.data[DOMAIN].items():
            if entry_id != "config" and entry_coordinator == coordinator:
                # Get the config entry
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry:
                    await hass.config_entries.async_reload(entry.entry_id)
                    _LOGGER.info(f"Config entry {entry_id} reloaded")
                break

    def _get_coordinator(hass):
        """Get the data coordinator for the first configured entry."""
        for entry_id, coordinator in hass.data[DOMAIN].items():
            if entry_id != "config":
                return coordinator
        raise ValueError("No configured Baby Tracker entry found")

    # Register the services
    hass.services.async_register(
        DOMAIN, "add_diaper", add_diaper, schema=DIAPER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_nursing", add_nursing, schema=NURSING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_formula", add_formula, schema=FORMULA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_pumped", add_pumped, schema=PUMPED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_temperature", add_temperature, schema=TEMPERATURE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_bath", log_bath, schema=BATH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_pump", log_pump, schema=PUMP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_medicine", log_medicine, schema=MEDICINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_sleep", log_sleep, schema=SLEEP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_growth", log_growth, schema=GROWTH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_milestone", log_milestone, schema=MILESTONE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_doctor_visit", log_doctor_visit, schema=DOCTOR_VISIT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_vaccine", log_vaccine, schema=VACCINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "list_babies", list_babies, schema=LIST_BABIES_SCHEMA, supports_response="only"
    )
    hass.services.async_register(
        DOMAIN, "sync", sync, schema=SYNC_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "force_resync", force_resync, schema=FORCE_RESYNC_SCHEMA
    )

    async def dismiss_alert(call: ServiceCall):
        """Dismiss a specific health alert."""
        data = call.data
        entity_id = data.get("entity_id")
        baby_name = data.get("baby_name")
        alert_type = data.get("alert_type")

        coordinator = _get_coordinator(hass)
        dismissed_count = 0

        for entity in coordinator._alert_entities:
            if not hasattr(entity, "dismiss"):
                continue
            if entity_id and entity.entity_id != entity_id:
                continue
            if baby_name and entity._baby_name != baby_name:
                continue
            if alert_type and entity._alert_type != alert_type:
                continue
            entity.dismiss()
            dismissed_count += 1

        _LOGGER.info(f"Dismissed {dismissed_count} alert(s)")

    async def dismiss_all_alerts(call: ServiceCall):
        """Dismiss all health alerts, optionally filtered by baby name."""
        data = call.data
        baby_name = data.get("baby_name")

        coordinator = _get_coordinator(hass)
        dismissed_count = 0

        for entity in coordinator._alert_entities:
            if not hasattr(entity, "dismiss"):
                continue
            if baby_name and entity._baby_name != baby_name:
                continue
            entity.dismiss()
            dismissed_count += 1

        _LOGGER.info(f"Dismissed {dismissed_count} alert(s)")

    hass.services.async_register(
        DOMAIN, "dismiss_alert", dismiss_alert, schema=DISMISS_ALERT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "dismiss_all_alerts", dismiss_all_alerts, schema=DISMISS_ALL_ALERTS_SCHEMA
    )

    # Bottle size mappings: oz -> ml (using nice round numbers)
    BOTTLE_SIZES = {
        "small": {"oz": 2, "ml": 60},
        "medium": {"oz": 4, "ml": 120},
        "large": {"oz": 6, "ml": 180},
        "xlarge": {"oz": 8, "ml": 240},
        "4oz": {"oz": 4, "ml": 120},
        "6oz": {"oz": 6, "ml": 180},
        "8oz": {"oz": 8, "ml": 240},
    }

    def _get_bottle_amount(size_key):
        """Get the bottle amount based on configured unit system."""
        is_imperial = _is_imperial_config()
        size = BOTTLE_SIZES.get(size_key, BOTTLE_SIZES["medium"])
        return (size["oz"], True) if is_imperial else (size["ml"], False)

    # Quick action bottle services
    async def add_4oz_bottle(call: ServiceCall):
        """Quick action: Add a 4oz/120ml bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("4oz")
        await _add_formula(data)

    async def add_6oz_bottle(call: ServiceCall):
        """Quick action: Add a 6oz/180ml bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("6oz")
        await _add_formula(data)

    async def add_8oz_bottle(call: ServiceCall):
        """Quick action: Add an 8oz/240ml bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("8oz")
        await _add_formula(data)

    async def add_small_bottle(call: ServiceCall):
        """Quick action: Add a small (2oz/60ml) bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("small")
        await _add_formula(data)

    async def add_medium_bottle(call: ServiceCall):
        """Quick action: Add a medium (4oz/120ml) bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("medium")
        await _add_formula(data)

    async def add_large_bottle(call: ServiceCall):
        """Quick action: Add a large (6oz/180ml) bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("large")
        await _add_formula(data)

    async def add_xlarge_bottle(call: ServiceCall):
        """Quick action: Add an extra large (8oz/240ml) bottle based on unit config."""
        data = dict(call.data)
        data["amount"], data["is_english_measure"] = _get_bottle_amount("xlarge")
        await _add_formula(data)

    # Register quick action services
    QUICK_BOTTLE_SCHEMA = vol.Schema({
        vol.Optional("baby_name"): cv.string,
        vol.Optional("note"): cv.string,
    })

    hass.services.async_register(DOMAIN, "add_4oz_bottle", add_4oz_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_6oz_bottle", add_6oz_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_8oz_bottle", add_8oz_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_small_bottle", add_small_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_medium_bottle", add_medium_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_large_bottle", add_large_bottle, schema=QUICK_BOTTLE_SCHEMA)
    hass.services.async_register(DOMAIN, "add_xlarge_bottle", add_xlarge_bottle, schema=QUICK_BOTTLE_SCHEMA)


async def async_unregister_services(hass: HomeAssistant):
    """Unregister services for Baby Tracker."""
    for service in [
        "add_diaper",
        "add_nursing",
        "add_formula",
        "add_pumped",
        "add_temperature",
        "log_bath",
        "log_pump",
        "log_medicine",
        "log_sleep",
        "log_growth",
        "log_milestone",
        "log_doctor_visit",
        "log_vaccine",
        "list_babies",
        "sync",
        "force_resync",
        "add_4oz_bottle",
        "add_6oz_bottle",
        "add_8oz_bottle",
        "add_small_bottle",
        "add_medium_bottle",
        "add_large_bottle",
        "add_xlarge_bottle",
        "dismiss_alert",
        "dismiss_all_alerts",
    ]:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
