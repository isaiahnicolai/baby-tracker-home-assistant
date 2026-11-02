"""Services for Baby Tracker integration."""
import contextlib
import logging
from functools import partial
import os
import uuid

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    ALERT_TYPE_FEED_DUE,
    ALERT_TYPE_FEEDING_OVERDUE,
    ALERT_TYPE_FEVER,
    ALERT_TYPE_INTAKE_LOW,
    ALERT_TYPE_LONG_SLEEP,
    ALERT_TYPE_LOW_WET_DIAPERS,
    ALERT_TYPE_NO_POOP,
    ALERT_TYPE_SLEEP_DUE,
    ALERT_TYPE_WAKE_OVERDUE,
    ALERT_TYPE_WAKE_TO_FEED,
    ATTACHABLE_RECORD_TYPES,
    DEFAULT_UNIT_SYSTEM,
    DELETABLE_RECORD_TYPES,
    DOMAIN,
    EVENT_UNDO,
    NOTHING_TO_UNDO,
    UNDO_WINDOW_HOURS,
    UNIT_SYSTEM_IMPERIAL,
)

_LOGGER = logging.getLogger(__name__)

# Fields every service that logs a record takes: which baby, and when it happened
# (the time a record is dated at; without it, now)
RECORD_FIELDS = {
    vol.Optional("baby_name"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Optional("time"): cv.datetime,
}

# Service schemas
DIAPER_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("pee", default=True): cv.boolean,
    vol.Optional("poo", default=False): cv.boolean,
    # 5 = "not set", as the app uses when no color/texture is recorded
    vol.Optional("pee_color", default=5): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("poo_color", default=5): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("texture", default=5): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("amount", default=2): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("note", default=""): cv.string,
})

NURSING_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("left_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("right_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("both_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("finish_side", default="Left"): vol.In(["Left", "Right", "Both"]),
    vol.Optional("note", default=""): cv.string,
})

FORMULA_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

PUMPED_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_measure"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

TEMPERATURE_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("temperature"): vol.All(vol.Coerce(float)),
    vol.Optional("is_fahrenheit"): cv.boolean,  # defaults to the integration's unit setting
    vol.Optional("note", default=""): cv.string,
})

BATH_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("bath_type"): vol.Any(None, vol.In(["Bubble Bath", "Sponge Bath", "Shower", "Washed Hair"])),
    vol.Optional("note", default=""): cv.string,
})

PUMP_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("left_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("right_duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
    vol.Optional("left_amount", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("right_amount", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("is_english_scale"): cv.boolean,  # defaults to the integration's unit setting
    vol.Optional("note", default=""): cv.string,
})

MEDICINE_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("medicine_name"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("create", default=False): cv.boolean,  # create the medicine when the account has none of that name
    vol.Optional("note", default=""): cv.string,
})

CREATE_MEDICINE_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("amount", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),  # the usual dose per time
    vol.Optional("unit", default=""): cv.string,
    vol.Optional("interval_hours", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("prescription", default=False): cv.boolean,
})

CREATE_FOOD_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("is_bottle", default=False): cv.boolean,
})

SLEEP_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("is_start"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

GROWTH_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("weight", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("length", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("head", default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    # Both default to the integration's unit setting
    vol.Optional("is_english_weight_scale"): cv.boolean,
    vol.Optional("is_english_length_scale"): cv.boolean,
    vol.Optional("note", default=""): cv.string,
})

MILESTONE_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("milestone_name"): cv.string,
    vol.Optional("note", default=""): cv.string,
})

DOCTOR_VISIT_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("is_appointment", default=True): cv.boolean,
    vol.Optional("visit_type", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("note", default=""): cv.string,
    vol.Optional("doctor_note", default=""): cv.string,
    vol.Optional("symptom", default=""): cv.string,
})

VACCINE_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("vaccine_name"): cv.string,
    vol.Optional("note", default=""): cv.string,
})

ACTIVITY_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("activity_name", default="Tummy Time"): cv.string,
    vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=720)),  # minutes
    vol.Optional("note", default=""): cv.string,
})

