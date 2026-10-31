"""Sensor platform for Baby Tracker integration."""
import logging
from datetime import UTC, datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter, MassConverter, VolumeConverter

from .const import (
    ATTR_AMOUNT,
    ATTR_BABY_NAME,
    ATTR_DURATION,
    ATTR_TEMPERATURE_C,
    ATTR_TEMPERATURE_F,
    ATTR_TIME,
    ATTR_TYPE,
    DOMAIN,
    FEEDING_THRESHOLDS,
    SENSOR_TYPE_BEDTIME_ANALYSIS,
    SENSOR_TYPE_BOTTLE_VOLUME,
    SENSOR_TYPE_DAILY_SUMMARY,
    SENSOR_TYPE_DIAPER_COUNT,
    SENSOR_TYPE_FEEDING_COUNT,
    SENSOR_TYPE_FEEDING_TIMER,
    SENSOR_TYPE_HEAD,
    SENSOR_TYPE_LAST_ACTIVITY,
    SENSOR_TYPE_LAST_BATH,
    SENSOR_TYPE_LAST_DIAPER,
    SENSOR_TYPE_LAST_DIAPER_TIME,
    SENSOR_TYPE_LAST_DOCTOR_VISIT,
    SENSOR_TYPE_LAST_FEEDING,
    SENSOR_TYPE_LAST_FEEDING_TIME,
    SENSOR_TYPE_LAST_MEDICINE,
    SENSOR_TYPE_LAST_MILESTONE,
    SENSOR_TYPE_LAST_NURSING,
    SENSOR_TYPE_LAST_PUMP,
    SENSOR_TYPE_LAST_SLEEP,
    SENSOR_TYPE_LAST_SLEEP_TIME,
    SENSOR_TYPE_LAST_TEMPERATURE,
    SENSOR_TYPE_LAST_VACCINE,
    SENSOR_TYPE_LENGTH,
    SENSOR_TYPE_NURSING_MINUTES,
    SENSOR_TYPE_POOPY_COUNT,
    SENSOR_TYPE_PUMP_SUMMARY,
    SENSOR_TYPE_TIME_SINCE_LAST_FEEDING,
    SENSOR_TYPE_WEIGHT,
    SENSOR_TYPE_WET_COUNT,
    SUMMARY_DAYS,
    UNIT_DIAPERS,
    UNIT_FEEDINGS,
    UNIT_SYSTEM_METRIC,
)
from .entity import ClockTickMixin, baby_device_info, baby_unique_id, hours_since_feeding, system_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# How long since the last feeding, in minutes, for each status label
FEEDING_STATUSES = (
    (30, "Recently fed"),
    (120, "Fed recently"),
    (180, "Due for feeding soon"),
    (210, "Feeding due very soon"),
    (240, "Feeding overdue"),
)
FEEDING_STATUS_MAX = "Feeding critically overdue"
NEEDS_FEEDING_MINUTES = 180

# Millilitres and fluid ounces, converted by Home Assistant's own factors
_MASS = MassConverter.convert
_DISTANCE = DistanceConverter.convert
_VOLUME = VolumeConverter.convert


def parse_time(value) -> datetime | None:
    """
    An aware datetime from a time the client returns: "2026-03-01 09:30:00 +0000",
    or an ISO string. A time with no zone is taken to be UTC, as the client's are.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
        except (TypeError, ValueError):
            moment = dt_util.parse_datetime(str(value))
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _round(value, digits):
    return round(value, digits) if value is not None else None


def _to_ml(amount, unit):
    """A pump amount in millilitres, whichever unit it was recorded in."""
    if amount is None:
        return None
    if (unit or "ml").lower() == "oz":
        amount = _VOLUME(amount, UnitOfVolume.FLUID_OUNCES, UnitOfVolume.MILLILITERS)
    return round(amount, 1)


def _note(record) -> dict:
    return {"note": record["note"]} if record.get("note") else {}


def _window() -> dict:
    return {"window_days": SUMMARY_DAYS}


def _get_baby_age_days(baby_info):
    """Calculate baby's age in days from DOB."""
    born = parse_time(getattr(baby_info, "dob", None)) if baby_info else None
    return (datetime.now(UTC) - born).days if born else None


def _get_age_threshold(age_days, thresholds):
    """Return (threshold_value, bracket_label) for the given age."""
    if age_days is None:
        value = thresholds[0][2]
        return value, f"0-{thresholds[0][1]}d"
    for min_days, max_days, value in thresholds:
        if min_days <= age_days <= max_days:
            return value, f"{min_days}-{max_days}d"
    last = thresholds[-1]
    return last[2], f"{last[0]}+d"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Baby Tracker sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [sensor_class(coordinator) for sensor_class in HOUSEHOLD_SENSORS]
    for baby in coordinator.data.get("babies") or []:
        sensors.extend(sensor_class(coordinator, baby.name) for sensor_class in PER_BABY_SENSORS)
        sensors.extend(
            BabyTrackerGrowthPercentileSensor(coordinator, baby.name, kind)
            for kind in ("weight", "length", "head")
        )

    async_add_entities(sensors)


