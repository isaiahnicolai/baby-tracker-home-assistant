"""Baby Tracker integration for Home Assistant."""
import logging
import os
import uuid
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, CONF_DEVICE_UUID,
    CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM,
    EVENT_FEEDING, EVENT_DIAPER, EVENT_SLEEP,
)
from .client import AuthenticationError
from .client import BabyTracker
from .entity import migrate_to_baby_ids
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = ["sensor", "button", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Baby Tracker component."""
    hass.data.setdefault(DOMAIN, {})
    return True


def get_option(entry: ConfigEntry, key, default):
    """A setting from the options flow, falling back to the original setup data."""
    return entry.options.get(key, entry.data.get(key, default))


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
        scan_interval=timedelta(minutes=get_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        entry=entry,
    )

    # Raises ConfigEntryNotReady (retry later) or ConfigEntryAuthFailed (re-login)
    await coordinator.async_config_entry_first_refresh()

    # Entities used to be keyed by baby name; re-key them by baby ID before
    # the platforms create them, so existing entity IDs are kept
    migrate_to_baby_ids(hass, entry, coordinator.email, coordinator.data.get("babies") or [])

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Settings changed in the options flow take effect on reload
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    # A baby added or renamed in the app needs its entities created/renamed
    coordinator.check_babies_changed()  # record the babies the entities are created for
    entry.async_on_unload(coordinator.async_add_listener(coordinator.check_babies_changed))

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


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


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

    def __init__(self, hass, email, password, device_uuid, db_path, scan_interval, entry):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        self.unit_system = get_option(entry, CONF_UNIT_SYSTEM, DEFAULT_UNIT_SYSTEM)
        self._baby_ids = None  # {name: id} the entities were created with

        # Create Baby Tracker instance
        self.baby_tracker = BabyTracker(
            db_path=db_path,
            time_zone=hass.config.time_zone,
            tz=dt_util.get_default_time_zone(),
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

    def baby_id_for(self, baby_name):
        """The ID of the baby with this name (entities are created per baby name)."""
        for baby in (self.data or {}).get("babies") or []:
            if baby.name == baby_name:
                return baby.object_id
        raise ValueError(f"Unknown baby: {baby_name}")

    def check_babies_changed(self):
        """Reload when the app's babies change, so entities match them."""
        babies = {b.name: b.object_id for b in (self.data or {}).get("babies") or []}
        if self._baby_ids is None:
            self._baby_ids = babies
        elif babies and babies != self._baby_ids:
            _LOGGER.info("Babies changed in Baby Tracker; reloading to update entities")
            self._baby_ids = babies
            self.hass.async_create_task(self.hass.config_entries.async_reload(self.config_entry.entry_id))

    def _fetch(self, www_dir):
        """
        Sync and read everything for one refresh. Runs in a single executor
        job rather than one per query.
        """
        tracker = self.baby_tracker
        sync_result = tracker.sync()
        if sync_result.get("status") != "success":
            raise UpdateFailed(f"Sync failed: {sync_result.get('message')}")

        all_babies = tracker.get_all_babies()
        # For backwards compatibility, also get the first baby as "baby_info"
        baby_info = tracker.get_baby_info()

        # Baby pictures are saved to www/baby_tracker/ and served via /local/
        baby_pictures = {}
        for baby in all_babies:
            if baby.picture_name and tracker.download_baby_picture(baby.picture_name, www_dir):
                baby_pictures[baby.name] = f"/local/baby_tracker/{baby.picture_name}"

        baby_data = {}
        for baby in all_babies:
            baby_id = baby.object_id
            baby_data[baby.name] = {
                "baby_info": baby,
                "feeding_summary": tracker.get_feeding_summary(7, baby_id),
                "diaper_summary": tracker.get_diaper_summary(7, baby_id),
                "last_feeding": tracker.get_last_feeding(baby_id),
                "last_temperature": tracker.get_last_temperature(baby_id),
                "time_since_last_feeding": tracker.time_since_last_feeding(baby_id),
                "last_diaper": tracker.get_last_diaper(baby_id),
                "last_sleep": tracker.get_last_sleep(baby_id),
                "last_nursing": tracker.get_last_nursing(baby_id),
                "last_feed_time": tracker.get_last_feed_time(baby_id),
                "is_currently_sleeping": tracker.is_currently_sleeping(baby_id),
                "last_bath": tracker.get_last_bath(baby_id),
                "last_pump": tracker.get_last_pump(baby_id),
                "pump_summary": tracker.get_pump_summary(7, baby_id),
                "last_medicine": tracker.get_last_medicine(baby_id),
                "last_growth": tracker.get_last_growth(baby_id),
                "last_milestone": tracker.get_last_milestone(baby_id),
                "last_doctor_visit": tracker.get_last_doctor_visit(baby_id),
                "last_vaccine": tracker.get_last_vaccine(baby_id),
                "today_wet_count": tracker.get_today_wet_diaper_count(baby_id),
                "daily_summary": tracker.get_daily_summary(baby_id),
                "sleep_analysis": tracker.get_sleep_analysis(baby_id, 14),
            }

        return all_babies, baby_info, baby_pictures, baby_data

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

            all_babies, baby_info, baby_pictures, baby_data = await self.hass.async_add_executor_job(
                self._fetch, self.hass.config.path("www", "baby_tracker")
            )

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
        except AuthenticationError as err:
            # Credentials rejected: ask the user to log in again
            self.authenticated = False
            raise ConfigEntryAuthFailed(str(err)) from err
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error updating Baby Tracker data: %s", err)
            raise UpdateFailed(f"Error communicating with Baby Tracker: {err}")