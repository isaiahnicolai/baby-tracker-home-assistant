"""Baby Tracker integration for Home Assistant."""
import logging
import os
import uuid
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, CONF_DEVICE_UUID,
    EVENT_FEEDING, EVENT_DIAPER, EVENT_SLEEP,
)
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

PLATFORMS = ["sensor", "button", "binary_sensor"]


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

    device_uuid = config.get(CONF_DEVICE_UUID)
    if not device_uuid:
        # Entries created before this was stored borrowed another device's
        # identity (usually a phone). Give this install its own, and rebuild
        # the local database since its per-device sync progress can't be trusted.
        _LOGGER.warning("Registering Baby Tracker as its own sync device; local data will be re-downloaded")
        device_uuid = str(uuid.uuid4())
        hass.config_entries.async_update_entry(entry, data={**config, CONF_DEVICE_UUID: device_uuid})
        await hass.async_add_executor_job(_remove_database, db_path)

    # Create the data coordinator
    coordinator = BabyTrackerDataCoordinator(
        hass,
        email=config[CONF_EMAIL],
        password=config[CONF_PASSWORD],
        device_uuid=device_uuid,
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
        hass.data[DOMAIN].pop(entry.entry_id)

        # If this is the last entry, unregister services
        if not any(entry_id != "config" for entry_id in hass.data[DOMAIN]):
            await async_unregister_services(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Delete the local database when the integration is removed (not on reload)."""
    db_path = os.path.join(hass.config.path(), "baby_tracker.db")
    await hass.async_add_executor_job(_remove_database, db_path)


def _remove_database(db_path):
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            _LOGGER.info(f"Deleted Baby Tracker database at: {db_path}")
        except OSError as e:
            _LOGGER.error(f"Failed to delete database at {db_path}: {e}")


class BabyTrackerDataCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Baby Tracker."""

    def __init__(self, hass, email, password, device_uuid, db_path, scan_interval):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        
        # Create Baby Tracker instance
        self.baby_tracker = BabyTracker(
            db_path=db_path,
            time_zone=hass.config.time_zone
        )
        self.email = email
        self.password = password
        self.device_uuid = device_uuid
        self.authenticated = False
        self.db_path = db_path
        self.alert_dismiss_state = {}
        self._alert_entities = []
        self._previous_data = None  # None until the first refresh, so startup fires no events
        _LOGGER.info(f"Initialized Baby Tracker coordinator with database at: {db_path}")

    async def _async_update_data(self):
        """Fetch data from Baby Tracker."""
        try:
            # Run authentication in an executor
            if not self.authenticated:
                auth_result = await self.hass.async_add_executor_job(
                    self.baby_tracker.authenticate, self.email, self.password, self.device_uuid
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
                    self.baby_tracker.get_last_feeding, baby_id
                )

                time_since_last_feeding = await self.hass.async_add_executor_job(
                    self.baby_tracker.time_since_last_feeding, baby_id
                )

                last_temperature = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_temperature, baby_id
                )

                last_diaper = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_diaper, baby_id
                )

                last_sleep = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_sleep, baby_id
                )

                last_nursing = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_nursing, baby_id
                )

                last_feed_time = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_feed_time, baby_id
                )

                is_sleeping = await self.hass.async_add_executor_job(
                    self.baby_tracker.is_currently_sleeping, baby_id
                )

                last_bath = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_bath, baby_id
                )

                last_pump = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_pump, baby_id
                )

                pump_summary = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_pump_summary, 7, baby_id  # days, baby_id
                )

                last_medicine = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_last_medicine, baby_id
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

                today_wet_count = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_today_wet_diaper_count, baby_id
                )

                daily_summary = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_daily_summary, baby_id
                )

                sleep_analysis = await self.hass.async_add_executor_job(
                    self.baby_tracker.get_sleep_analysis, baby_id, 14
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
                    "last_vaccine": last_vaccine,
                    "today_wet_count": today_wet_count,
                    "daily_summary": daily_summary,
                    "sleep_analysis": sleep_analysis,
                }

            # Fire events for detected changes (skipped on the first refresh,
            # when everything would look new)
            babies_by_name = {baby.name: baby for baby in all_babies}
            for baby_name, current in (baby_data.items() if self._previous_data is not None else []):
                prev = self._previous_data.get(baby_name, {})
                baby_id = babies_by_name[baby_name].object_id

                # Feeding change: compare last_feeding time
                curr_feed_time = (current.get("last_feeding") or {}).get("time")
                prev_feed_time = (prev.get("last_feeding") or {}).get("time")
                if curr_feed_time and curr_feed_time != prev_feed_time:
                    self.hass.bus.async_fire(EVENT_FEEDING, {
                        "baby_name": baby_name,
                        "baby_id": baby_id,
                        "type": (current.get("last_feeding") or {}).get("type"),
                        "time": curr_feed_time,
                    })

                # Diaper change: compare last_diaper time
                curr_diaper_time = (current.get("last_diaper") or {}).get("time")
                prev_diaper_time = (prev.get("last_diaper") or {}).get("time")
                if curr_diaper_time and curr_diaper_time != prev_diaper_time:
                    self.hass.bus.async_fire(EVENT_DIAPER, {
                        "baby_name": baby_name,
                        "baby_id": baby_id,
                        "status": (current.get("last_diaper") or {}).get("status"),
                        "time": curr_diaper_time,
                    })

                # Sleep change: compare last_sleep time or status
                curr_sleep = current.get("last_sleep") or {}
                prev_sleep = prev.get("last_sleep") or {}
                if (curr_sleep.get("time") != prev_sleep.get("time") or
                        curr_sleep.get("is_sleeping") != prev_sleep.get("is_sleeping")):
                    self.hass.bus.async_fire(EVENT_SLEEP, {
                        "baby_name": baby_name,
                        "baby_id": baby_id,
                        "is_sleeping": curr_sleep.get("is_sleeping"),
                        "time": curr_sleep.get("time"),
                    })

            self._previous_data = {k: dict(v) for k, v in baby_data.items()}

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