class BabyTrackerSensor(CoordinatorEntity, SensorEntity):
    """
    Base class for a baby's sensors. A subclass names the part of the baby's
    data it reads (_data_key) and turns that record into a value
    (_value) and attributes (_attributes).
    """

    _attr_has_entity_name = True
    _sensor_type = None  # the unique ID suffix, and the translation key
    _data_key = None  # key in the baby's data dict, e.g. "last_feeding"
    _imperial_unit = None  # suggested display unit when the entry is set to imperial

    def __init__(self, coordinator, baby_name, sensor_type=None):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._sensor_type = sensor_type or self._sensor_type
        self._attr_translation_key = self._sensor_type
        # Make unique_id baby-specific to support multiple babies
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, self._sensor_type)
        self._attr_device_info = baby_device_info(coordinator, baby_name)
        if self._imperial_unit:
            # The entry's unit setting decides what is shown, not Home Assistant's own unit system
            self._attr_suggested_unit_of_measurement = (
                self._attr_native_unit_of_measurement
                if coordinator.unit_system == UNIT_SYSTEM_METRIC else self._imperial_unit
            )

    def _get_baby_data(self):
        """This baby's data from the coordinator."""
        if not self.coordinator.data:
            return None
        # No fallback to the top-level data: that is the first baby's, and
        # showing it under another baby's name would be wrong
        return self.coordinator.data.get("baby_data", {}).get(self._baby_name)

    def _get_baby_info(self):
        """The Baby object for this sensor's baby."""
        for baby in (self.coordinator.data or {}).get("babies") or []:
            if baby.name == self._baby_name:
                return baby
        return None

    def _record(self):
        """The record this sensor reads, or None when there isn't one."""
        return (self._get_baby_data() or {}).get(self._data_key) or None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.coordinator.data is not None

    def _value(self, record):
        raise NotImplementedError

    def _attributes(self, record) -> dict:
        return {}

    @property
    def native_value(self):
        record = self._record()
        return self._value(record) if record else None

    @property
    def extra_state_attributes(self):
        record = self._record()
        return self._attributes(record) if record else {}


