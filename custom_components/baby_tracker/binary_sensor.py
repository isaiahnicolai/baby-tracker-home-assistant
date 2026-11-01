"""Binary sensor platform for Baby Tracker health alerts."""
import logging
from datetime import UTC, datetime

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ALERT_TYPE_FEED_DUE,
    ALERT_TYPE_FEEDING_OVERDUE,
    ALERT_TYPE_FEVER,
    ALERT_TYPE_INTAKE_LOW,
    ALERT_TYPE_LONG_SLEEP,
    ALERT_TYPE_LOW_WET_DIAPERS,
    ALERT_TYPE_NO_POOP,
    ALERT_TYPE_WAKE_TO_FEED,
    ATTR_AGE_BRACKET,
    ATTR_ALERT_TYPE,
    ATTR_BABY_AGE_DAYS,
    ATTR_BABY_NAME,
    ATTR_CURRENT_VALUE,
    ATTR_DISMISSED,
    ATTR_THRESHOLD,
    DOMAIN,
    FEEDING_THRESHOLDS,
    FEVER_THRESHOLD_F,
    LONG_SLEEP_THRESHOLDS,
    LOW_WET_CHECK_HOUR,
    LOW_WET_MIN_AGE_DAYS,
    LOW_WET_THRESHOLD,
    NIGHT_END_HOUR,
    NIGHT_START_HOUR,
    NO_POOP_THRESHOLDS,
)
from .entity import ClockTickMixin, baby_device_info, baby_unique_id, hours_since_feeding

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _get_baby_age_days(baby_info):
    """Calculate baby's age in days from DOB."""
    if not baby_info or not hasattr(baby_info, "dob") or not baby_info.dob:
        return None
    try:
        dob = datetime.strptime(baby_info.dob, "%Y-%m-%d %H:%M:%S %z")
        age_delta = datetime.now(UTC) - dob
        return age_delta.days
    except (ValueError, TypeError):
        return None


def _get_age_threshold(age_days, thresholds):
    """Return (threshold_value, bracket_label) for the given age."""
    if age_days is None:
        # Default to first bracket
        value = thresholds[0][2]
        return value, f"0-{thresholds[0][1]}d"
    for min_days, max_days, value in thresholds:
        if min_days <= age_days <= max_days:
            return value, f"{min_days}-{max_days}d"
    # Fallback to last bracket
    last = thresholds[-1]
    return last[2], f"{last[0]}+d"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up Baby Tracker health alert binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    babies = coordinator.data.get("babies", [])
    if not babies:
        baby_info = coordinator.data.get("baby_info")
        if baby_info:
            babies = [baby_info]

    for baby in babies:
        if not baby:
            continue
        baby_name = baby.name if hasattr(baby, "name") else "Baby"

        alert_entities = [
            FeedingOverdueAlert(coordinator, baby_name),
            NoPoopAlert(coordinator, baby_name),
            LowWetDiapersAlert(coordinator, baby_name),
            FeverAlert(coordinator, baby_name),
            LongSleepAlert(coordinator, baby_name),
            IntakeLowAlert(coordinator, baby_name),
            FeedDueAlert(coordinator, baby_name),
            WakeToFeedAlert(coordinator, baby_name),
        ]
        entities.extend(alert_entities)
        entities.append(BabyTrackerNightModeSensor(coordinator, baby_name))

    coordinator._alert_entities.extend(entities)
    async_add_entities(entities)


