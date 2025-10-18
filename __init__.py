"""Baby Tracker integration for Home Assistant."""
import asyncio
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

PLATFORMS = ["sensor"]


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

    # Set up all platforms for this device/entry
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Close any open connections or resources
        
        # If this is the last entry, unregister services
        if not any(entry_id != "config" for entry_id in hass.data[DOMAIN]):
            await async_unregister_services(hass)
        
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
            
            # Fetch baby info and summaries
            baby_info = await self.hass.async_add_executor_job(
                self.baby_tracker.get_baby_info
            )
            
            feeding_summary = await self.hass.async_add_executor_job(
                self.baby_tracker.get_feeding_summary
            )
            
            diaper_summary = await self.hass.async_add_executor_job(
                self.baby_tracker.get_diaper_summary
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
            
            # Return all data as dictionary
            return {
                "baby_info": baby_info,
                "feeding_summary": feeding_summary,
                "diaper_summary": diaper_summary,
                "last_feeding": last_feeding,
                "last_temperature": last_temperature,
                "time_since_last_feeding": time_since_last_feeding  # Add this line

            }
        except Exception as err:
            _LOGGER.error("Error updating Baby Tracker data: %s", err)
            raise UpdateFailed(f"Error communicating with Baby Tracker: {err}")