class BabyTrackerTimestampSensor(BabyTrackerSensor):
    """A sensor whose state is when something happened, for history and automations."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def _value(self, record):
        return parse_time(record.get("time"))


class BabyTrackerInfoSensor(BabyTrackerSensor):
    """Sensor that displays baby information including age."""

    _sensor_type = "baby_info"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _record(self):
        return self._get_baby_info()

    def _value(self, baby):
        born = parse_time(baby.dob)
        if born is None:
            return "Unknown"
        age_days = (datetime.now(UTC) - born).days
        if age_days < 30:
            return f"{age_days} days"
        if age_days < 365:
            return f"{age_days // 30} months"
        years, remaining_months = age_days // 365, (age_days % 365) // 30
        return f"{years}y {remaining_months}m" if remaining_months else f"{years} years"

    def _attributes(self, baby):
        attrs = {
            "name": baby.name,
            "date_of_birth": baby.dob,
            "due_date": baby.due_day,
            "gender": "Male" if baby.gender else "Female",
            "baby_id": baby.object_id,
        }
        age_days = _get_baby_age_days(baby)
        if age_days is not None:
            attrs["age_days"] = age_days
            attrs["age_weeks"] = age_days // 7
            attrs["age_months"] = age_days // 30
        return attrs


class BabyTrackerTimeSinceLastFeedingSensor(ClockTickMixin, BabyTrackerSensor):
    """Minutes since the last feeding."""

    _sensor_type = SENSOR_TYPE_TIME_SINCE_LAST_FEEDING
    _data_key = "time_since_last_feeding"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _minutes(self, record):
        hours = hours_since_feeding(self.coordinator, record)
        # Rounded first so float error (214.99999999999997) doesn't lose a minute
        return None if hours is None else int(round(hours * 60, 6))

    def _value(self, record):
        return self._minutes(record)

    def _attributes(self, record):
        total_minutes = self._minutes(record)
        if total_minutes is None:
            return {}
        status = next((label for limit, label in FEEDING_STATUSES if total_minutes < limit), FEEDING_STATUS_MAX)

        hours, minutes = divmod(total_minutes, 60)
        if hours == 0:
            friendly_time = "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
        elif hours == 1:
            friendly_time = f"1 hour and {minutes} minutes ago"
        else:
            friendly_time = f"{hours} hours and {minutes} minutes ago"

        return {
            "last_feeding_time": record.get("last_feeding_time"),
            "time_difference": record.get("time_difference"),
            "total_minutes": total_minutes,
            "friendly_time": friendly_time,
            "feeding_status": status,
            "needs_feeding": total_minutes >= NEEDS_FEEDING_MINUTES,  # Boolean flag for easier automation
            ATTR_BABY_NAME: self._baby_name,
        }


class BabyTrackerLastFeedingSensor(BabyTrackerSensor):
    """Sensor that displays the type of the last feeding."""

    _sensor_type = SENSOR_TYPE_LAST_FEEDING
    _data_key = "last_feeding"
    _TYPES = ("nursing", "formula", "pumped", "supplement")
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_TYPES)

    def _value(self, record):
        feeding_type = str(record.get("type") or "").lower()
        return feeding_type if feeding_type in self._TYPES else None

    def _attributes(self, record):
        attrs = {
            ATTR_TIME: record.get("time"),
            ATTR_TYPE: record.get("type"),
        }
        if record.get("type") == "Nursing":
            attrs[ATTR_DURATION] = record.get("total_duration")
            attrs["left_duration"] = record.get("left_duration")
            attrs["right_duration"] = record.get("right_duration")
            attrs["both_duration"] = record.get("both_duration")
        elif record.get("type") in ("Pumped", "Formula"):
            attrs[ATTR_AMOUNT] = record.get("amount")
            attrs["amount_oz"] = record.get("amount_oz")
            attrs["amount_ml"] = record.get("amount_ml")
        return attrs | _note(record)


class BabyTrackerLastFeedingTimeSensor(BabyTrackerTimestampSensor):
    """When the last feeding was."""

    _sensor_type = SENSOR_TYPE_LAST_FEEDING_TIME
    _data_key = "last_feeding"


class BabyTrackerLastDiaperSensor(BabyTrackerSensor):
    """Sensor that displays the status of the last diaper change."""

    _sensor_type = SENSOR_TYPE_LAST_DIAPER
    _data_key = "last_diaper"
    _STATUSES = ("wet", "poopy", "mixed", "dry")
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_STATUSES)

    def _value(self, record):
        status = str(record.get("status") or "").lower()
        return status if status in self._STATUSES else None

    def _attributes(self, record):
        attrs = {
            ATTR_TIME: record.get("time"),
            "status": record.get("status"),
            "status_code": record.get("status_code"),
            "pee_color": record.get("pee_color"),
            "poo_color": record.get("poo_color"),
            "amount": record.get("amount"),
            "texture": record.get("texture"),
            "count": record.get("count"),
        }
        # Also include summary stats from the diaper summary if available
        diaper_summary = (self._get_baby_data() or {}).get("diaper_summary")
        if diaper_summary:
            attrs["total_diapers_today"] = diaper_summary.get("total_diapers", 0)
            attrs["poopy_streak"] = diaper_summary.get("poopy_streak", 0)
        return attrs | _note(record)


class BabyTrackerLastDiaperTimeSensor(BabyTrackerTimestampSensor):
    """When the last diaper change was."""

    _sensor_type = SENSOR_TYPE_LAST_DIAPER_TIME
    _data_key = "last_diaper"


class BabyTrackerLastSleepSensor(BabyTrackerSensor):
    """Minutes slept in the last sleep, or so far if the baby is asleep now."""

    _sensor_type = SENSOR_TYPE_LAST_SLEEP
    _data_key = "last_sleep"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _value(self, record):
        if record.get("is_sleeping"):
            return record.get("current_duration", 0)
        return record.get("duration", 0)

    def _attributes(self, record):
        is_sleeping = record.get("is_sleeping", False)
        duration = record.get("duration", 0)
        current_duration = record.get("current_duration", 0)

        attrs = {
            ATTR_TIME: record.get("time"),
            "start_time": record.get("time"),
            "sleeping": is_sleeping,
            "is_sleeping": is_sleeping,  # kept for automations written before "sleeping"
            "status": record.get("status", "unknown"),
            ATTR_DURATION: duration,  # Original duration from DB
            "current_duration": current_duration,  # Real-time if sleeping
        }

        display_duration = current_duration if is_sleeping else duration
        if display_duration:
            hours, minutes = divmod(int(display_duration), 60)
            attrs["duration_hours"] = hours
            attrs["duration_minutes"] = minutes
            attrs["duration_formatted"] = f"{hours}h {minutes}m"
            attrs["message"] = f"{'Sleeping for' if is_sleeping else 'Slept'} {hours}h {minutes}m"
        return attrs | _note(record)


class BabyTrackerLastSleepTimeSensor(BabyTrackerTimestampSensor):
    """When the last sleep started."""

    _sensor_type = SENSOR_TYPE_LAST_SLEEP_TIME
    _data_key = "last_sleep"


class BabyTrackerLastNursingSensor(BabyTrackerSensor):
    """Minutes of the last nursing session."""

    _sensor_type = SENSOR_TYPE_LAST_NURSING
    _data_key = "last_nursing"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _value(self, record):
        return record.get("total_duration", 0)

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            ATTR_DURATION: record.get("total_duration"),
            "left_duration": record.get("left_duration"),
            "right_duration": record.get("right_duration"),
            "both_duration": record.get("both_duration"),
            "finish_side": record.get("finish_side"),
            "count": record.get("count"),
        } | _note(record)


class BabyTrackerLastBathSensor(BabyTrackerSensor):
    """Sensor that displays info about the last bath."""

    _sensor_type = SENSOR_TYPE_LAST_BATH
    _data_key = "last_bath"

    def _value(self, record):
        return record.get("bath_type", "Bath")

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "bath_type": record.get("bath_type", "Bath"),
        } | _note(record)


class BabyTrackerLastTemperatureSensor(BabyTrackerSensor):
    """The last temperature reading, in the unit chosen for this entry."""

    _sensor_type = SENSOR_TYPE_LAST_TEMPERATURE
    _data_key = "last_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, baby_name):
        super().__init__(coordinator, baby_name)
        self._metric = coordinator.unit_system == UNIT_SYSTEM_METRIC
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.CELSIUS if self._metric else UnitOfTemperature.FAHRENHEIT
        )
        # Show the unit chosen for this entry, not the one Home Assistant's own unit system would convert to
        self._attr_suggested_unit_of_measurement = self._attr_native_unit_of_measurement

    def _value(self, record):
        return record.get("celsius" if self._metric else "fahrenheit")

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            ATTR_TEMPERATURE_F: record.get("fahrenheit"),
            ATTR_TEMPERATURE_C: record.get("celsius"),
        }


# --- Totals over the last SUMMARY_DAYS days ---

class BabyTrackerFeedingCountSensor(BabyTrackerSensor):
    """Feedings in the last 7 days."""

    _sensor_type = SENSOR_TYPE_FEEDING_COUNT
    _data_key = "feeding_summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_FEEDINGS

    def _value(self, record):
        return record.get("total_feedings", 0)

    def _attributes(self, record):
        return {
            "nursing_count": record.get("nursing_count", 0),
            "formula_count": record.get("formula_count", 0),
            "pumped_count": record.get("pumped_count", 0),
            "bottle_feedings": record.get("bottle_feedings", 0),
            "avg_feedings_per_day": record.get("avg_feedings_per_day", 0),
        } | _window()


class BabyTrackerNursingMinutesSensor(BabyTrackerSensor):
    """Minutes nursed in the last 7 days."""

    _sensor_type = SENSOR_TYPE_NURSING_MINUTES
    _data_key = "feeding_summary"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _value(self, record):
        return record.get("nursing_total_minutes", 0)

    def _attributes(self, record):
        return {
            "left_minutes": record.get("nursing_left_minutes", 0),
            "right_minutes": record.get("nursing_right_minutes", 0),
            "avg_nursing_minutes_per_day": record.get("avg_nursing_minutes_per_day", 0),
        } | _window()


class BabyTrackerBottleVolumeSensor(BabyTrackerSensor):
    """Bottle milk (formula and pumped) in the last 7 days."""

    _sensor_type = SENSOR_TYPE_BOTTLE_VOLUME
    _data_key = "feeding_summary"
    _imperial_unit = UnitOfVolume.FLUID_OUNCES
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    def _value(self, record):
        return _round(record.get("bottle_amount_ml", 0), 1)

    def _attributes(self, record):
        return {
            "formula_amount_ml": _round(record.get("formula_amount_ml", 0), 1),
            "pumped_amount_ml": _round(record.get("pumped_amount_ml", 0), 1),
            "avg_bottle_ml_per_day": record.get("avg_bottle_ml_per_day", 0),
            "bottle_amount_oz": _round(record.get("bottle_amount_oz", 0), 1),
            "formula_amount_oz": _round(record.get("formula_amount_oz", 0), 1),
            "pumped_amount_oz": _round(record.get("pumped_amount_oz", 0), 1),
            "avg_bottle_oz_per_day": record.get("avg_bottle_oz_per_day", 0),
            "bottle_feedings": record.get("bottle_feedings", 0),
        } | _window()


class BabyTrackerDiaperCountSensor(BabyTrackerSensor):
    """Diapers in the last 7 days."""

    _sensor_type = SENSOR_TYPE_DIAPER_COUNT
    _data_key = "diaper_summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_DIAPERS

    def _value(self, record):
        return record.get("total_diapers", 0)

    def _attributes(self, record):
        return {"avg_diapers_per_day": record.get("avg_diapers_per_day", 0)} | _window()


class BabyTrackerPoopyCountSensor(BabyTrackerSensor):
    """Poopy diapers (including mixed) in the last 7 days."""

    _sensor_type = SENSOR_TYPE_POOPY_COUNT
    _data_key = "diaper_summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_DIAPERS

    def _value(self, record):
        return record.get("poopy_count", 0) + record.get("mixed_count", 0)

    def _attributes(self, record):
        return {
            "poopy_streak": record.get("poopy_streak", 0),
            "avg_poopy_per_day": record.get("avg_poopy_per_day", 0),
            "last_poopy_time": record.get("last_poopy_time"),
            "hours_since_last_poopy": record.get("hours_since_last_poopy"),
        } | _window()


class BabyTrackerWetCountSensor(BabyTrackerSensor):
    """Wet diapers (including mixed) in the last 7 days."""

    _sensor_type = SENSOR_TYPE_WET_COUNT
    _data_key = "diaper_summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_DIAPERS

    def _value(self, record):
        return record.get("wet_count", 0) + record.get("mixed_count", 0)

    def _attributes(self, record):
        return {
            "avg_wet_per_day": record.get("avg_wet_per_day", 0),
            "pee_color_distribution": record.get("pee_by_color", {}),
        } | _window()


# --- Pumping ---

class BabyTrackerLastPumpSensor(BabyTrackerSensor):
    """Millilitres from the last pump session."""

    _sensor_type = SENSOR_TYPE_LAST_PUMP
    _data_key = "last_pump"
    _imperial_unit = UnitOfVolume.FLUID_OUNCES
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    def _value(self, record):
        return _to_ml(record.get("total_amount", 0), record.get("unit"))

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "left_duration": record.get("left_duration", 0),
            "right_duration": record.get("right_duration", 0),
            "total_duration": record.get("total_duration", 0),
            "left_amount": record.get("left_amount", 0),
            "right_amount": record.get("right_amount", 0),
            "total_amount": record.get("total_amount", 0),
            "unit": record.get("unit", "ml"),
            "finish_side": record.get("finish_side", "Unknown"),
        } | _note(record)


class BabyTrackerPumpSummarySensor(BabyTrackerSensor):
    """Millilitres pumped in the last 7 days."""

    _sensor_type = SENSOR_TYPE_PUMP_SUMMARY
    _data_key = "pump_summary"
    _imperial_unit = UnitOfVolume.FLUID_OUNCES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    def _value(self, record):
        return _to_ml(record.get("total_amount", 0), record.get("unit"))

    def _attributes(self, record):
        return {
            "total_sessions": record.get("total_sessions", 0),
            "total_amount": record.get("total_amount", 0),
            "total_duration": record.get("total_duration", 0),
            "avg_amount_per_session": record.get("avg_amount_per_session", 0),
            "avg_duration_per_session": record.get("avg_duration_per_session", 0),
            "sessions_per_day": record.get("sessions_per_day", 0),
            "unit": record.get("unit", "ml"),
        } | _window()


# --- Other records ---

class BabyTrackerLastMedicineSensor(BabyTrackerSensor):
    """Sensor that displays info about the last medicine dose."""

    _sensor_type = SENSOR_TYPE_LAST_MEDICINE
    _data_key = "last_medicine"

    def _value(self, record):
        return record.get("medicine_name", "Unknown Medicine")

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "medicine_name": record.get("medicine_name", "Unknown"),
            ATTR_AMOUNT: record.get("amount", 0),
            "unit": record.get("unit", ""),
            "med_id": record.get("med_id"),
        } | _note(record)


class BabyTrackerLastActivitySensor(BabyTrackerSensor):
    """Sensor that displays the last other activity (tummy time and the like)."""

    _sensor_type = SENSOR_TYPE_LAST_ACTIVITY
    _data_key = "last_activity"

    def _value(self, record):
        return record.get("activity_name") or "Activity"

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            ATTR_DURATION: record.get("duration"),
        } | _note(record)


class BabyTrackerLastMilestoneSensor(BabyTrackerSensor):
    """Sensor that displays info about the last milestone."""

    _sensor_type = SENSOR_TYPE_LAST_MILESTONE
    _data_key = "last_milestone"

    def _value(self, record):
        return record.get("milestone_name", "Unknown")

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "milestone_name": record.get("milestone_name", "Unknown"),
            "milestone_description": record.get("milestone_description", ""),
            "milestone_selection_id": record.get("milestone_selection_id"),
        } | _note(record)


class BabyTrackerLastDoctorVisitSensor(BabyTrackerTimestampSensor):
    """When the last doctor visit was."""

    _sensor_type = SENSOR_TYPE_LAST_DOCTOR_VISIT
    _data_key = "last_doctor_visit"

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "is_appointment": record.get("is_appointment", False),
            "visit_type": record.get("visit_type", 0),
            "symptom": record.get("symptom", ""),
            "doctor_note": record.get("doctor_note", ""),
        } | _note(record)


class BabyTrackerLastVaccineSensor(BabyTrackerSensor):
    """Sensor that displays info about the last vaccine."""

    _sensor_type = SENSOR_TYPE_LAST_VACCINE
    _data_key = "last_vaccine"

    def _value(self, record):
        return record.get("vaccine_name", "Unknown")

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("time"),
            "vaccine_name": record.get("vaccine_name", "Unknown"),
            "vaccine_description": record.get("vaccine_description", ""),
            "vacc_id": record.get("vacc_id"),
        } | _note(record)


# --- Growth measurements, stored in the unit they were recorded in ---

class BabyTrackerWeightSensor(BabyTrackerSensor):
    """The most recent weight, in kilograms."""

    _sensor_type = SENSOR_TYPE_WEIGHT
    _data_key = "last_growth"
    _imperial_unit = UnitOfMass.POUNDS
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS

    def _value(self, record):
        weight = record.get("weight")
        if not weight:  # 0 is "not measured"
            return None
        if record.get("is_english_weight", record.get("weight_unit") == "lbs"):
            weight = _MASS(weight, UnitOfMass.POUNDS, UnitOfMass.KILOGRAMS)
        return round(weight, 3)

    def _attributes(self, record):
        return {
            ATTR_TIME: record.get("weight_time", record.get("time")),
            "weight": record.get("weight", 0),
            "unit": record.get("weight_unit", "lbs"),
        } | _note(record)


class BabyTrackerLengthSensor(BabyTrackerSensor):
    """The most recent length/height, in centimetres."""

    _sensor_type = SENSOR_TYPE_LENGTH
    _data_key = "last_growth"
    _field = "length"
    _imperial_unit = UnitOfLength.INCHES
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS

    def _value(self, record):
        length = record.get(self._field)
        if not length:  # 0 is "not measured"
            return None
        if self._english(record):
            length = _DISTANCE(length, UnitOfLength.INCHES, UnitOfLength.CENTIMETERS)
        return round(length, 1)

    def _english(self, record):
        """Whether this measure was recorded in inches (head and length can differ between visits)."""
        key = f"is_english_{self._field}"
        return record[key] if key in record else record.get("is_english_length", record.get("length_unit") == "in")

    def _attributes(self, record):
        return {
            # When this measure was taken, which may be an earlier visit than the latest one
            ATTR_TIME: record.get(f"{self._field}_time", record.get("time")),
            self._field: record.get(self._field, 0),
            "unit": "in" if self._english(record) else "cm",
        } | _note(record)


class BabyTrackerHeadSensor(BabyTrackerLengthSensor):
    """The most recent head circumference, in centimetres."""

    _sensor_type = SENSOR_TYPE_HEAD
    _field = "head"


# --- Daily summary, feeding timer and sleep pattern ---

class BabyTrackerDailySummarySensor(BabyTrackerSensor):
    """Feedings so far today, with the rest of today's totals as attributes."""

    _sensor_type = SENSOR_TYPE_DAILY_SUMMARY
    _data_key = "daily_summary"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_FEEDINGS

    def _value(self, record):
        return record.get("total_feedings", 0)

    def _attributes(self, record):
        return {
            "formula_oz": record.get("formula_oz", 0),
            "nursing_minutes": record.get("nursing_minutes", 0),
            "diaper_count": record.get("diaper_count", 0),
            "sleep_hours": record.get("sleep_hours", 0),
            "window": "today",
        }