SOLIDS_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Required("food_name"): cv.string,  # a food in the app's solids list, e.g. "Banana"
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("unit", default=""): cv.string,  # e.g. "tbsp"
    vol.Optional("is_english_measure"): cv.boolean,  # defaults to the integration's unit setting
    vol.Optional("create", default=False): cv.boolean,  # create the food when the account has none of that name
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
        ALERT_TYPE_INTAKE_LOW,
        ALERT_TYPE_FEED_DUE,
        ALERT_TYPE_WAKE_TO_FEED,
        ALERT_TYPE_SLEEP_DUE,
        ALERT_TYPE_WAKE_OVERDUE,
    ]),
})

DISMISS_ALL_ALERTS_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
})

UNDO_LAST_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Optional("within_hours", default=UNDO_WINDOW_HOURS): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
})

DELETE_RECORD_SCHEMA = vol.Schema({
    # Only used to say which baby's Activity event the deletion is reported on
    vol.Optional("baby_name"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Required("object_type"): vol.In(DELETABLE_RECORD_TYPES),
    vol.Required("object_id"): cv.string,
})

# Where a photo comes from: a file, or a snapshot of an image or camera entity (at most one)
PHOTO_FIELDS = {
    vol.Optional("photo"): cv.string,
    vol.Optional("image_entity"): cv.entity_domain("image"),
    vol.Optional("camera_entity"): cv.entity_domain("camera"),
}

LOG_JOY_SCHEMA = vol.Schema({
    **RECORD_FIELDS,
    vol.Optional("note", default=""): cv.string,
    **PHOTO_FIELDS,
})

ATTACH_PHOTO_SCHEMA = vol.Schema({
    # Only used to say which baby's data to refresh; the entry is found by its type and ID
    vol.Optional("baby_name"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Required("object_type"): vol.In(ATTACHABLE_RECORD_TYPES),
    vol.Required("object_id"): cv.string,
    **PHOTO_FIELDS,
})

SNAPSHOT_DIR_NAME = "snapshots"  # under the integration's private folder; snapshots only live there briefly


# Android NursingFinishSide: NotSet=0, Left=1, Right=2 ("Both" has no finish side)
NURSING_FINISH_SIDES = {"Both": 0, "Left": 1, "Right": 2}


# ----- writes shared by the services, the buttons and the Assist intents -----
# Each one writes in an executor job, raises HomeAssistantError if the write failed, and then asks for
# a (debounced) refresh so the entities pick the record up.

def get_coordinator(hass: HomeAssistant):
    """The data coordinator of the (first) configured entry."""
    for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
        if entry_id != "config":
            return coordinator
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entry")


def check_result(result, what):
    """Raise if a core write reported failure, so the caller sees the error."""
    ok = result.get("status") == "success" if isinstance(result, dict) else bool(result)
    if not ok:
        message = result.get("message") if isinstance(result, dict) else None
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="action_failed",
            translation_placeholders={"action": what, "error": message or "unknown error"},
        )


def sync_time_str(moment):
    """A time in the sync format, "2026-03-01 09:30:00 +0000" (None for now)."""
    return dt_util.as_utc(moment).strftime("%Y-%m-%d %H:%M:%S +0000") if moment else None


async def async_log_diaper(
    hass, coordinator, baby_id, pee=True, poo=False, *, time_str=None, pee_color=5, poo_color=5,
    texture=5, amount=2, note="",
):
    """Log a diaper change (neither pee nor poo is a dry diaper)."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_diaper, baby_id, time_str, pee, poo, pee_color, poo_color, texture, amount, note,
    )
    check_result(result, "add diaper")
    await coordinator.async_request_refresh()


async def async_log_bottle(hass, coordinator, baby_id, amount, is_english, *, pumped=False, time_str=None, note=""):
    """Log a bottle of formula, or of pumped milk, in oz (is_english) or mL."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_pumped if pumped else coordinator.baby_tracker.add_formula,
        baby_id, time_str, amount, is_english, note,
    )
    check_result(result, "add pumped milk" if pumped else "add formula")
    await coordinator.async_request_refresh()


