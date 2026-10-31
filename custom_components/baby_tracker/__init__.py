"""Baby Tracker integration for Home Assistant."""
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import AccountResetError, AuthenticationError, BabyTracker
from .client.dbconn import remove_sidecar_files
from .const import (
    BUTTON_DEBOUNCE_SECONDS,
    CALENDAR_LOOKBACK_DAYS,
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_SYSTEM,
    CONFIG_ENTRY_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_SYSTEM,
    DOMAIN,
    EVENT_DIAPER,
    EVENT_FEEDING,
    EVENT_SLEEP,
    ISSUE_ACCOUNT_RESET,
    ISSUE_OLD_WWW_FOLDER,
    ISSUE_UPLOADS_PENDING,
    NURSING_STORE_VERSION,
    NURSING_TIMER_MAX_AGE_HOURS,
    PHOTO_DIR_NAME,
    UPLOADS_PENDING_REFRESHES,
    activity_signal,
)
from .entity import migrate_to_baby_ids, remove_retired_entities
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = ["sensor", "button", "binary_sensor", "image", "calendar", "event", "number", "select"]


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

    # Create the data coordinator
    coordinator = BabyTrackerDataCoordinator(
        hass,
        email=config[CONF_EMAIL],
        password=config[CONF_PASSWORD],
        device_uuid=config[CONF_DEVICE_UUID],
        db_path=db_path,
        scan_interval=timedelta(minutes=get_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        entry=entry,
    )

    # Older versions saved photos under www/, where anyone on the network can fetch them without a login
    legacy_photo_dir = hass.config.path("www", "baby_tracker")
    if await hass.async_add_executor_job(os.path.isdir, legacy_photo_dir):
        _LOGGER.info("Old baby photo copies are still in %s; see Settings > Repairs", legacy_photo_dir)
        ir.async_create_issue(
            hass, DOMAIN, ISSUE_OLD_WWW_FOLDER,
            is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_OLD_WWW_FOLDER, translation_placeholders={"folder": legacy_photo_dir},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_OLD_WWW_FOLDER)

    # A nursing session timed before a restart or reload carries on
    await coordinator.async_load_nursing()

    # Raises ConfigEntryNotReady (retry later) or ConfigEntryAuthFailed (re-login)
    await coordinator.async_config_entry_first_refresh()

    # Entities used to be keyed by baby name; re-key them by baby ID before
    # the platforms create them, so existing entity IDs are kept
    migrate_to_baby_ids(hass, entry, coordinator.email, coordinator.data.get("babies") or [])
    remove_retired_entities(hass, entry)

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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring a config entry made by an older version up to the current one."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False  # made by a newer version; can't be downgraded

    if entry.version == 1:
        # Version 2: every entry has its own device identity on the sync server
        data = dict(entry.data)
        if not data.get(CONF_DEVICE_UUID):
            # Entries created before this was stored borrowed another device's
            # identity (usually a phone). Give this install its own, and rebuild
            # the local database since its per-device sync progress can't be trusted.
            _LOGGER.warning("Registering Baby Tracker as its own sync device; local data will be re-downloaded")
            data[CONF_DEVICE_UUID] = str(uuid.uuid4())
            await hass.async_add_executor_job(_remove_database, os.path.join(hass.config.path(), "baby_tracker.db"))
        hass.config_entries.async_update_entry(entry, data=data, version=2, minor_version=1)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_save_nursing()

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
    await Store(hass, NURSING_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.nursing").async_remove()
    for issue_id in (ISSUE_OLD_WWW_FOLDER, ISSUE_UPLOADS_PENDING, ISSUE_ACCOUNT_RESET):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _remove_database(db_path):
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            remove_sidecar_files(db_path)
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
        # Baby and activity photos are kept here, not under www, so nothing is served without a login
        self.photo_dir = hass.config.path(PHOTO_DIR_NAME)
        self.picture_dir = os.path.join(self.photo_dir, "pictures")
        self.last_sync_result = None  # what the last sync reported, for diagnostics
        self.pending_uploads = None  # records logged here that the server hasn't received yet
        self.fetched_at = None  # when the data was last read, so time-based entities can keep it current
        self._refreshes_with_pending = 0  # consecutive refreshes that ended with records still unsent
        # What the number/select entities are set to, by baby ID: bottle_size, bottle_type,
        # medicine, medicine_amount and tummy_time_minutes. The buttons read them.
        self.controls = {}
        # Running nursing timers by baby ID (not in the app's database; kept in HA's storage so a
        # restart or reload doesn't lose a session in progress)
        self.nursing_timers = {}
        self._nursing_store = Store(hass, NURSING_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.nursing")
        self._button_presses = {}  # when each button last finished successfully (monotonic seconds)
        self._pressing = set()  # buttons being handled right now
        _LOGGER.info(f"Initialized Baby Tracker coordinator with database at: {db_path}")

    # ----- per-baby controls -----

    def control(self, baby_id, key, default=None):
        """The value a baby's number/select control is set to."""
        return self.controls.get(baby_id, {}).get(key, default)

    def set_control(self, baby_id, key, value):
        self.controls.setdefault(baby_id, {})[key] = value

    @property
    def medicine_names(self):
        """The names of the account's medicines, as the Medicine select offers them."""
        return [m["name"] for m in (self.data or {}).get("medicines") or [] if m.get("name")]

    def selected_medicine(self, baby_id):
        """The medicine chosen for a baby, else the first one (None when the account has none)."""
        names = self.medicine_names
        chosen = self.control(baby_id, "medicine")
        return chosen if chosen in names else (names[0] if names else None)

    # ----- buttons -----

    def is_repeat_press(self, key):
        """
        True if this button is still being handled, or was pressed successfully less than
        BUTTON_DEBOUNCE_SECONDS ago, so a double tap (or an automation firing twice)
        doesn't log a record twice. A press that goes ahead must be closed with finish_press.
        """
        last = self._button_presses.get(key)
        if key in self._pressing or (last is not None and time.monotonic() - last < BUTTON_DEBOUNCE_SECONDS):
            _LOGGER.info("Ignoring a repeat press of %s within %s seconds", key, BUTTON_DEBOUNCE_SECONDS)
            return True
        self._pressing.add(key)
        return False

    def finish_press(self, key, succeeded):
        """
        A press that is_repeat_press let through is over. Only one that worked starts the
        debounce window: after a failure the user can press again straight away.
        """
        self._pressing.discard(key)
        if succeeded:
            self._button_presses[key] = time.monotonic()

    # ----- nursing timer -----

    def start_nursing(self, baby_id, side):
        """
        Start timing a nursing session on a side ("left" or "right"). If one is
        already running on the other side, the time so far is kept and timing
        carries on with this side.
        """
        now = dt_util.utcnow()
        timer = self.nursing_timers.get(baby_id)
        if timer is None:
            self.nursing_timers[baby_id] = {
                "side": side, "started_at": now, "segment_started_at": now,
                "seconds": {"left": 0.0, "right": 0.0},
            }
        elif timer["side"] != side:
            timer["seconds"][timer["side"]] += (now - timer["segment_started_at"]).total_seconds()
            timer.update(side=side, segment_started_at=now)
        else:
            return
        self._save_nursing()
        self.async_update_listeners()

    def _nursing_payload(self):
        """The running timers as storable data (times as text)."""
        return {
            baby_id: {
                "side": timer["side"],
                "started_at": timer["started_at"].isoformat(),
                "segment_started_at": timer["segment_started_at"].isoformat(),
                "seconds": timer["seconds"],
            }
            for baby_id, timer in self.nursing_timers.items()
        }

    def _save_nursing(self):
        """Save the timers soon (a start, switch or end is rare enough to write straight away)."""
        self._nursing_store.async_delay_save(self._nursing_payload, 0)

    async def async_save_nursing(self):
        """Save the timers now (before an unload or reload)."""
        await self._nursing_store.async_save(self._nursing_payload())

    async def async_load_nursing(self):
        """Pick up the timers that were running before a restart or reload."""
        try:
            stored = await self._nursing_store.async_load() or {}
            cutoff = dt_util.utcnow() - timedelta(hours=NURSING_TIMER_MAX_AGE_HOURS)
            timers = {}
            for baby_id, timer in stored.items():
                started_at = dt_util.parse_datetime(timer["started_at"])
                segment_started_at = dt_util.parse_datetime(timer["segment_started_at"])
                if started_at is None or segment_started_at is None or started_at < cutoff:
                    continue
                timers[baby_id] = {
                    "side": timer["side"], "started_at": started_at, "segment_started_at": segment_started_at,
                    "seconds": {"left": float(timer["seconds"]["left"]), "right": float(timer["seconds"]["right"])},
                }
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Ignoring the saved nursing timers, which could not be read: %s", err)
            return
        self.nursing_timers = timers

    def nursing_totals(self, baby_id):
        """
        What a running session has come to, as {"left": minutes, "right": minutes, "side": the
        side now being timed, "started_at": datetime}, or None when no timer is running.
        Minutes are whole; a session too short to round up still counts one minute.
        """
        timer = self.nursing_timers.get(baby_id)
        if timer is None:
            return None
        seconds = dict(timer["seconds"])
        seconds[timer["side"]] += (dt_util.utcnow() - timer["segment_started_at"]).total_seconds()
        minutes = {side: round(value / 60) for side, value in seconds.items()}
        if not any(minutes.values()):
            minutes[timer["side"]] = 1
        return {**minutes, "side": timer["side"], "started_at": timer["started_at"]}

    def clear_nursing(self, baby_id):
        if self.nursing_timers.pop(baby_id, None) is not None:
            self._save_nursing()
            self.async_update_listeners()

    # ----- repairs -----

    def _track_uploads(self):
        """Raise a repair when records stay unsent for several refreshes in a row, clear it when they go."""
        if self.pending_uploads is None:
            return
        self._refreshes_with_pending = self._refreshes_with_pending + 1 if self.pending_uploads else 0
        if self._refreshes_with_pending > UPLOADS_PENDING_REFRESHES:
            ir.async_create_issue(
                self.hass, DOMAIN, ISSUE_UPLOADS_PENDING,
                is_fixable=False, severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_UPLOADS_PENDING,
                translation_placeholders={"count": str(self.pending_uploads)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_UPLOADS_PENDING)

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

    @staticmethod
    def _insights_for(tracker, baby):
        """One baby's insights, or {} so a bad record never breaks the whole refresh."""
        try:
            return tracker.get_insights(baby.object_id) or {}
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Insights for %s unavailable: %s", baby.name, err, exc_info=True)
            return {}

    @staticmethod
    def _derived(what, default, call, *args):
        """One derived answer (next breast, next dose...), or the default so a bad record never breaks the refresh."""
        try:
            return call(*args)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("%s unavailable: %s", what, err, exc_info=True)
            return default

    def _latest_event(self, tracker, baby_id, now):
        """The most recent thing that happened for a baby (for the calendar's current event), or None."""
        events = self._derived(
            "Recent events", [], tracker.get_events_between,
            baby_id, now - timedelta(days=CALENDAR_LOOKBACK_DAYS), now + timedelta(minutes=1))
        return next((event for event in reversed(events) if event["start"] <= now), None)

    def _fetch(self, photo_dir):
        """
        Sync and read everything for one refresh. Runs in a single executor
        job rather than one per query.
        """
        tracker = self.baby_tracker
        # Activity pictures go to the private photo directory's pictures/ folder
        sync_result = tracker.sync(picture_dir=os.path.join(photo_dir, "pictures"))
        self.last_sync_result = {
            key: value.isoformat() if isinstance(value, datetime) else value for key, value in sync_result.items()
        }
        self.pending_uploads = tracker.pending_upload_count()
        if not tracker.is_authenticated:
            # The tracker lost its session (a failed force resync): authenticate again next refresh
            self.authenticated = False
        if sync_result.get("status") != "success":
            raise UpdateFailed(f"Sync failed: {sync_result.get('message')}")

        all_babies = tracker.get_all_babies()
        # For backwards compatibility, also get the first baby as "baby_info"
        baby_info = tracker.get_baby_info()

        # Baby pictures are saved in the private photo directory, and served
        # only by the image entities
        baby_pictures = {}
        for baby in all_babies:
            if not baby.picture_name:
                continue
            saved = tracker.download_baby_picture(baby.picture_name, photo_dir)
            if saved:
                # The file may have gained a .jpg extension
                baby_pictures[baby.name] = {
                    "path": saved,
                    "updated": dt_util.utc_from_timestamp(os.path.getmtime(saved)),
                }

        baby_data = {}
        now = dt_util.utcnow()
        for baby in all_babies:
            baby_id = baby.object_id
            baby_data[baby.name] = {
                "baby_info": baby,
                "feeding_summary": tracker.get_feeding_summary(7, baby_id),
                "diaper_summary": self._derived("Diaper summary", None, tracker.get_diaper_summary, 7, baby_id),
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
                "last_activity": tracker.get_last_activity(baby_id),
                "today_wet_count": tracker.get_today_wet_diaper_count(baby_id),
                "daily_summary": tracker.get_daily_summary(baby_id),
                "sleep_analysis": tracker.get_sleep_analysis(baby_id, 14),
                "insights": self._insights_for(tracker, baby),
                "next_breast": self._derived("Next breast", {}, tracker.get_next_breast),
                "next_medicine_dose": self._derived("Next medicine dose", None, tracker.get_next_medicine_dose, baby_id),
                "upcoming_milestones": self._derived("Upcoming milestones", [], tracker.get_upcoming_milestones, baby_id),
                "upcoming_vaccines": self._derived("Upcoming vaccines", [], tracker.get_upcoming_vaccines, baby_id),
                "last_event": self._latest_event(tracker, baby_id, now),
            }

        account = {
            "pumped_milk_inventory": self._derived("Milk inventory", None, tracker.get_pumped_milk_inventory),
            "pending_uploads": self.pending_uploads,
        }
        # The account's medicines, for the Medicine select (shared by all babies)
        medicines = self._derived("Medicine selections", [], tracker.get_medicine_selections)

        return all_babies, baby_info, baby_pictures, baby_data, account, medicines

    def _announce(self, activity, baby_name, baby_id, details, bus_event=None):
        """Tell the baby's Activity event entity, and the event bus where an event is named for it."""
        payload = {"baby_name": baby_name, "baby_id": baby_id, **details}
        if bus_event:
            self.hass.bus.async_fire(bus_event, payload)
        async_dispatcher_send(self.hass, activity_signal(self.config_entry.entry_id), baby_name, activity, payload)

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

            try:
                all_babies, baby_info, baby_pictures, baby_data, account, medicines = await self.hass.async_add_executor_job(
                    self._fetch, self.photo_dir
                )
            finally:
                self._track_uploads()
            self.fetched_at = dt_util.utcnow()
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ACCOUNT_RESET)  # a sync got through

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
                    self._announce("feeding", baby_name, baby_id, {
                        "type": (current.get("last_feeding") or {}).get("type"),
                        "time": curr_feed_time,
                    }, EVENT_FEEDING)

                # Diaper change: compare last_diaper time
                curr_diaper_time = (current.get("last_diaper") or {}).get("time")
                prev_diaper_time = (prev.get("last_diaper") or {}).get("time")
                if curr_diaper_time and curr_diaper_time != prev_diaper_time:
                    self._announce("diaper", baby_name, baby_id, {
                        "status": (current.get("last_diaper") or {}).get("status"),
                        "time": curr_diaper_time,
                    }, EVENT_DIAPER)

                # Sleep change: compare last_sleep time or status
                curr_sleep = current.get("last_sleep") or {}
                prev_sleep = prev.get("last_sleep") or {}
                if (curr_sleep.get("time") != prev_sleep.get("time") or
                        curr_sleep.get("is_sleeping") != prev_sleep.get("is_sleeping")):
                    self._announce("sleep_start" if curr_sleep.get("is_sleeping") else "sleep_end",
                                   baby_name, baby_id, {
                        "is_sleeping": curr_sleep.get("is_sleeping"),
                        "time": curr_sleep.get("time"),
                    }, EVENT_SLEEP)

                # Baths and medicines are only reported by the Activity event entity
                curr_bath = current.get("last_bath") or {}
                if curr_bath.get("time") and curr_bath.get("time") != (prev.get("last_bath") or {}).get("time"):
                    self._announce("bath", baby_name, baby_id, {
                        "bath_type": curr_bath.get("bath_type"), "time": curr_bath.get("time")})

                curr_medicine = current.get("last_medicine") or {}
                if curr_medicine.get("time") and curr_medicine.get("time") != (prev.get("last_medicine") or {}).get("time"):
                    self._announce("medicine", baby_name, baby_id, {
                        "medicine_name": curr_medicine.get("medicine_name"),
                        "amount": curr_medicine.get("amount"),
                        "unit": curr_medicine.get("unit"),
                        "time": curr_medicine.get("time"),
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
                    "account": account,
                    "medicines": medicines,
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
                    "account": account,
                    "medicines": medicines,
                    "baby_info": baby_info
                }
        except AuthenticationError as err:
            # Credentials rejected: ask the user to log in again
            self.authenticated = False
            raise ConfigEntryAuthFailed(str(err)) from err
        except AccountResetError as err:
            # Not a bad password: the group was reset, and our data belongs to the old one
            _LOGGER.error(
                "Baby Tracker account was reset or recreated, so syncing has stopped: %s. "
                "Press the Force Resync button (or call the force_resync service) to rejoin the group.", err)
            ir.async_create_issue(
                self.hass, DOMAIN, ISSUE_ACCOUNT_RESET,
                is_fixable=False, severity=ir.IssueSeverity.ERROR, translation_key=ISSUE_ACCOUNT_RESET,
            )
            raise UpdateFailed(f"Account was reset; use Force Resync to rejoin: {err}") from err
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error updating Baby Tracker data: %s", err)
            raise UpdateFailed(f"Error communicating with Baby Tracker: {err}") from err