class BabyTrackerFeedingTimerSensor(ClockTickMixin, BabyTrackerSensor):
    """Minutes until the next feeding is due (negative once overdue)."""

    _sensor_type = SENSOR_TYPE_FEEDING_TIMER
    _data_key = "time_since_last_feeding"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _compute_timer(self):
        """(minutes_remaining, status, threshold_hours, next_feeding_time, hours_since), all None without data."""
        time_data = self._record()
        hours_since = hours_since_feeding(self.coordinator, time_data)
        if hours_since is None:
            return None, None, None, None, None

        threshold_hours, _ = _get_age_threshold(_get_baby_age_days(self._get_baby_info()), FEEDING_THRESHOLDS)
        minutes_remaining = int(threshold_hours * 60 - hours_since * 60)

        if minutes_remaining > 30:
            status = "ok"
        elif minutes_remaining > 0:
            status = "soon"
        else:
            status = "overdue"

        # Estimate next feeding time
        last_fed = parse_time(time_data.get("last_feeding_time"))
        next_feeding_time = None
        if last_fed:
            next_feeding_time = (last_fed + timedelta(hours=threshold_hours)).strftime("%Y-%m-%d %H:%M:%S %z")

        return minutes_remaining, status, threshold_hours, next_feeding_time, hours_since

    @property
    def icon(self):
        """Return icon based on status."""
        if self._compute_timer()[1] == "overdue":
            return "mdi:timer-alert-outline"
        return "mdi:timer-outline"

    @property
    def native_value(self):
        return self._compute_timer()[0]

    @property
    def extra_state_attributes(self):
        _, status, threshold_hours, next_feeding_time, hours_since = self._compute_timer()
        attrs = {
            "status": status,
            "threshold_hours": threshold_hours,
            "hours_since_last": _round(hours_since, 2),
        }
        if next_feeding_time:
            attrs["next_feeding_time"] = next_feeding_time
        return attrs