async def async_log_sleep(hass, coordinator, baby_id, is_start, *, note="", moment=None):
    """Log the start of a sleep, or the end of the one in progress."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.log_sleep_event, baby_id, is_start, note, dt_util.as_utc(moment) if moment else None,
    )
    check_result(result, "start sleep" if is_start else "end sleep")
    await coordinator.async_request_refresh()


async def async_log_temperature(hass, coordinator, baby_id, temperature, is_fahrenheit, *, time_str=None, note=""):
    """Log a temperature reading in F (is_fahrenheit) or C."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_temperature, baby_id, time_str, temperature, is_fahrenheit, note,
    )
    check_result(result, "add temperature")
    await coordinator.async_request_refresh()


async def async_log_nursing(
    hass, coordinator, baby_id, *, left=0, right=0, both=0, finish_side="Left", time_str=None, note="",
):
    """Log a nursing session; finish_side is "Left", "Right" or "Both"."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_nursing, baby_id, time_str, left, right, both,
        NURSING_FINISH_SIDES.get(finish_side, 1), note,
    )
    check_result(result, "add nursing")
    await coordinator.async_request_refresh()


async def async_end_nursing(hass, coordinator, baby_id, note=""):
    """
    Log the running nursing timer as a session, dated when it started, then stop the timer.
    Returns the totals it logged (see the coordinator's nursing_totals).
    """
    totals = coordinator.nursing_totals(baby_id)
    if totals is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_nursing_timer")
    await async_log_nursing(
        hass, coordinator, baby_id,
        left=min(totals["left"], 120), right=min(totals["right"], 120),
        finish_side=totals["side"].capitalize(), time_str=sync_time_str(totals["started_at"]), note=note,
    )
    # Only once it is logged; if that failed, the timer keeps running so it can be ended again
    coordinator.clear_nursing(baby_id)
    return totals


def _is_under(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _checked_photo_path(hass, coordinator, path):
    """
    A photo file the caller may use, as a real path. Blocking: runs in the executor.

    Only the integration's own folder (config/baby_tracker), www and media qualify, and www and
    media must also be in Home Assistant's allowed paths; anything else could be used to send
    any file on the machine to the Baby Tracker server.
    """
    real = os.path.realpath(path)
    own = os.path.realpath(coordinator.photo_dir)
    shared = [os.path.realpath(hass.config.path(name)) for name in ("www", "media")]
    allowed = _is_under(real, own) or (
        any(_is_under(real, folder) for folder in shared) and hass.config.is_allowed_path(real))
    if not allowed:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="photo_path_not_allowed",
            translation_placeholders={"path": path})
    if not os.path.isfile(real):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="photo_not_found", translation_placeholders={"path": path})
    return real


async def _entity_snapshot(hass, data):
    """The bytes of an image entity's current picture or a camera's snapshot."""
    # Imported here: they pull in the web server and are only needed for snapshots
    from homeassistant.components import camera

    if data.get("camera_entity"):
        entity_id = data["camera_entity"]
        try:
            return (await camera.async_get_image(hass, entity_id)).content
        except (HomeAssistantError, TimeoutError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="photo_snapshot_failed",
                translation_placeholders={"entity_id": entity_id, "error": str(err) or type(err).__name__},
            ) from err
    entity_id = data["image_entity"]
    component = hass.data.get("image")
    entity = component.get_entity(entity_id) if component else None
    content = None
    if entity is not None:
        try:
            content = await entity.async_image()
        except (HomeAssistantError, TimeoutError):
            content = None
    if not content:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="photo_snapshot_failed",
            translation_placeholders={"entity_id": entity_id, "error": "no image available"})
    return content


@contextlib.asynccontextmanager
async def async_photo_file(hass, coordinator, data, *, required=False):
    """
    Yield the path of the photo a service call names (None if it names none): its `photo` file
    after the path checks, or a snapshot of its `image_entity` or `camera_entity` written to a
    short-lived file in the integration's private folder.
    """
    sources = [key for key in ("photo", "image_entity", "camera_entity") if data.get(key)]
    if len(sources) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="photo_one_source")
    if not sources:
        if required:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="photo_required")
        yield None
        return
    if sources[0] == "photo":
        yield await hass.async_add_executor_job(_checked_photo_path, hass, coordinator, data["photo"])
        return

    content = await _entity_snapshot(hass, data)
    snapshot = os.path.join(coordinator.photo_dir, SNAPSHOT_DIR_NAME, f"{uuid.uuid4().hex}.img")

    def write():
        os.makedirs(os.path.dirname(snapshot), exist_ok=True)
        with open(snapshot, "wb") as handle:
            handle.write(content)

    await hass.async_add_executor_job(write)
    try:
        yield snapshot
    finally:
        await hass.async_add_executor_job(_remove_quietly, snapshot)


def _remove_quietly(path):
    with contextlib.suppress(OSError):
        os.remove(path)


async def async_log_joy(hass, coordinator, baby_id, *, note="", time_str=None, photo_path=None):
    """Log a joy, with a photo if a file is given."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_joy, baby_id, note, time_str, photo_path, coordinator.picture_dir,
    )
    check_result(result, "add joy")
    await coordinator.async_request_refresh()