class BabyTrackerAlert(CoordinatorEntity, BinarySensorEntity):
    """Base class for Baby Tracker health alert binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _alert_type = None  # the unique ID suffix and translation key, set by each alert

    def __init__(self, coordinator, baby_name):
        """Initialize the alert."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._dismissed = False
        self._was_clear = True

        self._attr_translation_key = self._alert_type
        self._attr_unique_id = (
            baby_unique_id(coordinator, baby_name, self._alert_type)
        )
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    def _get_baby_data(self):
        """Get data for this alert's baby from coordinator."""
        if not self.coordinator.data:
            return None
        baby_data = self.coordinator.data.get("baby_data", {})
        return baby_data.get(self._baby_name)

    def _get_baby_info(self):
        """Get the Baby object for this alert's baby."""
        if not self.coordinator.data:
            return None
        babies = self.coordinator.data.get("babies", [])
        for baby in babies:
            if baby and hasattr(baby, "name") and baby.name == self._baby_name:
                return baby
        return self.coordinator.data.get("baby_info")

    def _evaluate_condition(self):
        """Evaluate the alert condition. Returns True if condition is met (alert should fire)."""
        raise NotImplementedError

    def _get_current_value(self):
        """Return the current value being checked."""
        return None

    def _get_threshold_info(self):
        """Return (threshold_value, bracket_label) for this alert."""
        return None, None

    @property
    def is_on(self):
        """Return True if alert is active (condition met and not dismissed)."""
        raw_condition = self._evaluate_condition()

        if not raw_condition:
            # Condition is OFF - mark as clear, reset dismissed for next episode
            self._was_clear = True
            self._dismissed = False
            return False

        # Condition is ON
        if self._was_clear:
            # New episode starting
            self._was_clear = False
            self._dismissed = False

        if self._dismissed:
            return False

        return True

    @property
    def extra_state_attributes(self):
        """Return alert attributes."""
        baby_info = self._get_baby_info()
        age_days = _get_baby_age_days(baby_info)
        threshold, bracket = self._get_threshold_info()

        return {
            ATTR_ALERT_TYPE: self._alert_type,
            ATTR_BABY_NAME: self._baby_name,
            ATTR_THRESHOLD: threshold,
            ATTR_CURRENT_VALUE: self._get_current_value(),
            ATTR_BABY_AGE_DAYS: age_days,
            ATTR_AGE_BRACKET: bracket,
            ATTR_DISMISSED: self._dismissed,
            "raw_condition": self._evaluate_condition(),
        }

    def dismiss(self):
        """Dismiss this alert until the condition clears and re-triggers."""
        self._dismissed = True
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class FeedingOverdueAlert(ClockTickMixin, BabyTrackerAlert):
    """Alert when feeding is overdue based on age thresholds."""

    _alert_type = ALERT_TYPE_FEEDING_OVERDUE

    def _get_hours_since_feeding(self):
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        return hours_since_feeding(self.coordinator, baby_data.get("time_since_last_feeding"))

    def _get_threshold_info(self):
        age_days = _get_baby_age_days(self._get_baby_info())
        return _get_age_threshold(age_days, FEEDING_THRESHOLDS)

    def _get_current_value(self):
        hours = self._get_hours_since_feeding()
        return round(hours, 1) if hours is not None else None

    def _evaluate_condition(self):
        hours = self._get_hours_since_feeding()
        if hours is None:
            return False
        threshold, _ = self._get_threshold_info()
        return hours >= threshold


class NoPoopAlert(BabyTrackerAlert):
    """Alert when baby hasn't pooped for too long based on age thresholds."""

    _alert_type = ALERT_TYPE_NO_POOP

    def _get_hours_since_poop(self):
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        diaper_summary = baby_data.get("diaper_summary")
        if not diaper_summary:
            return None
        return diaper_summary.get("hours_since_last_poopy")

    def _get_threshold_info(self):
        age_days = _get_baby_age_days(self._get_baby_info())
        return _get_age_threshold(age_days, NO_POOP_THRESHOLDS)

    def _get_current_value(self):
        hours = self._get_hours_since_poop()
        return round(hours, 1) if hours is not None else None

    def _evaluate_condition(self):
        hours = self._get_hours_since_poop()
        if hours is None:
            return False
        threshold, _ = self._get_threshold_info()
        return hours >= threshold


class LowWetDiapersAlert(BabyTrackerAlert):
    """Alert when wet diaper count is low, checked after 8pm for babies > 3 days old."""

    _alert_type = ALERT_TYPE_LOW_WET_DIAPERS

    def _get_today_wet_count(self):
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        return baby_data.get("today_wet_count")

    def _get_threshold_info(self):
        return LOW_WET_THRESHOLD, f">{LOW_WET_MIN_AGE_DAYS}d, after {LOW_WET_CHECK_HOUR}:00"

    def _get_current_value(self):
        return self._get_today_wet_count()

    def _evaluate_condition(self):
        # Only check after LOW_WET_CHECK_HOUR (8pm)
        now = dt_util.now()
        if now.hour < LOW_WET_CHECK_HOUR:
            return False

        # Only for babies older than LOW_WET_MIN_AGE_DAYS
        age_days = _get_baby_age_days(self._get_baby_info())
        if age_days is None or age_days <= LOW_WET_MIN_AGE_DAYS:
            return False

        wet_count = self._get_today_wet_count()
        if wet_count is None:
            return False

        return wet_count < LOW_WET_THRESHOLD


class FeverAlert(BabyTrackerAlert):
    """Alert when baby's temperature is >= 100.4F."""

    _alert_type = ALERT_TYPE_FEVER

    def _get_temp(self):
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        temp_data = baby_data.get("last_temperature")
        if not temp_data:
            return None
        # Compared in Fahrenheit whatever scale the reading was recorded in
        return temp_data.get("fahrenheit")

    def _get_threshold_info(self):
        return FEVER_THRESHOLD_F, "all ages"

    def _get_current_value(self):
        return self._get_temp()

    def _evaluate_condition(self):
        temp = self._get_temp()
        if temp is None:
            return False
        return temp >= FEVER_THRESHOLD_F