class BabyTrackerBedtimeAnalysisSensor(BabyTrackerSensor):
    """The average bedtime over the last two weeks, with per-day data for graphing."""

    _sensor_type = SENSOR_TYPE_BEDTIME_ANALYSIS
    _data_key = "sleep_analysis"

    @staticmethod
    def _clean(value):
        """The client says "N/A" where there is nothing to average."""
        return None if value == "N/A" else value

    def _value(self, record):
        return self._clean(record.get("avg_bedtime"))

    def _attributes(self, record):
        return {
            "avg_wake_time": self._clean(record.get("avg_wake_time")),
            "avg_sleep_duration_hours": record.get("avg_sleep_duration_hours"),
            "avg_bedtime_minutes": record.get("avg_bedtime_minutes"),
            "avg_wake_time_minutes": record.get("avg_wake_time_minutes"),
            "days_analyzed": record.get("days_analyzed"),
            "per_day": record.get("per_day", []),
        }


# --- Insights: derived from the logged data (see client/insights.py) ---

class BabyTrackerInsightSensor(BabyTrackerSensor):
    """Base for sensors that read one section of a baby's insights."""

    _data_key = "insights"
    _section = None  # key in the insights dict, e.g. "next_feed"
    _attribute_keys = ()  # copied from the section into the attributes

    def _get_section(self):
        """This baby's section of the insights as a dict (empty when missing)."""
        return ((self._get_baby_data() or {}).get("insights") or {}).get(self._section) or {}

    def _record(self):
        return self._get_section() or None

    def _attributes(self, record):
        return {key: record.get(key) for key in self._attribute_keys}