async def async_attach_photo(hass, coordinator, object_type, object_id, photo_path):
    """Add a photo to an entry that is already logged."""
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.attach_photo, object_type, object_id, photo_path, coordinator.picture_dir,
    )
    check_result(result, "attach photo")
    await coordinator.async_request_refresh()


async def async_register_services(hass: HomeAssistant):
    """Register services for Baby Tracker."""

    # Check if services are already registered
    if hass.services.has_service(DOMAIN, "add_formula"):
        _LOGGER.debug("Services already registered, skipping registration")
        return

    async def _get_baby_id(coordinator, data):
        """
        Resolve the target baby: a Baby Tracker device picked in the UI,
        baby_name, or the only baby if there is just one.
        """
        if data.get("device_id"):
            device = dr.async_get(hass).async_get(data["device_id"])
            prefix = f"{coordinator.email}_"
            for domain, identifier in (device.identifiers if device else ()):
                if domain == DOMAIN and identifier.startswith(prefix):
                    baby_id = identifier[len(prefix):]
                    if any(b.object_id == baby_id for b in (coordinator.data or {}).get("babies") or []):
                        return baby_id
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_not_a_baby")

        baby_name = data.get("baby_name")

        if baby_name:
            baby = await hass.async_add_executor_job(
                coordinator.baby_tracker.get_baby_by_name,
                baby_name
            )
            if not baby:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="baby_not_found",
                    translation_placeholders={"baby_name": baby_name},
                )
            return baby.object_id

        babies = (coordinator.data or {}).get("babies") or []
        if len(babies) == 1:
            return babies[0].object_id
        if not babies:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_babies")
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="baby_required",
            translation_placeholders={"names": ", ".join(b.name for b in babies)},
        )

    _check = check_result

    def _get_unit_system_from_config():
        """Get the configured unit system (imperial or metric), honouring the options flow."""
        try:
            return _get_coordinator(hass).unit_system
        except ServiceValidationError:
            return DEFAULT_UNIT_SYSTEM

    def _is_imperial_config():
        """Check if the configured unit system is imperial (oz, lbs, F)."""
        return _get_unit_system_from_config() == UNIT_SYSTEM_IMPERIAL

    def _unit_default(data, key):
        """A unit flag from the call, else true for an imperial entry and false for a metric one."""
        value = data.get(key)
        return _is_imperial_config() if value is None else value

    def _utc(data):
        """The time the call asked to date the record at, as an aware UTC datetime (None for now)."""
        moment = data.get("time")
        # A time with no zone is in Home Assistant's time zone
        return dt_util.as_utc(moment) if moment else None

    def _time_str(data):
        """That time in the sync format, "2026-03-01 09:30:00 +0000" (None for now)."""
        return sync_time_str(_utc(data))

    async def add_diaper(call: ServiceCall):
        """Add a diaper change record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        await async_log_diaper(
            hass, coordinator, baby_id, data.get("pee"), data.get("poo"),
            time_str=_time_str(data), pee_color=data.get("pee_color", 5), poo_color=data.get("poo_color", 5),
            texture=data.get("texture", 5), amount=data.get("amount", 2), note=data.get("note", ""),
        )

    async def add_nursing(call: ServiceCall):
        """Add a nursing session record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        await async_log_nursing(
            hass, coordinator, baby_id,
            left=data.get("left_duration", 0), right=data.get("right_duration", 0),
            both=data.get("both_duration", 0), finish_side=data.get("finish_side", "Left"),
            time_str=_time_str(data), note=data.get("note", ""),
        )

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

        await async_log_bottle(
            hass, coordinator, baby_id, data.get("amount"), is_english,
            time_str=_time_str(data), note=data.get("note", ""),
        )

    async def add_pumped(call: ServiceCall):
        """Add a pumped milk record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        # Use configured unit system as default if not explicitly provided
        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        await async_log_bottle(
            hass, coordinator, baby_id, data.get("amount"), is_english,
            pumped=True, time_str=_time_str(data), note=data.get("note", ""),
        )

    async def add_temperature(call: ServiceCall):
        """Add a temperature record."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        await async_log_temperature(
            hass, coordinator, baby_id, data.get("temperature"), _unit_default(data, "is_fahrenheit"),
            time_str=_time_str(data), note=data.get("note", ""),
        )

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
            _time_str(data),
        )
        _check(result, "log bath")

        _LOGGER.info(f"Logged bath: type={data.get('bath_type')}, note={data.get('note')}")
        await coordinator.async_request_refresh()

    async def log_pump(call: ServiceCall):
        """Log a pump session record."""
        data = call.data
        coordinator = _get_coordinator(hass)

        # Pump sessions belong to the account, not a baby, in the app
        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_pump,
            None,
            data.get("left_duration", 0),
            data.get("right_duration", 0),
            data.get("left_amount", 0),
            data.get("right_amount", 0),
            _unit_default(data, "is_english_scale"),
            data.get("note", ""),
            _time_str(data),
        )

        _check(result, "log pump session")

        _LOGGER.info(f"Logged pump session: left={data.get('left_duration')}min/{data.get('left_amount')}, right={data.get('right_duration')}min/{data.get('right_amount')}")
        await coordinator.async_request_refresh()

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

        if not med_id and data.get("create"):
            created = await hass.async_add_executor_job(
                partial(coordinator.baby_tracker.create_medicine, medicine_name,
                        amount_per_time=data.get("amount") or 0))
            _check(created, "create medicine")
            med_id = created.get("objectID")

        if not med_id:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="medicine_not_found",
                translation_placeholders={"name": medicine_name},
            )

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_medicine,
            baby_id,
            _time_str(data),
            med_id,
            data.get("amount"),
            data.get("note", "")
        )

        _check(result, "log medicine")

        _LOGGER.info(f"Logged medicine: {medicine_name}, amount={data.get('amount')}")
        await coordinator.async_request_refresh()

    async def create_medicine(call: ServiceCall):
        """Create a medicine, which then shows up in the Medicine select and can be logged."""
        data = call.data
        coordinator = _get_coordinator(hass)
        result = await hass.async_add_executor_job(
            partial(coordinator.baby_tracker.create_medicine, data["name"],
                    amount_per_time=data.get("amount", 0), unit=data.get("unit", ""),
                    interval_hours=data.get("interval_hours", 0), prescription=data.get("prescription", False)))
        _check(result, "create medicine")

        _LOGGER.info(f"Created medicine: {data['name']} ({result.get('message')})")
        await coordinator.async_request_refresh()

    async def create_food(call: ServiceCall):
        """Create a food for add_solids."""
        data = call.data
        coordinator = _get_coordinator(hass)
        result = await hass.async_add_executor_job(
            partial(coordinator.baby_tracker.create_food, data["name"], is_bottle=data.get("is_bottle", False)))
        _check(result, "create food")

        _LOGGER.info(f"Created food: {data['name']} ({result.get('message')})")
        await coordinator.async_request_refresh()

    async def log_sleep(call: ServiceCall):
        """Log a sleep start or end event."""
        _LOGGER.debug(f"log_sleep service called with data: {call.data}")
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        is_start = data.get("is_start", True)
        await async_log_sleep(hass, coordinator, baby_id, is_start, note=data.get("note", ""), moment=_utc(data))

        _LOGGER.info(f"Logged sleep {'start' if is_start else 'end'}")
        await coordinator.async_request_refresh()

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
            _unit_default(data, "is_english_weight_scale"),
            _unit_default(data, "is_english_length_scale"),
            data.get("note", ""),
            _time_str(data),
        )

        _check(result, "log growth measurement")

        _LOGGER.info(f"Logged growth: weight={data.get('weight')}, length={data.get('length')}, head={data.get('head')}")
        await coordinator.async_request_refresh()

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
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="milestone_not_found",
                translation_placeholders={"name": milestone_name},
            )

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_milestone,
            baby_id,
            milestone_selection_id,
            data.get("note", ""),
            _time_str(data),
        )

        _check(result, "log milestone")

        _LOGGER.info(f"Logged milestone: {milestone_name}")
        await coordinator.async_request_refresh()

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
            _utc(data).timestamp() if data.get("time") else None,  # the app's time: seconds since 1970
        )

        _check(result, "log doctor visit")

        _LOGGER.info(f"Logged doctor visit: type={data.get('visit_type')}, appointment={data.get('is_appointment')}")
        await coordinator.async_request_refresh()

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
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="vaccine_not_found",
                translation_placeholders={"name": vaccine_name},
            )

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.log_vaccine,
            baby_id,
            vacc_id,
            data.get("note", ""),
            "",  # doc_visit_id (empty for now)
            _time_str(data),
        )

        _check(result, "log vaccine")

        _LOGGER.info(f"Logged vaccine: {vaccine_name}")
        await coordinator.async_request_refresh()

    async def log_activity(call: ServiceCall):
        """Log an other activity (tummy time and the like)."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_activity,
            baby_id,
            _time_str(data),
            data.get("activity_name", "Tummy Time"),
            data.get("duration"),
            None,  # location
            data.get("note", ""),
        )
        _check(result, "log activity")

        _LOGGER.info(f"Logged activity: {data.get('activity_name', 'Tummy Time')}, {data.get('duration')} min")
        await coordinator.async_request_refresh()

    async def add_solids(call: ServiceCall):
        """Log a solids (or supplement) feed of one of the account's foods."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        food_name = data.get("food_name")
        foods = await hass.async_add_executor_job(coordinator.baby_tracker.get_other_feed_selections)
        feed_type_id = next((food["id"] for food in foods if food["name"].lower() == food_name.lower()), None)
        if not feed_type_id and data.get("create"):
            created = await hass.async_add_executor_job(coordinator.baby_tracker.create_food, food_name)
            _check(created, "create food")
            feed_type_id = created.get("objectID")
        if not feed_type_id:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="food_not_found",
                translation_placeholders={"name": food_name},
            )

        is_english = data.get("is_english_measure")
        if is_english is None:
            is_english = _is_imperial_config()

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.add_other_feed,
            baby_id,
            _time_str(data),
            feed_type_id,
            data.get("amount"),
            data.get("unit", ""),
            is_english,
            data.get("note", ""),
        )
        _check(result, "add solids")

        _LOGGER.info(f"Logged solids: {food_name}, {data.get('amount')} {data.get('unit', '')}")
        await coordinator.async_request_refresh()

    async def undo_last(call: ServiceCall):
        """Delete a baby's newest record (within the last within_hours), on every device."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.undo_last, baby_id, data.get("within_hours", UNDO_WINDOW_HOURS)
        )
        if result.get("status") != "success" and result.get("message") == NOTHING_TO_UNDO:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_undo",
                translation_placeholders={"hours": f"{data.get('within_hours', UNDO_WINDOW_HOURS):g}"},
            )
        _check(result, "undo the last entry")

        deleted = result.get("deleted") or {}
        _LOGGER.info(f"Undid the last entry: {deleted.get('kind')} ({deleted.get('object_type')} {deleted.get('object_id')})")
        coordinator._announce("undo", coordinator.baby_name_for(baby_id), baby_id, {
            "object_type": deleted.get("object_type"),
            "object_id": deleted.get("object_id"),
            "kind": deleted.get("kind"),
            "time": deleted.get("time"),
        }, EVENT_UNDO)
        await coordinator.async_request_refresh()

    async def delete_record(call: ServiceCall):
        """Delete one record by its type and ID (see the Recent Entries sensor), on every device."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data) if data.get("baby_name") or data.get("device_id") else None

        result = await hass.async_add_executor_job(
            coordinator.baby_tracker.delete_record, data["object_type"], data["object_id"]
        )
        if result.get("status") != "success":
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="delete_failed",
                translation_placeholders={
                    "object_type": data["object_type"], "object_id": data["object_id"],
                    "error": result.get("message") or "unknown error",
                },
            )

        _LOGGER.info(f"Deleted {data['object_type']} {data['object_id']}")
        if baby_id:
            coordinator._announce("undo", coordinator.baby_name_for(baby_id), baby_id, {
                "object_type": result.get("object_type", data["object_type"]),
                "object_id": data["object_id"],
            }, EVENT_UNDO)
        await coordinator.async_request_refresh()

    async def log_joy(call: ServiceCall):
        """Log a joy, optionally with a photo (a file, or a snapshot of an image or camera entity)."""
        data = call.data
        coordinator = _get_coordinator(hass)
        baby_id = await _get_baby_id(coordinator, data)

        async with async_photo_file(hass, coordinator, data) as photo_path:
            await async_log_joy(
                hass, coordinator, baby_id, note=data.get("note", ""), time_str=_time_str(data),
                photo_path=photo_path,
            )

    async def attach_photo(call: ServiceCall):
        """Add a photo to an entry that is already logged, by its type and ID."""
        data = call.data
        coordinator = _get_coordinator(hass)

        async with async_photo_file(hass, coordinator, data, required=True) as photo_path:
            await async_attach_photo(hass, coordinator, data["object_type"], data["object_id"], photo_path)

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
            coordinator.baby_tracker.sync, coordinator.picture_dir
        )

        _check(result, "sync")
        await coordinator.async_request_refresh()

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
        if not coordinator.baby_tracker.is_authenticated:
            # The database is gone and the rejoin failed: the next refresh must sign in again
            coordinator.authenticated = False
        _check(result, "force resync")

        _LOGGER.info("Force resync completed successfully")

        # Refresh coordinator data first (not the debounced request: the reload below needs the new babies)
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

    _get_coordinator = get_coordinator

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
        DOMAIN, "create_medicine", create_medicine, schema=CREATE_MEDICINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "create_food", create_food, schema=CREATE_FOOD_SCHEMA
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
        DOMAIN, "log_activity", log_activity, schema=ACTIVITY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_solids", add_solids, schema=SOLIDS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "undo_last", undo_last, schema=UNDO_LAST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_record", delete_record, schema=DELETE_RECORD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "log_joy", log_joy, schema=LOG_JOY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "attach_photo", attach_photo, schema=ATTACH_PHOTO_SCHEMA
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
        **RECORD_FIELDS,
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
        "create_medicine",
        "create_food",
        "log_sleep",
        "log_growth",
        "log_milestone",
        "log_doctor_visit",
        "log_vaccine",
        "log_activity",
        "add_solids",
        "undo_last",
        "delete_record",
        "log_joy",
        "attach_photo",
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
