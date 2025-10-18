"""Services for Baby Tracker integration."""
import logging
from datetime import datetime, timezone
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Service schemas
DIAPER_SCHEMA = vol.Schema({
    vol.Optional("pee", default=True): cv.boolean,
    vol.Optional("poo", default=False): cv.boolean,
    vol.Optional("pee_color", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("poo_color", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("texture", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)), 
    vol.Optional("amount", default=2): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("note", default=""): cv.string,
})

NURSING_SCHEMA = vol.Schema({
    vol.Optional("left_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("right_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("both_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("finish_side", default="Left"): vol.In(["Left", "Right", "Both"]),
    vol.Optional("note", default=""): cv.string,
})

FORMULA_SCHEMA = vol.Schema({
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure", default=False): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

PUMPED_SCHEMA = vol.Schema({
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure", default=False): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

TEMPERATURE_SCHEMA = vol.Schema({
    vol.Required("temperature"): vol.All(vol.Coerce(float)),
    vol.Optional("is_fahrenheit", default=True): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

SYNC_SCHEMA = vol.Schema({})


async def async_register_services(hass: HomeAssistant):
    """Register services for Baby Tracker."""
    
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
        
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_formula,
            None,  # time_str
            data.get("amount"),
            data.get("is_english_measure", False),
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
        
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_pumped,
            None,  # time_str
            data.get("amount"),
            data.get("is_english_measure", False),
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
        DOMAIN, "sync", sync, schema=SYNC_SCHEMA
    )


async def async_unregister_services(hass: HomeAssistant):
    """Unregister services for Baby Tracker."""
    for service in [
        "add_diaper",
        "add_nursing",
        "add_formula",
        "add_pumped",
        "add_temperature",
        "sync"
    ]:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