class BabyTrackerNextFeedSensor(BabyTrackerInsightSensor):
    """When the next feed is expected, from the pattern of recent feeds."""

    _sensor_type = "next_feed"
    _section = "next_feed"
    _attribute_keys = ("interval_hours", "basis", "sample_count", "bucket", "last_feed_at",
                       "max_gap_hours", "wake_by", "overdue")
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def _value(self, record):
        return parse_time(record.get("predicted_at"))

    def _attributes(self, record):
        attrs = super()._attributes(record)
        attrs["interval_hours"] = _round(attrs["interval_hours"], 2)
        return attrs


class BabyTrackerFeedIntervalSensor(BabyTrackerInsightSensor):
    """The usual time between feeds right now."""

    _sensor_type = "feed_interval"
    _section = "next_feed"
    _attribute_keys = ("basis", "sample_count", "bucket")
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    def _value(self, record):
        return _round(record.get("interval_hours"), 2)


class BabyTrackerIntakeSensor(BabyTrackerInsightSensor):
    """Bottle milk (formula and pumped) in the last 24 hours."""

    _sensor_type = "intake_24h"
    _section = "intake"
    _attribute_keys = ("expected_min_ml", "expected_max_ml", "status", "reason",
                       "bottle_feeds", "nursing_feeds", "ml_per_kg")
    _imperial_unit = UnitOfVolume.FLUID_OUNCES
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    def _value(self, record):
        return _round(record.get("actual_ml"), 1)

    def _attributes(self, record):
        attrs = super()._attributes(record)
        attrs["ml_per_kg"] = _round(attrs["ml_per_kg"], 1)
        return attrs


class BabyTrackerIntakeStatusSensor(BabyTrackerInsightSensor):
    """Whether the last 24 hours of bottle milk is low, ok or high for the baby's weight."""

    _sensor_type = "intake_status"
    _section = "intake"
    _attribute_keys = ("reason",)
    _STATUSES = ("low", "ok", "high", "unknown")
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_STATUSES)

    def _value(self, record):
        status = record.get("status")
        return status if status in self._STATUSES else None


class BabyTrackerDiaperAdequacySensor(BabyTrackerInsightSensor):
    """Whether the last 24 hours of wet and dirty diapers is enough for the baby's age."""

    _sensor_type = "diaper_adequacy"
    _section = "diapers"
    _attribute_keys = ("wet_count", "dirty_count", "expected_min_wet", "note")
    _STATUSES = ("ok", "low", "unknown")
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_STATUSES)

    def _value(self, record):
        status = record.get("status")
        return status if status in self._STATUSES else None


class BabyTrackerGrowthPercentileSensor(BabyTrackerInsightSensor):
    """Where the latest weight, length or head measurement sits on the WHO growth standard."""

    _section = "growth"
    _attribute_keys = ("z", "p3", "p50", "p97", "measured_at", "age_months")
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, baby_name, kind):
        super().__init__(coordinator, baby_name, f"{kind}_percentile")
        self._kind = kind

    def _get_section(self):
        return (super()._get_section().get(self._kind)) or {}

    def _value(self, record):
        return _round(record.get("percentile"), 1)

    def _attributes(self, record):
        attrs = super()._attributes(record)
        for key in ("z", "p3", "p50", "p97", "age_months"):
            attrs[key] = _round(attrs[key], 2)
        return attrs