class LongSleepAlert(BabyTrackerAlert):
    """Alert when baby has been sleeping too long based on age thresholds."""

    _alert_type = ALERT_TYPE_LONG_SLEEP

    def _get_sleep_info(self):
        """Return (is_sleeping, current_duration_hours) or (False, None)."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return False, None
        last_sleep = baby_data.get("last_sleep")
        if not last_sleep:
            return False, None
        is_sleeping = last_sleep.get("is_sleeping", False)
        if not is_sleeping:
            return False, None
        current_duration_minutes = last_sleep.get("current_duration", 0)
        return True, current_duration_minutes / 60.0

    def _get_threshold_info(self):
        age_days = _get_baby_age_days(self._get_baby_info())
        return _get_age_threshold(age_days, LONG_SLEEP_THRESHOLDS)

    def _get_current_value(self):
        is_sleeping, hours = self._get_sleep_info()
        if not is_sleeping or hours is None:
            return None
        return round(hours, 1)

    def _evaluate_condition(self):
        is_sleeping, hours = self._get_sleep_info()
        if not is_sleeping or hours is None:
            return False
        threshold, _ = self._get_threshold_info()
        return hours >= threshold


class InsightAlert(BabyTrackerAlert):
    """Base for alerts driven by a baby's insights (see client/insights.py)."""

    def _get_insight(self, section):
        """One part of this baby's insights as a dict (empty when missing)."""
        baby_data = self._get_baby_data() or {}
        return (baby_data.get("insights") or {}).get(section) or {}

    @staticmethod
    def _has_passed(iso_time):
        """True once the current time is at or past an ISO timestamp (False if missing)."""
        moment = dt_util.parse_datetime(iso_time) if iso_time else None
        return moment is not None and moment.tzinfo is not None and dt_util.utcnow() >= moment


class IntakeLowAlert(InsightAlert):
    """Alert when the last 24 hours of bottle milk is under 150 ml/kg."""

    _alert_type = ALERT_TYPE_INTAKE_LOW

    def _get_threshold_info(self):
        return self._get_insight("intake").get("expected_min_ml"), "ml in 24h"

    def _get_current_value(self):
        actual = self._get_insight("intake").get("actual_ml")
        return round(actual) if actual is not None else None

    def _evaluate_condition(self):
        return self._get_insight("intake").get("status") == "low"


class FeedDueAlert(ClockTickMixin, InsightAlert):
    """Alert when the predicted time of the next feed has passed."""

    _alert_type = ALERT_TYPE_FEED_DUE

    def _get_current_value(self):
        return self._get_insight("next_feed").get("predicted_at")

    def _evaluate_condition(self):
        return self._has_passed(self._get_current_value())


class WakeToFeedAlert(ClockTickMixin, InsightAlert):
    """Alert when a baby who should be woken to feed has gone past the longest sensible gap."""

    _alert_type = ALERT_TYPE_WAKE_TO_FEED

    def _get_threshold_info(self):
        return self._get_insight("next_feed").get("max_gap_hours"), "hours between feeds"

    def _get_current_value(self):
        return self._get_insight("next_feed").get("wake_by")

    def _evaluate_condition(self):
        return self._has_passed(self._get_current_value())


class BabyTrackerNightModeSensor(ClockTickMixin, CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that indicates if the baby is in night mode (sleeping at night)."""

    _attr_has_entity_name = True
    _attr_translation_key = "night_mode"

    def __init__(self, coordinator, baby_name):
        """Initialize the night mode sensor."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._attr_unique_id = (
            baby_unique_id(coordinator, baby_name, "night_mode")
        )
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    def _get_baby_data(self):
        """Get data for this sensor's baby from coordinator."""
        if not self.coordinator.data:
            return None
        baby_data = self.coordinator.data.get("baby_data", {})
        return baby_data.get(self._baby_name)

    @property
    def is_on(self):
        """Return True when baby is sleeping during night hours."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return False

        last_sleep = baby_data.get("last_sleep")
        if not last_sleep:
            return False

        is_sleeping = last_sleep.get("is_sleeping", False)
        if not is_sleeping:
            return False

        now = dt_util.now()
        current_hour = now.hour
        # Night hours: 7pm (19) to 7am (7) — wraps around midnight
        is_night = current_hour >= NIGHT_START_HOUR or current_hour < NIGHT_END_HOUR
        return is_night

    @property
    def extra_state_attributes(self):
        """Return night mode attributes."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return {}

        last_sleep = baby_data.get("last_sleep") or {}
        return {
            "sleep_start": last_sleep.get("time"),
            "current_duration": last_sleep.get("current_duration", 0),
            "night_start_hour": NIGHT_START_HOUR,
            "night_end_hour": NIGHT_END_HOUR,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
