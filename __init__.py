"""Baby Tracker integration for Home Assistant."""
import logging
import os
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .baby_tracker import BabyTracker
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = ["sensor", "button"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Baby Tracker component."""
    hass.data.setdefault(DOMAIN, {})
    
    if DOMAIN not in config:
        return True
        
    hass.data[DOMAIN]["config"] = config[DOMAIN]
    
    # Register services
    await async_register_services(hass)
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Baby Tracker from a config entry."""
    config = entry.data

    # Set database path in Home Assistant's config directory
    db_path = os.path.join(hass.config.path(), "baby_tracker.db")
    _LOGGER.info(f"Setting up Baby Tracker with database at: {db_path}")

    # Create the data coordinator
    coordinator = BabyTrackerDataCoordinator(
        hass,
        email=config[CONF_EMAIL],
        password=config[CONF_PASSWORD],
        db_path=db_path,
        scan_interval=timedelta(minutes=config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    # Fetch initial data
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register services (will only register once even if multiple entries exist)
    await async_register_services(hass)

    # Set up all platforms for this device/entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Close any open connections or resources

        # If this is the last entry, unregister services and clean up database
        if not any(entry_id != "config" for entry_id in hass.data[DOMAIN]):
            await async_unregister_services(hass)

            # Delete the database file when the extension is removed
            db_path = coordinator.db_path
            if db_path and os.path.exists(db_path):
                try:
                    os.remove(db_path)
                    _LOGGER.info(f"Deleted Baby Tracker database at: {db_path}")
                except Exception as e:
                    _LOGGER.error(f"Failed to delete database at {db_path}: {e}")

    return unload_ok


class BabyTrackerDataCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Baby Tracker."""

    def __init__(self, hass, email, password, db_path, scan_interval):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        
        # Create Baby Tracker instance
        self.baby_tracker = BabyTracker(
            db_path=db_path
        )
        self.email = email
        self.password = password
        self.authenticated = False
        self.db_path = db_path
        _LOGGER.info(f"Initialized Baby Tracker coordinator with database at: {db_path}")

    async def _async_update_data(self):
        """Fetch data from Baby Tracker."""
        try:
            # Run authentication in an executor
            if not self.authenticated:
                auth_result = await self.hass.async_add_executor_job(
                    self.baby_tracker.authenticate, self.email, self.password
                )
                if auth_result.get("status") != "success":
                    raise UpdateFailed(f"Authentication failed: {auth_result.get('message')}")
                self.authenticated = True
            
            # Sync data from the server
            sync_result = await self.hass.async_add_executor_job(
                self.baby_tracker.sync
            )
            
            if sync_result.get("status") != "success":
                raise UpdateFailed(f"Sync failed: {sync_result.get('message')}")

            # Fetch all babies
            all_babies = await self.hass.async_add_executor_job(
                self.baby_tracker.get_all_babies
            )

            # For backwards compatibility, also get the first baby as "baby_info"
            baby_info = await self.hass.async_add_executor_job(
                self.baby_tracker.get_baby_info
            )

            # Download baby pictures to www/baby_tracker/ folder
            www_dir = self.hass.config.path("www", "baby_tracker")
            baby_pictures = {}
            for baby in all_babies:
                if hasattr(baby, 'picture_name') and baby.picture_name:
                    local_path = await self.hass.async_add_executor_job(
                        self.baby_tracker.download_baby_picture,
                        baby.picture_name,
                        www_dir
                    )
                    if local_path:
                        # Store the URL path for serving via /local/
                        baby_pictures[baby.name] = f"/local/baby_tracker/{baby.picture_name}"
                        _LOGGER.debug(f"Baby picture available at: {baby_pictures[baby.name]}")

            # Create baby-specific data structure
            baby_data = {}

            # Fetch data for each baby
            for baby in all_babies:
                baby_id = baby.object_id
                baby_name = baby.name

                # Fetch all activity data for this baby (pass baby_id where supported)
                feeding_summary = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_feeding_summary, 7, baby_id  # days, baby_id
                )

                diaper_summary = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_diaper_summary, 7, baby_id  # days, baby_id
                )

                last_feeding = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_feeding
                )

                time_since_last_feeding = await self.hass.async_add_executor_job(
                    self.baby_tracker.time_since_last_feeding
                )

                last_temperature = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_temperature
                )

                last_diaper = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_diaper
                )

                last_sleep = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_sleep
                )

                last_nursing = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_nursing
                )

                last_feed_time = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_feed_time
                )

                is_sleeping = await self.hass.async_add_executor_job(
                    self.baby_tracker.is_currently_sleeping
                )

                last_bath = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_bath
                )

                last_pump = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_pump, baby_id
                )

                pump_summary = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_pump_summary, 7, baby_id  # days, baby_id
                )

                last_medicine = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_medicine
                )

                last_growth = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_growth, baby_id
                )

                last_milestone = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_milestone, baby_id
                )

                last_doctor_visit = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_doctor_visit, baby_id
                )

                last_vaccine = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_vaccine, baby_id
                )

                # Store all data for this baby
                baby_data[baby_name] = {
                    "baby_info": baby,
                    "feeding_summary": feeding_summary,
                    "diaper_summary": diaper_summary,
                    "last_feeding": last_feeding,
                    "last_temperature": last_temperature,
                    "time_since_last_feeding": time_since_last_feeding,
                    "last_diaper": last_diaper,
                    "last_sleep": last_sleep,
                    "last_nursing": last_nursing,
                    "last_feed_time": last_feed_time,
                    "is_currently_sleeping": is_sleeping,
                    "last_bath": last_bath,
                    "last_pump": last_pump,
                    "pump_summary": pump_summary,
                    "last_medicine": last_medicine,
                    "last_growth": last_growth,
                    "last_milestone": last_milestone,
                    "last_doctor_visit": last_doctor_visit,
                    "last_vaccine": last_vaccine
                }

            # For backwards compatibility, keep single-baby structure
            # Use first baby's data if available
            if all_babies and len(all_babies) > 0:
                first_baby_name = all_babies[0].name
                first_baby_data = baby_data.get(first_baby_name, {})

                return {
                    "babies": all_babies,
                    "baby_data": baby_data,
                    "baby_pictures": baby_pictures,
                    # Backwards compatibility fields (first baby)
                    "baby_info": baby_info,
                    "feeding_summary": first_baby_data.get("feeding_summary"),
                    "diaper_summary": first_baby_data.get("diaper_summary"),
                    "last_feeding": first_baby_data.get("last_feeding"),
                    "last_temperature": first_baby_data.get("last_temperature"),
                    "time_since_last_feeding": first_baby_data.get("time_since_last_feeding"),
                    "last_diaper": first_baby_data.get("last_diaper"),
                    "last_sleep": first_baby_data.get("last_sleep"),
                    "last_nursing": first_baby_data.get("last_nursing"),
                    "last_feed_time": first_baby_data.get("last_feed_time"),
                    "is_currently_sleeping": first_baby_data.get("is_currently_sleeping"),
                    "last_bath": first_baby_data.get("last_bath"),
                    "last_pump": first_baby_data.get("last_pump"),
                    "pump_summary": first_baby_data.get("pump_summary"),
                    "last_medicine": first_baby_data.get("last_medicine"),
                    "last_growth": first_baby_data.get("last_growth"),
                    "last_milestone": first_baby_data.get("last_milestone"),
                    "last_doctor_visit": first_baby_data.get("last_doctor_visit"),
                    "last_vaccine": first_baby_data.get("last_vaccine")
                }
            else:
                # No babies found
                return {
                    "babies": [],
                    "baby_data": {},
                    "baby_pictures": {},
                    "baby_info": baby_info
                }
        except Exception as err:
            _LOGGER.error("Error updating Baby Tracker data: %s", err)
            raise UpdateFailed(f"Error communicating with Baby Tracker: {err}")