class BabyTrackerWeightGainSensor(BabyTrackerInsightSensor):
    """Weight gain in grams per day between the latest two weights."""

    _sensor_type = "weight_gain"
    _section = "weight_velocity"
    _attribute_keys = ("status", "expected_min", "expected_max", "span_days",
                       "from_at", "to_at", "reason")
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "g/d"

    def _value(self, record):
        return _round(record.get("grams_per_day"), 1)

    def _attributes(self, record):
        attrs = super()._attributes(record)
        attrs["span_days"] = _round(attrs["span_days"], 1)
        return attrs


class BabyTrackerCorrectedAgeSensor(BabyTrackerInsightSensor):
    """Age in days, corrected for prematurity when the baby was born before 37 weeks."""

    _sensor_type = "corrected_age"
    _section = "age"
    _attribute_keys = ("chronological_days", "corrected_months", "premature",
                       "correction_applied", "gestation_days")
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def _value(self, record):
        return record.get("corrected_days")

    def _attributes(self, record):
        attrs = super()._attributes(record)
        attrs["corrected_months"] = _round(attrs["corrected_months"], 2)
        return attrs


# --- Derived from records already stored (see client/database.py) ---

def _iso(value):
    """A client time as an ISO string for an attribute, None when missing."""
    moment = parse_time(value)
    return moment.isoformat() if moment else None


class BabyTrackerNextBreastSensor(BabyTrackerSensor):
    """Which breast to offer next: the side the last nursing or pump session did not finish on."""

    _sensor_type = "next_breast"
    _data_key = "next_breast"
    _SIDES = ("left", "right", "unknown")
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_SIDES)

    def _value(self, record):
        side = record.get("next_side")
        return side if side in self._SIDES else None

    def _attributes(self, record):
        return {
            "last_side": record.get("last_side"),
            "last_type": record.get("last_type"),
            "last_time": _iso(record.get("last_time")),
        }


class BabyTrackerNextMedicineDoseSensor(BabyTrackerSensor):
    """When the last medicine given can be given again (its interval after the last dose)."""

    _sensor_type = "next_medicine_dose"
    _data_key = "next_medicine_dose"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def _value(self, record):
        return parse_time(record.get("next_dose_at"))  # unknown when the medicine has no interval

    def _attributes(self, record):
        return {
            "medicine_name": record.get("medicine_name"),
            ATTR_AMOUNT: record.get("amount"),
            "unit": record.get("unit"),
            "last_given": _iso(record.get("last_given")),
            "interval_minutes": record.get("interval_minutes"),
        }


class BabyTrackerUpcomingSensor(BabyTrackerSensor):
    """The next item the baby hasn't logged, by the age (in months) it is expected at."""

    _MAX_LISTED = 10

    def _value(self, record):
        return str(record[0]["name"])[:255]

    def _attributes(self, record):
        return {
            "for_age_months": record[0]["for_age"],
            "count": len(record),
            "upcoming": [{"name": item["name"], "for_age_months": item["for_age"]}
                         for item in record[:self._MAX_LISTED]],
        }


class BabyTrackerUpcomingMilestonesSensor(BabyTrackerUpcomingSensor):
    _sensor_type = "upcoming_milestones"
    _data_key = "upcoming_milestones"


class BabyTrackerUpcomingVaccinesSensor(BabyTrackerUpcomingSensor):
    _sensor_type = "upcoming_vaccines"
    _data_key = "upcoming_vaccines"


class BabyTrackerRecentEntriesSensor(BabyTrackerSensor):
    """
    The baby's newest records of every kind, for dashboards and the delete_record service: the
    state is the newest one's label and the records attribute lists them with the type and ID the
    service takes.
    """

    _sensor_type = "recent_entries"
    _data_key = "recent_records"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _value(self, record):
        return str(record[0]["kind"])[:255]

    def _attributes(self, record):
        return {"records": record}


# --- Household: all babies together, on the account's own "Baby Tracker" device ---

class BabyTrackerHouseholdSensor(CoordinatorEntity, SensorEntity):
    """Base for sensors that look across every baby."""

    _attr_has_entity_name = True
    _sensor_type = None  # the unique ID suffix, and the translation key

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_translation_key = self._sensor_type
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_system_{self._sensor_type}"
        self._attr_device_info = system_device_info(coordinator)

    def _babies(self):
        """[(baby name, that baby's data)] for every baby."""
        return list(((self.coordinator.data or {}).get("baby_data") or {}).items())

    def _account(self):
        return (self.coordinator.data or {}).get("account") or {}

    def _next_feed(self):
        """({baby name: predicted time} for every baby with one, (name, time) of the soonest or None)."""
        predictions = {}
        for name, data in self._babies():
            moment = parse_time((((data.get("insights") or {}).get("next_feed")) or {}).get("predicted_at"))
            if moment:
                predictions[name] = moment
        return predictions, (min(predictions.items(), key=lambda item: item[1]) if predictions else None)

    def _last_fed(self):
        """(baby name, time) of whoever was fed most recently, else None."""
        fed = [(name, parse_time((data.get("last_feeding") or {}).get("time"))) for name, data in self._babies()]
        fed = [item for item in fed if item[1]]
        return max(fed, key=lambda item: item[1]) if fed else None


class BabyTrackerNextFeedDueSensor(BabyTrackerHouseholdSensor):
    """When the next feed is due, for whichever baby is due first."""

    _sensor_type = "next_feed_due"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        _, soonest = self._next_feed()
        return soonest[1] if soonest else None

    @property
    def extra_state_attributes(self):
        predictions, soonest = self._next_feed()
        return {
            "baby": soonest[0] if soonest else None,
            "predictions": {name: moment.isoformat() for name, moment in predictions.items()},
        }


