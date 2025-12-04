"""Services for Baby Tracker integration."""
import logging
from datetime import datetime, timezone
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_UNIT_SYSTEM,
    DEFAULT_UNIT_SYSTEM,
    UNIT_SYSTEM_IMPERIAL,
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
    vol.Optional("is_english_measure", default=False): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

PUMPED_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure", default=False): cv.boolean,
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


async def async_register_services(hass: HomeAssistant):
    """Register services for Baby Tracker."""

    # Check if services are already registered
    if hass.services.has_service(DOMAIN, "add_formula"):
        _LOGGER.debug("Services already registered, skipping registration")
        return

    async def _get_baby_id(coordinator, data):
        """Helper to get baby_id from baby_name or use default."""
        baby_name = data.get("baby_name")

        if baby_name:
            # Look up baby by name
            baby = await hass.async_add_executor_job(
                coordinator.baby_tracker.get_baby_by_name,
                baby_name
            )
            if not baby:
                _LOGGER.error(f"Baby '{baby_name}' not found")
                return None
            return baby.object_id
        else:
            # Use first baby as default
            baby_info = coordinator.data.get("baby_info")
            if not baby_info:
                _LOGGER.error("No baby info available")
                return None
            baby_id = baby_info.object_id if hasattr(baby_info, 'object_id') else None
            if not baby_id:
                _LOGGER.error("Could not determine baby_id")
                return None
            return baby_id

    def _get_unit_system_from_config():
        """Get the configured unit system (imperial or metric)."""
        for entry_id, entry_data in hass.data[DOMAIN].items():
            if entry_id != "config" and hasattr(entry_data, "config_entry"):
                return entry_data.config_entry.data.get(CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)
        return DEFAULT_UNIT_SYSTEM

    def _is_imperial_config():
        """Check if the configured unit system is imperial (oz, lbs, F)."""
        return _get_unit_system_from_config() == UNIT_SYSTEM_IMPERIAL

    @callback
    async def add_diaper(call: ServiceCall):
        """Add a diaper change record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        
        status = 2 if data["pee"] and data["poo"] else 1 if data["poo"] else 0 if data["pee"] else 3
        
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_diaper,
            None,  # time_str
            data.get("pee"),
            data.get("poo"),
            data.get("pee_color", 0),
            data.get("poo_color", 0), 
            data.get("texture", 0),
            data.get("amount", 2),
            data.get("note", "")
        )
        
        if result["status"] != "success":
            _LOGGER.error(f"Failed to add diaper: {result.get('message')}")
            return False
            
        await coordinator.async_refresh()
        return True
        
    @callback
    async def add_nursing(call: ServiceCall):
        """Add a nursing session record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        
        # Convert finish_side from string to integer
        finish_side_map = {"Right": 0, "Left": 1, "Both": 2}
        finish_side = finish_side_map.get(data.get("finish_side", "Left"), 1)
        
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_nursing,
            None,  # time_str
            data.get("left_duration", 0),
            data.get("right_duration", 0),
            data.get("both_duration", 0),
            finish_side,
            data.get("note", "")
        )
        
        if result["status"] != "success":
            _LOGGER.error(f"Failed to add nursing: {result.get('message')}")
            return False
            
        await coordinator.async_refresh()
        return True
        
    @callback
    async def add_formula(call: ServiceCall):
        """Add a formula feeding record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Use configured unit system as default if not explicitly provided
        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_formula,
            None,  # time_str
            data.get("amount"),
            is_english,
            data.get("note", "")
        )

        if result["status"] != "success":
            _LOGGER.error(f"Failed to add formula: {result.get('message')}")
            return False

        await coordinator.async_refresh()
        return True

    @callback
    async def add_pumped(call: ServiceCall):
        """Add a pumped milk record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Use configured unit system as default if not explicitly provided
        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_pumped,
            None,  # time_str
            data.get("amount"),
            is_english,
            data.get("note", "")
        )

        if result["status"] != "success":
            _LOGGER.error(f"Failed to add pumped milk: {result.get('message')}")
            return False

        await coordinator.async_refresh()
        return True
        
    @callback
    async def add_temperature(call: ServiceCall):
        """Add a temperature record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_temperature,
            None,  # time_str
            data.get("temperature"),
            data.get("is_fahrenheit", True),
            data.get("note", "")
        )

        if result["status"] != "success":
            _LOGGER.error(f"Failed to add temperature: {result.get('message')}")
            return False

        await coordinator.async_refresh()
        return True

    @callback
    async def log_bath(call: ServiceCall):
        """Log a bath record."""
        _LOGGER.warning(f"=== log_bath service called with data: {call.data}")
        data = call.data
        coordinator = _get_coordinator(hass)

        try:
            result = await hass.async_add_executor_job(
                coordinator.baby_tracker.log_bath,
                data.get("bath_type"),
                data.get("note", ""),
                None  # time (defaults to now)
            )

            if result.get("status") != "success":
                _LOGGER.error(f"Failed to log bath: {result.get('message')}")
                return False

            _LOGGER.info(f"Successfully logged bath: type={data.get('bath_type')}, note={data.get('note')}")
            await coordinator.async_refresh()
            return True
        except Exception as e:
            _LOGGER.error(f"Exception in log_bath service: {str(e)}", exc_info=True)
            return False

    @callback
    async def log_pump(call: ServiceCall):
        """Log a pump session record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Get baby_id using helper
        baby_id = await _get_baby_id(coordinator, data)
        if not baby_id:
            return False

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

        if not result:
            _LOGGER.error("Failed to log pump session")
            return False

        _LOGGER.info(f"Successfully logged pump session: left={data.get('left_duration')}min/{data.get('left_amount')}, right={data.get('right_duration')}min/{data.get('right_amount')}")
        await coordinator.async_refresh()
        return True

    @callback
    async def log_medicine(call: ServiceCall):
        """Log a medicine administration record."""
        data = call.data
        coordinator = _get_coordinator(hass)

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
            _LOGGER.error(f"Medicine '{medicine_name}' not found in available medicines")
            return False

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_medicine,
            None,  # time_str (defaults to now)
            med_id,
            data.get("amount"),
            data.get("note", "")
        )

        if result.get("status") != "success":
            _LOGGER.error(f"Failed to log medicine: {result.get('message')}")
            return False

        _LOGGER.info(f"Successfully logged medicine: {medicine_name}, amount={data.get('amount')}")
        await coordinator.async_refresh()
        return True

    @callback
    async def log_sleep(call: ServiceCall):
        """Log a sleep start or end event."""
        _LOGGER.warning(f"=== log_sleep service called with data: {call.data}")
        data = call.data
        coordinator = _get_coordinator(hass)

        try:
            # Get baby_id using helper
            baby_id = await _get_baby_id(coordinator, data)
            if not baby_id:
                _LOGGER.error("Could not determine baby_id for sleep event")
                return False

            is_start = data.get("is_start", True)
            note = data.get("note", "")

            result = await hass.async_add_executor_job(
                coordinator.baby_tracker.log_sleep_event,
                baby_id,
                is_start,
                note
            )

            if result.get("status") != "success":
                _LOGGER.error(f"Failed to log sleep: {result.get('message')}")
                return False

            action = "started" if is_start else "ended"
            _LOGGER.info(f"Successfully logged sleep {action}")
            await coordinator.async_refresh()
            return True
        except Exception as e:
            _LOGGER.error(f"Exception in log_sleep service: {str(e)}", exc_info=True)
            return False

    @callback
    async def log_growth(call: ServiceCall):
        """Log a growth measurement record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Get baby_id using helper
        baby_id = await _get_baby_id(coordinator, data)
        if not baby_id:
            return False

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

        if not result:
            _LOGGER.error("Failed to log growth measurement")
            return False

        _LOGGER.info(f"Successfully logged growth: weight={data.get('weight')}, length={data.get('length')}, head={data.get('head')}")
        await coordinator.async_refresh()
        return True

    @callback
    async def log_milestone(call: ServiceCall):
        """Log a milestone achievement record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Get baby_id using helper
        baby_id = await _get_baby_id(coordinator, data)
        if not baby_id:
            return False

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
            _LOGGER.error(f"Milestone '{milestone_name}' not found in available milestones")
            return False

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_milestone,
            baby_id,
            milestone_selection_id,
            data.get("note", ""),
            None  # time (defaults to now)
        )

        if not result:
            _LOGGER.error("Failed to log milestone")
            return False

        _LOGGER.info(f"Successfully logged milestone: {milestone_name}")
        await coordinator.async_refresh()
        return True

    @callback
    async def log_doctor_visit(call: ServiceCall):
        """Log a doctor visit record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Get baby_id using helper
        baby_id = await _get_baby_id(coordinator, data)
        if not baby_id:
            return False

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

        if not result:
            _LOGGER.error("Failed to log doctor visit")
            return False

        _LOGGER.info(f"Successfully logged doctor visit: type={data.get('visit_type')}, appointment={data.get('is_appointment')}")
        await coordinator.async_refresh()
        return True

    @callback
    async def log_vaccine(call: ServiceCall):
        """Log a vaccine administration record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Get baby_id using helper
        baby_id = await _get_baby_id(coordinator, data)
        if not baby_id:
            return False

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
            _LOGGER.error(f"Vaccine '{vaccine_name}' not found in available vaccines")
            return False

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_vaccine,
            baby_id,
            vacc_id,
            data.get("note", ""),
            "",  # doc_visit_id (empty for now)
            None  # time (defaults to now)
        )

        if not result:
            _LOGGER.error("Failed to log vaccine")
            return False

        _LOGGER.info(f"Successfully logged vaccine: {vaccine_name}")
        await coordinator.async_refresh()
        return True

    @callback
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
                    "dob": baby.dob.strftime("%Y-%m-%d") if hasattr(baby, 'dob') and baby.dob else None,
                    "gender": baby.gender if hasattr(baby, 'gender') else None
                }
                for baby in babies
            ],
            "count": len(babies)
        }

    @callback
    async def sync(call: ServiceCall):
        """Sync data with the server."""
        coordinator = _get_coordinator(hass)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.sync
        )

        if result["status"] != "success":
            _LOGGER.error(f"Failed to sync: {result.get('message')}")
            return False

        await coordinator.async_refresh()
        return True
    
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
    @callback
    async def add_4oz_bottle(call: ServiceCall):
        """Quick action: Add a 4oz/120ml bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("4oz")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_6oz_bottle(call: ServiceCall):
        """Quick action: Add a 6oz/180ml bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("6oz")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_8oz_bottle(call: ServiceCall):
        """Quick action: Add an 8oz/240ml bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("8oz")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_small_bottle(call: ServiceCall):
        """Quick action: Add a small (2oz/60ml) bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("small")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_medium_bottle(call: ServiceCall):
        """Quick action: Add a medium (4oz/120ml) bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("medium")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_large_bottle(call: ServiceCall):
        """Quick action: Add a large (6oz/180ml) bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("large")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

    @callback
    async def add_xlarge_bottle(call: ServiceCall):
        """Quick action: Add an extra large (8oz/240ml) bottle based on unit config."""
        data = dict(call.data)
        amount, is_english = _get_bottle_amount("xlarge")
        data["amount"] = amount
        data["is_english_measure"] = is_english
        await add_formula(ServiceCall(DOMAIN, "add_formula", data))

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
        "log_growth",
        "log_milestone",
        "log_doctor_visit",
        "log_vaccine",
        "list_babies",
        "sync",
        "add_4oz_bottle",
        "add_6oz_bottle",
        "add_8oz_bottle",
        "add_small_bottle",
        "add_medium_bottle",
        "add_large_bottle",
        "add_xlarge_bottle"
    ]:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