class BabyTrackerNextFeedBabySensor(BabyTrackerHouseholdSensor):
    """Which baby is due to feed first."""

    _sensor_type = "next_feed_baby"

    @property
    def native_value(self):
        _, soonest = self._next_feed()
        return soonest[0] if soonest else None

    @property
    def extra_state_attributes(self):
        _, soonest = self._next_feed()
        return {"predicted_at": soonest[1].isoformat() if soonest else None}


class BabyTrackerLastFedBabySensor(BabyTrackerHouseholdSensor):
    """Which baby was fed most recently."""

    _sensor_type = "last_fed_baby"

    @property
    def native_value(self):
        last = self._last_fed()
        return last[0] if last else None

    @property
    def extra_state_attributes(self):
        last = self._last_fed()
        return {"time": last[1].isoformat() if last else None}


class BabyTrackerBabiesAsleepSensor(BabyTrackerHouseholdSensor):
    """How many babies are asleep right now."""

    _sensor_type = "babies_asleep"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "babies"

    def _asleep(self):
        return [name for name, data in self._babies() if (data.get("last_sleep") or {}).get("is_sleeping")]

    @property
    def native_value(self):
        return len(self._asleep()) if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        return {"babies": self._asleep()}


class BabyTrackerFeedsTodaySensor(BabyTrackerHouseholdSensor):
    """Feedings so far today, across every baby."""

    _sensor_type = "feeds_today"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_FEEDINGS

    def _counts(self):
        return {name: (data.get("daily_summary") or {}).get("total_feedings", 0) for name, data in self._babies()}

    @property
    def native_value(self):
        return sum(self._counts().values()) if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        return {"per_baby": self._counts(), "window": "today"}


class BabyTrackerPendingUploadsSensor(BabyTrackerHouseholdSensor):
    """Records logged here that the Baby Tracker server has not received yet."""

    _sensor_type = "pending_uploads"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "records"

    @property
    def native_value(self):
        return self._account().get("pending_uploads")


class BabyTrackerPumpedMilkInventorySensor(BabyTrackerHouseholdSensor):
    """Pumped milk in store: everything pumped (with inventory adjustments) minus everything fed."""

    _sensor_type = "pumped_milk_inventory"
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    def __init__(self, coordinator):
        super().__init__(coordinator)
        # The entry's unit setting decides what is shown, as for the baby's volume sensors
        self._attr_suggested_unit_of_measurement = (
            UnitOfVolume.MILLILITERS if coordinator.unit_system == UNIT_SYSTEM_METRIC else UnitOfVolume.FLUID_OUNCES
        )

    def _inventory(self):
        return self._account().get("pumped_milk_inventory") or {}

    @property
    def native_value(self):
        return self._inventory().get("ml")

    @property
    def extra_state_attributes(self):
        inventory = self._inventory()
        return {"pumped_ml": inventory.get("pumped_ml"), "fed_ml": inventory.get("fed_ml")}


HOUSEHOLD_SENSORS = (
    BabyTrackerNextFeedDueSensor,
    BabyTrackerNextFeedBabySensor,
    BabyTrackerLastFedBabySensor,
    BabyTrackerBabiesAsleepSensor,
    BabyTrackerFeedsTodaySensor,
    BabyTrackerPendingUploadsSensor,
    BabyTrackerPumpedMilkInventorySensor,
)


# Sensors every baby gets (the growth percentiles take an extra argument)
PER_BABY_SENSORS = (
    BabyTrackerInfoSensor,
    BabyTrackerLastFeedingSensor,
    BabyTrackerLastFeedingTimeSensor,
    BabyTrackerLastDiaperSensor,
    BabyTrackerLastDiaperTimeSensor,
    BabyTrackerLastSleepSensor,
    BabyTrackerLastSleepTimeSensor,
    BabyTrackerLastNursingSensor,
    BabyTrackerLastBathSensor,
    BabyTrackerLastPumpSensor,
    BabyTrackerPumpSummarySensor,
    BabyTrackerLastMedicineSensor,
    BabyTrackerLastActivitySensor,
    BabyTrackerLastMilestoneSensor,
    BabyTrackerLastDoctorVisitSensor,
    BabyTrackerLastVaccineSensor,
    BabyTrackerWeightSensor,
    BabyTrackerLengthSensor,
    BabyTrackerHeadSensor,
    BabyTrackerLastTemperatureSensor,
    BabyTrackerFeedingCountSensor,
    BabyTrackerNursingMinutesSensor,
    BabyTrackerBottleVolumeSensor,
    BabyTrackerDiaperCountSensor,
    BabyTrackerPoopyCountSensor,
    BabyTrackerWetCountSensor,
    BabyTrackerTimeSinceLastFeedingSensor,
    BabyTrackerDailySummarySensor,
    BabyTrackerFeedingTimerSensor,
    BabyTrackerBedtimeAnalysisSensor,
    BabyTrackerNextFeedSensor,
    BabyTrackerFeedIntervalSensor,
    BabyTrackerIntakeSensor,
    BabyTrackerIntakeStatusSensor,
    BabyTrackerDiaperAdequacySensor,
    BabyTrackerWeightGainSensor,
    BabyTrackerCorrectedAgeSensor,
    BabyTrackerNextBreastSensor,
    BabyTrackerNextMedicineDoseSensor,
    BabyTrackerUpcomingMilestonesSensor,
    BabyTrackerUpcomingVaccinesSensor,
    BabyTrackerRecentEntriesSensor,
)
