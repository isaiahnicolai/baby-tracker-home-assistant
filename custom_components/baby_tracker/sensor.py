"""Sensor platform for Baby Tracker integration."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple 


from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import baby_device_info, baby_unique_id
from .const import (
    DOMAIN,
    SENSOR_TYPE_LAST_FEEDING,
    SENSOR_TYPE_LAST_DIAPER,
    SENSOR_TYPE_LAST_SLEEP,
    SENSOR_TYPE_LAST_NURSING,
    SENSOR_TYPE_LAST_BATH,
    SENSOR_TYPE_LAST_PUMP,
    SENSOR_TYPE_PUMP_SUMMARY,
    SENSOR_TYPE_LAST_MEDICINE,
    SENSOR_TYPE_LAST_GROWTH,
    SENSOR_TYPE_LAST_MILESTONE,
    SENSOR_TYPE_LAST_DOCTOR_VISIT,
    SENSOR_TYPE_LAST_VACCINE,
    SENSOR_TYPE_WEIGHT,
    SENSOR_TYPE_LENGTH,
    SENSOR_TYPE_HEAD,
    SENSOR_TYPE_LAST_TEMPERATURE,
    SENSOR_TYPE_FEEDING_COUNT,
    SENSOR_TYPE_NURSING_MINUTES,
    SENSOR_TYPE_BOTTLE_OZ,
    SENSOR_TYPE_BOTTLE_ML,
    SENSOR_TYPE_DIAPER_COUNT,
    SENSOR_TYPE_POOPY_COUNT,
    SENSOR_TYPE_WET_COUNT,
    SENSOR_TYPE_DAILY_SUMMARY,
    SENSOR_TYPE_FEEDING_TIMER,
    SENSOR_TYPE_BEDTIME_ANALYSIS,
    FEEDING_THRESHOLDS,
    UNIT_MINUTES,
    UNIT_FEEDINGS,
    UNIT_DIAPERS,
    UNIT_OZ,
    UNIT_ML,
    UNIT_F,
    UNIT_C,
    UNIT_SYSTEM_METRIC,
    ATTR_BABY_NAME,
    ATTR_BABY_DOB,
    ATTR_BABY_GENDER,
    ATTR_TIME,
    ATTR_DURATION,
    ATTR_AMOUNT,
    ATTR_TYPE,
    ATTR_FEEDING_DETAILS,
    ATTR_DIAPER_DETAILS,
    ATTR_TEMPERATURE_F,
    ATTR_TEMPERATURE_C,
    ATTR_POOPY_STREAK,
)

_LOGGER = logging.getLogger(__name__)

def calculate_time_since(time_str: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Calculate time since a given timestamp with robust parsing.
    
    Args:
        time_str (str): Timestamp string
    
    Returns:
        tuple: (hours, minutes) or (None, None) if parsing fails
    """
    try:
        # Try parsing with timezone
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            # Try parsing without timezone
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        
        # Calculate time difference
        current_time = datetime.now(timezone.utc)
        time_diff = current_time - dt
        
        # Calculate total hours and minutes
        total_hours = time_diff.total_seconds() / 3600
        hours = int(total_hours)
        minutes = int((total_hours - hours) * 60)
        
        return hours, minutes
    
    except Exception as e:
        _LOGGER.error(f"Error calculating time since: {e}")
        return None, None

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Baby Tracker sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []

    # Get list of all babies
    babies = coordinator.data.get("babies", [])

    if not babies:
        # Fallback to single baby mode for backwards compatibility
        baby_info = coordinator.data.get("baby_info")
        if baby_info:
            babies = [baby_info]

    # Create sensors for each baby
    for baby in babies:
        if not baby:
            continue
        baby_name = baby.name if hasattr(baby, 'name') else "Baby"

        # Create all sensor types for this baby
        baby_sensors = [
            BabyTrackerInfoSensor(coordinator, baby_name),  # New sensor for baby info
            BabyTrackerLastFeedingSensor(coordinator, baby_name),
            BabyTrackerLastDiaperSensor(coordinator, baby_name),
            BabyTrackerLastSleepSensor(coordinator, baby_name),
            BabyTrackerLastNursingSensor(coordinator, baby_name),
            BabyTrackerLastBathSensor(coordinator, baby_name),
            BabyTrackerLastPumpSensor(coordinator, baby_name),
            BabyTrackerPumpSummarySensor(coordinator, baby_name),
            BabyTrackerLastMedicineSensor(coordinator, baby_name),
            BabyTrackerLastMilestoneSensor(coordinator, baby_name),
            BabyTrackerLastDoctorVisitSensor(coordinator, baby_name),
            BabyTrackerLastVaccineSensor(coordinator, baby_name),
            BabyTrackerWeightSensor(coordinator, baby_name),
            BabyTrackerLengthSensor(coordinator, baby_name),
            BabyTrackerHeadSensor(coordinator, baby_name),
            BabyTrackerLastTemperatureSensor(coordinator, baby_name),
            BabyTrackerFeedingCountSensor(coordinator, baby_name),
            BabyTrackerNursingMinutesSensor(coordinator, baby_name),
            BabyTrackerBottleOzSensor(coordinator, baby_name),
            BabyTrackerBottleMlSensor(coordinator, baby_name),
            BabyTrackerDiaperCountSensor(coordinator, baby_name),
            BabyTrackerPoopyCountSensor(coordinator, baby_name),
            BabyTrackerWetCountSensor(coordinator, baby_name),
            BabyTrackerTimeSinceLastFeedingSensor(coordinator, baby_name),
            BabyTrackerDailySummarySensor(coordinator, baby_name),
            BabyTrackerFeedingTimerSensor(coordinator, baby_name),
            BabyTrackerBedtimeAnalysisSensor(coordinator, baby_name),
        ]

        sensors.extend(baby_sensors)

    async_add_entities(sensors, True)


class BabyTrackerSensor(CoordinatorEntity, SensorEntity):
    """Base class for Baby Tracker sensors."""

    def __init__(self, coordinator, baby_name, sensor_type, sensor_name, unit):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._baby_name = baby_name
        self._attr_has_entity_name = True
        self._attr_name = sensor_name
        self._attr_native_unit_of_measurement = unit
        self._attr_extra_state_attributes = {}
        # Make unique_id baby-specific to support multiple babies
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, sensor_type)
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    def _get_baby_data(self):
        """Get data for this sensor's baby from coordinator."""
        if not self.coordinator.data:
            return None

        # Try to get baby-specific data
        baby_data = self.coordinator.data.get("baby_data", {})
        # No fallback to the top-level data: that is the first baby's, and
        # showing it under another baby's name would be wrong
        return baby_data.get(self._baby_name)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Implement in child classes
        self.async_write_ha_state()


class BabyTrackerInfoSensor(CoordinatorEntity, SensorEntity):
    """Sensor that displays baby information including age."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._attr_has_entity_name = True
        self._attr_name = "Info"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "baby_info")
        self._attr_icon = "mdi:baby-face"
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def entity_picture(self) -> Optional[str]:
        """Return the baby's picture URL."""
        if not self.coordinator.data:
            return None
        baby_pictures = self.coordinator.data.get("baby_pictures", {})
        return baby_pictures.get(self._baby_name)

    @property
    def state(self):
        """Return the baby's age in days."""
        babies = self.coordinator.data.get("babies", [])
        if not babies:
            baby_info = self.coordinator.data.get("baby_info")
            if baby_info:
                babies = [baby_info]

        for baby in babies:
            if baby and hasattr(baby, 'name') and baby.name == self._baby_name:
                if hasattr(baby, 'dob') and baby.dob:
                    try:
                        # Parse DOB and calculate age in days
                        dob = datetime.strptime(baby.dob, "%Y-%m-%d %H:%M:%S %z")
                        age_delta = datetime.now(timezone.utc) - dob
                        age_days = age_delta.days

                        # Return age in appropriate format
                        if age_days < 30:
                            return f"{age_days} days"
                        elif age_days < 365:
                            months = age_days // 30
                            return f"{months} months"
                        else:
                            years = age_days // 365
                            remaining_months = (age_days % 365) // 30
                            if remaining_months > 0:
                                return f"{years}y {remaining_months}m"
                            return f"{years} years"
                    except:
                        return "Unknown"

        return "Unknown"

    @property
    def extra_state_attributes(self):
        """Return the baby's attributes."""
        babies = self.coordinator.data.get("babies", [])
        if not babies:
            baby_info = self.coordinator.data.get("baby_info")
            if baby_info:
                babies = [baby_info]

        for baby in babies:
            if baby and hasattr(baby, 'name') and baby.name == self._baby_name:
                attrs = {
                    "name": baby.name if hasattr(baby, 'name') else None,
                    "date_of_birth": baby.dob if hasattr(baby, 'dob') else None,
                    "due_date": baby.due_day if hasattr(baby, 'due_day') else None,
                    "gender": "Male" if (hasattr(baby, 'gender') and baby.gender) else "Female",
                    "baby_id": baby.object_id if hasattr(baby, 'object_id') else None,
                }

                # Calculate exact age if DOB is available
                if hasattr(baby, 'dob') and baby.dob:
                    try:
                        dob = datetime.strptime(baby.dob, "%Y-%m-%d %H:%M:%S %z")
                        age_delta = datetime.now(timezone.utc) - dob
                        attrs["age_days"] = age_delta.days
                        attrs["age_weeks"] = age_delta.days // 7
                        attrs["age_months"] = age_delta.days // 30
                    except:
                        pass

                return attrs

        return {}


class BabyTrackerTimeSinceLastFeedingSensor(BabyTrackerSensor):
    """Sensor that displays time since last feeding in hours and minutes."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(coordinator, baby_name, "time_since_last_feeding", "Time Since Last Feeding", "min")
        # Define feeding status categories for Google Home integration
        self._feeding_status_categories = {
            30: "Recently fed",
            120: "Fed recently",
            180: "Due for feeding soon",
            210: "Feeding due very soon",
            240: "Feeding overdue",
            float('inf'): "Feeding critically overdue"
        }

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "time_since_last_feeding" not in baby_data:
            return "Unknown"
            
        feeding_data = baby_data["time_since_last_feeding"]
        if not feeding_data:
            return "Unknown"
        
        # Get hours for display
        hours = feeding_data.get("hours_since_last_feeding", 0)
        if isinstance(hours, float):
            hours = int(hours)
        
        # Calculate minutes from the total hours
        total_hours = feeding_data.get("hours_since_last_feeding", 0)
        if total_hours is None:
            return "Unknown"
            
        total_minutes = total_hours * 60
        minutes = int(total_minutes % 60)
        
        # Return in format suitable for display and Google Home
        return f"{hours}h {minutes}m"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        baby_data = self._get_baby_data()
        if not baby_data or "time_since_last_feeding" not in baby_data:
            return {}
            
        feeding_data = baby_data["time_since_last_feeding"]
        if not feeding_data:
            return {}
        
        # Calculate total minutes for status categories
        total_hours = feeding_data.get("hours_since_last_feeding", 0)
        total_minutes = int(total_hours * 60)
        
        # Determine status category based on time thresholds
        status = "Unknown"
        for threshold, category in sorted(self._feeding_status_categories.items()):
            if total_minutes < threshold:
                status = category
                break
        
        # Create human-readable time string
        hours = int(total_minutes // 60)
        minutes = int(total_minutes % 60)
        
        if hours == 0:
            if minutes == 1:
                friendly_time = "1 minute ago"
            else:
                friendly_time = f"{minutes} minutes ago"
        elif hours == 1:
            friendly_time = f"1 hour and {minutes} minutes ago"
        else:
            friendly_time = f"{hours} hours and {minutes} minutes ago"
        
        # Include raw timestamps and calculated values in attributes
        attrs = {
            "last_feeding_time": feeding_data.get("last_feeding_time"),
            "time_difference": feeding_data.get("time_difference"),
            "total_minutes": total_minutes,
            "friendly_time": friendly_time,
            "feeding_status": status,
            "needs_feeding": total_minutes >= 180,  # Boolean flag for easier automation
            ATTR_BABY_NAME: self._baby_name
        }
        
        return attrs

class BabyTrackerLastFeedingSensor(BabyTrackerSensor):
    """Sensor that displays info about the last feeding."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_FEEDING,
            "Last Feeding",
            None,  # No unit for this sensor
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_feeding" not in baby_data:
            return None
            
        feeding = baby_data["last_feeding"]
        if not feeding:
            return "Unknown"
            
        # Return feeding type as state
        return feeding.get("type", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_feeding" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        feeding = baby_data["last_feeding"]
        if not feeding:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes based on feeding type
        attrs = {
            ATTR_TIME: feeding.get("time"),
            ATTR_TYPE: feeding.get("type"),
        }
        
        if feeding.get("type") == "Nursing":
            attrs[ATTR_DURATION] = feeding.get("total_duration")
            attrs["left_duration"] = feeding.get("left_duration")
            attrs["right_duration"] = feeding.get("right_duration")
            attrs["both_duration"] = feeding.get("both_duration")
        elif feeding.get("type") in ["Pumped", "Formula"]:
            attrs[ATTR_AMOUNT] = feeding.get("amount")
            attrs["amount_oz"] = feeding.get("amount_oz")
            attrs["amount_ml"] = feeding.get("amount_ml")
        
        # Add note if present
        if feeding.get("note"):
            attrs["note"] = feeding.get("note")
            
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()

class BabyTrackerLastDiaperSensor(BabyTrackerSensor):
    """Sensor that displays info about the last diaper change."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_DIAPER,
            "Last Diaper",
            None,  # No unit for this sensor
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_diaper" not in baby_data:
            return None

        last_diaper = baby_data["last_diaper"]
        if not last_diaper:
            return "Unknown"

        # Return the diaper status (Wet, Poopy, Mixed, Dry)
        return last_diaper.get("status", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_diaper" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_diaper = baby_data["last_diaper"]
        if not last_diaper:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes from Progress table data
        attrs = {
            ATTR_TIME: last_diaper.get("time"),
            "status": last_diaper.get("status"),
            "status_code": last_diaper.get("status_code"),
            "pee_color": last_diaper.get("pee_color"),
            "poo_color": last_diaper.get("poo_color"),
            "amount": last_diaper.get("amount"),
            "texture": last_diaper.get("texture"),
            "count": last_diaper.get("count"),
        }

        # Add note if present
        if last_diaper.get("note"):
            attrs["note"] = last_diaper.get("note")

        # Also include summary stats from diaper_summary if available
        if "diaper_summary" in baby_data:
            diaper_summary = baby_data["diaper_summary"]
            if diaper_summary:
                attrs["total_diapers_today"] = diaper_summary.get("total_diapers", 0)
                attrs["poopy_streak"] = diaper_summary.get("poopy_streak", 0)

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastSleepSensor(BabyTrackerSensor):
    """Sensor that displays info about the last sleep."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_SLEEP,
            "Last Sleep",
            None,  # No unit - will show "sleeping" or duration
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_sleep" not in baby_data:
            return None

        last_sleep = baby_data["last_sleep"]
        if not last_sleep:
            return "unknown"

        # CRITICAL: Check if currently sleeping (duration == 0)
        is_sleeping = last_sleep.get("is_sleeping", False)

        if is_sleeping:
            return "sleeping"
        else:
            # Return the completed sleep duration in minutes
            return f"{last_sleep.get('duration', 0)} min"

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_sleep" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_sleep = baby_data["last_sleep"]
        if not last_sleep:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        is_sleeping = last_sleep.get("is_sleeping", False)
        duration = last_sleep.get("duration", 0)
        current_duration = last_sleep.get("current_duration", 0)

        # Set attributes
        attrs = {
            ATTR_TIME: last_sleep.get("time"),
            "start_time": last_sleep.get("time"),
            "is_sleeping": is_sleeping,  # Critical for automations!
            "status": last_sleep.get("status", "unknown"),
            ATTR_DURATION: duration,  # Original duration from DB
            "current_duration": current_duration,  # Real-time if sleeping
        }

        # Add note if present
        if last_sleep.get("note"):
            attrs["note"] = last_sleep.get("note")

        # Calculate hours and minutes for display
        display_duration = current_duration if is_sleeping else duration
        if display_duration:
            hours = int(display_duration // 60)
            minutes = int(display_duration % 60)
            attrs["duration_hours"] = hours
            attrs["duration_minutes"] = minutes
            attrs["duration_formatted"] = f"{hours}h {minutes}m"

            # Add friendly message
            if is_sleeping:
                attrs["message"] = f"Sleeping for {hours}h {minutes}m"
            else:
                attrs["message"] = f"Slept {hours}h {minutes}m"

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastNursingSensor(BabyTrackerSensor):
    """Sensor that displays info about the last nursing session."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_NURSING,
            "Last Nursing",
            UNIT_MINUTES,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_nursing" not in baby_data:
            return None

        last_nursing = baby_data["last_nursing"]
        if not last_nursing:
            return None

        # Return the total nursing duration in minutes
        return last_nursing.get("total_duration", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_nursing" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_nursing = baby_data["last_nursing"]
        if not last_nursing:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes from Progress table data
        attrs = {
            ATTR_TIME: last_nursing.get("time"),
            ATTR_DURATION: last_nursing.get("total_duration"),
            "left_duration": last_nursing.get("left_duration"),
            "right_duration": last_nursing.get("right_duration"),
            "both_duration": last_nursing.get("both_duration"),
            "finish_side": last_nursing.get("finish_side"),
            "count": last_nursing.get("count"),
        }

        # Add note if present
        if last_nursing.get("note"):
            attrs["note"] = last_nursing.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastBathSensor(BabyTrackerSensor):
    """Sensor that displays info about the last bath."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_BATH,
            "Last Bath",
            None,  # No unit
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_bath" not in baby_data:
            return None

        last_bath = baby_data["last_bath"]
        if not last_bath:
            return "unknown"

        # Return the bath type (Bubble Bath, Sponge Bath, etc.)
        return last_bath.get("bath_type", "Bath")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_bath" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_bath = baby_data["last_bath"]
        if not last_bath:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_bath.get("time"),
            "bath_type": last_bath.get("bath_type", "Bath"),
        }

        # Add note if present
        if last_bath.get("note"):
            attrs["note"] = last_bath.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastTemperatureSensor(BabyTrackerSensor):
    """Sensor that displays the last temperature reading."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_TEMPERATURE,
            "Temperature",
            UNIT_C if coordinator.unit_system == UNIT_SYSTEM_METRIC else UNIT_F,
        )
        self._metric = coordinator.unit_system == UNIT_SYSTEM_METRIC

    @property
    def state(self):
        """Return the state of the sensor, in the unit chosen for this entry."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_temperature" not in baby_data:
            return None

        temp = baby_data["last_temperature"]
        if not temp:
            return None

        return temp.get("celsius" if self._metric else "fahrenheit")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_temperature" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        temp = baby_data["last_temperature"]
        if not temp:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            ATTR_TIME: temp.get("time"),
            ATTR_TEMPERATURE_F: temp.get("fahrenheit"),
            ATTR_TEMPERATURE_C: temp.get("celsius"),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerFeedingCountSensor(BabyTrackerSensor):
    """Sensor that displays the feeding count."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_FEEDING_COUNT,
            "Feedings",
            UNIT_FEEDINGS,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            return None
            
        summary = baby_data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("total_feedings", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["feeding_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "nursing_count": summary.get("nursing_count", 0),
            "formula_count": summary.get("formula_count", 0),
            "pumped_count": summary.get("pumped_count", 0),
            "bottle_feedings": summary.get("bottle_feedings", 0),
            "avg_feedings_per_day": summary.get("avg_feedings_per_day", 0),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerNursingMinutesSensor(BabyTrackerSensor):
    """Sensor that displays nursing minutes."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_NURSING_MINUTES,
            "Nursing Minutes",
            UNIT_MINUTES,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            return None
            
        summary = baby_data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("nursing_total_minutes", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["feeding_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "left_minutes": summary.get("nursing_left_minutes", 0),
            "right_minutes": summary.get("nursing_right_minutes", 0),
            "avg_nursing_minutes_per_day": summary.get("avg_nursing_minutes_per_day", 0),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerBottleOzSensor(BabyTrackerSensor):
    """Sensor that displays bottle amount in oz."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_BOTTLE_OZ,
            "Bottle oz",
            UNIT_OZ,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            return None
            
        summary = baby_data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("bottle_amount_oz", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["feeding_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "formula_amount_oz": summary.get("formula_amount_oz", 0),
            "pumped_amount_oz": summary.get("pumped_amount_oz", 0),
            "avg_bottle_oz_per_day": summary.get("avg_bottle_oz_per_day", 0),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerBottleMlSensor(BabyTrackerSensor):
    """Sensor that displays bottle amount in ml."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_BOTTLE_ML,
            "Bottle ml",
            UNIT_ML,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            return None
            
        summary = baby_data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("bottle_amount_ml", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "feeding_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["feeding_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "formula_amount_ml": summary.get("formula_amount_ml", 0),
            "pumped_amount_ml": summary.get("pumped_amount_ml", 0),
            "avg_bottle_ml_per_day": summary.get("avg_bottle_ml_per_day", 0),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerDiaperCountSensor(BabyTrackerSensor):
    """Sensor that displays diaper count."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_DIAPER_COUNT,
            "Diapers",
            UNIT_DIAPERS,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            return None
            
        summary = baby_data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("total_diapers", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["diaper_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "avg_diapers_per_day": summary.get("avg_diapers_per_day", 0),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerPoopyCountSensor(BabyTrackerSensor):
    """Sensor that displays poopy diaper count."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_POOPY_COUNT,
            "Poopy Diapers",
            UNIT_DIAPERS,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            return None
            
        summary = baby_data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("poopy_count", 0) + summary.get("mixed_count", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["diaper_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "poopy_streak": summary.get("poopy_streak", 0),
            "avg_poopy_per_day": summary.get("avg_poopy_per_day", 0),
            "last_poopy_time": summary.get("last_poopy_time"),
            "hours_since_last_poopy": summary.get("hours_since_last_poopy"),
        }
        
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerWetCountSensor(BabyTrackerSensor):
    """Sensor that displays wet diaper count."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_WET_COUNT,
            "Wet Diapers",
            UNIT_DIAPERS,
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            return None
            
        summary = baby_data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("wet_count", 0) + summary.get("mixed_count", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "diaper_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = baby_data["diaper_summary"]
        if not summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "avg_wet_per_day": summary.get("avg_wet_per_day", 0),
            "pee_color_distribution": summary.get("pee_by_color", {}),
        }

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastPumpSensor(BabyTrackerSensor):
    """Sensor that displays info about the last pump session."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_PUMP,
            "Last Pump",
            None,  # No unit for the main state
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_pump" not in baby_data:
            return None

        last_pump = baby_data["last_pump"]
        if not last_pump:
            return "unknown"

        # Return the total amount pumped
        total_amount = last_pump.get("total_amount", 0)
        unit = last_pump.get("unit", "ml")
        return f"{total_amount} {unit}"

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_pump" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_pump = baby_data["last_pump"]
        if not last_pump:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_pump.get("time"),
            "left_duration": last_pump.get("left_duration", 0),
            "right_duration": last_pump.get("right_duration", 0),
            "total_duration": last_pump.get("total_duration", 0),
            "left_amount": last_pump.get("left_amount", 0),
            "right_amount": last_pump.get("right_amount", 0),
            "total_amount": last_pump.get("total_amount", 0),
            "unit": last_pump.get("unit", "ml"),
            "finish_side": last_pump.get("finish_side", "Unknown"),
        }

        # Add note if present
        if last_pump.get("note"):
            attrs["note"] = last_pump.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerPumpSummarySensor(BabyTrackerSensor):
    """Sensor that displays pump session statistics."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_PUMP_SUMMARY,
            "Pump Summary",
            "sessions",  # Unit for total sessions
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "pump_summary" not in baby_data:
            return None

        pump_summary = baby_data["pump_summary"]
        if not pump_summary:
            return 0

        # Return total number of sessions
        return pump_summary.get("total_sessions", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "pump_summary" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        pump_summary = baby_data["pump_summary"]
        if not pump_summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            "total_sessions": pump_summary.get("total_sessions", 0),
            "total_amount": pump_summary.get("total_amount", 0),
            "total_duration": pump_summary.get("total_duration", 0),
            "avg_amount_per_session": pump_summary.get("avg_amount_per_session", 0),
            "avg_duration_per_session": pump_summary.get("avg_duration_per_session", 0),
            "sessions_per_day": pump_summary.get("sessions_per_day", 0),
            "unit": pump_summary.get("unit", "ml"),
        }

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastMedicineSensor(BabyTrackerSensor):
    """Sensor that displays info about the last medicine dose."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_MEDICINE,
            "Last Medicine",
            None,  # No unit for the main state
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_medicine" not in baby_data:
            return None

        last_medicine = baby_data["last_medicine"]
        if not last_medicine:
            return "unknown"

        # Return the medicine name
        return last_medicine.get("medicine_name", "Unknown Medicine")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_medicine" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_medicine = baby_data["last_medicine"]
        if not last_medicine:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_medicine.get("time"),
            "medicine_name": last_medicine.get("medicine_name", "Unknown"),
            ATTR_AMOUNT: last_medicine.get("amount", 0),
            "unit": last_medicine.get("unit", ""),
            "med_id": last_medicine.get("med_id"),
        }

        # Add note if present
        if last_medicine.get("note"):
            attrs["note"] = last_medicine.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastMilestoneSensor(BabyTrackerSensor):
    """Sensor that displays info about the last milestone."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_MILESTONE,
            "Last Milestone",
            None,  # No unit for the main state
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_milestone" not in baby_data:
            return None

        last_milestone = baby_data["last_milestone"]
        if not last_milestone:
            return "unknown"

        # Return the milestone name
        return last_milestone.get("milestone_name", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_milestone" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_milestone = baby_data["last_milestone"]
        if not last_milestone:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_milestone.get("time"),
            "milestone_name": last_milestone.get("milestone_name", "Unknown"),
            "milestone_description": last_milestone.get("milestone_description", ""),
            "milestone_selection_id": last_milestone.get("milestone_selection_id"),
        }

        # Add note if present
        if last_milestone.get("note"):
            attrs["note"] = last_milestone.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastDoctorVisitSensor(BabyTrackerSensor):
    """Sensor that displays info about the last doctor visit."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_DOCTOR_VISIT,
            "Last Doctor Visit",
            None,  # No unit for the main state
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_doctor_visit" not in baby_data:
            return None

        last_doctor_visit = baby_data["last_doctor_visit"]
        if not last_doctor_visit:
            return "unknown"

        # Return the time as the main state
        return last_doctor_visit.get("time", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_doctor_visit" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_doctor_visit = baby_data["last_doctor_visit"]
        if not last_doctor_visit:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_doctor_visit.get("time"),
            "is_appointment": last_doctor_visit.get("is_appointment", False),
            "visit_type": last_doctor_visit.get("visit_type", 0),
            "symptom": last_doctor_visit.get("symptom", ""),
            "doctor_note": last_doctor_visit.get("doctor_note", ""),
        }

        # Add note if present
        if last_doctor_visit.get("note"):
            attrs["note"] = last_doctor_visit.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLastVaccineSensor(BabyTrackerSensor):
    """Sensor that displays info about the last vaccine."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_VACCINE,
            "Last Vaccine",
            None,  # No unit for the main state
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_vaccine" not in baby_data:
            return None

        last_vaccine = baby_data["last_vaccine"]
        if not last_vaccine:
            return "unknown"

        # Return the vaccine name
        return last_vaccine.get("vaccine_name", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_vaccine" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_vaccine = baby_data["last_vaccine"]
        if not last_vaccine:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_vaccine.get("time"),
            "vaccine_name": last_vaccine.get("vaccine_name", "Unknown"),
            "vaccine_description": last_vaccine.get("vaccine_description", ""),
            "vacc_id": last_vaccine.get("vacc_id"),
        }

        # Add note if present
        if last_vaccine.get("note"):
            attrs["note"] = last_vaccine.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerWeightSensor(BabyTrackerSensor):
    """Sensor that displays the most recent weight measurement."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_WEIGHT,
            "Weight",
            None,  # Unit will be set dynamically
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        # Return weight value
        return last_growth.get("weight", 0)

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        return last_growth.get("weight_unit", "lbs")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_growth = baby_data["last_growth"]
        if not last_growth:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_growth.get("time"),
            "weight": last_growth.get("weight", 0),
            "unit": last_growth.get("weight_unit", "lbs"),
        }

        # Add note if present
        if last_growth.get("note"):
            attrs["note"] = last_growth.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerLengthSensor(BabyTrackerSensor):
    """Sensor that displays the most recent length/height measurement."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LENGTH,
            "Length",
            None,  # Unit will be set dynamically
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        # Return length value
        return last_growth.get("length", 0)

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        return last_growth.get("length_unit", "in")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_growth = baby_data["last_growth"]
        if not last_growth:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_growth.get("time"),
            "length": last_growth.get("length", 0),
            "unit": last_growth.get("length_unit", "in"),
        }

        # Add note if present
        if last_growth.get("note"):
            attrs["note"] = last_growth.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


class BabyTrackerHeadSensor(BabyTrackerSensor):
    """Sensor that displays the most recent head circumference measurement."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_HEAD,
            "Head Circumference",
            None,  # Unit will be set dynamically
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        # Return head value
        return last_growth.get("head", 0)

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            return None

        last_growth = baby_data["last_growth"]
        if not last_growth:
            return None

        return last_growth.get("length_unit", "in")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        baby_data = self._get_baby_data()
        if not baby_data or "last_growth" not in baby_data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_growth = baby_data["last_growth"]
        if not last_growth:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_growth.get("time"),
            "head": last_growth.get("head", 0),
            "unit": last_growth.get("length_unit", "in"),
        }

        # Add note if present
        if last_growth.get("note"):
            attrs["note"] = last_growth.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()


def _get_baby_age_days(baby_info):
    """Calculate baby's age in days from DOB."""
    if not baby_info or not hasattr(baby_info, "dob") or not baby_info.dob:
        return None
    try:
        dob = datetime.strptime(baby_info.dob, "%Y-%m-%d %H:%M:%S %z")
        age_delta = datetime.now(timezone.utc) - dob
        return age_delta.days
    except (ValueError, TypeError):
        return None


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


class BabyTrackerDailySummarySensor(BabyTrackerSensor):
    """Sensor that displays today's daily summary."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_DAILY_SUMMARY,
            "Daily Summary",
            UNIT_FEEDINGS,
        )
        self._attr_icon = "mdi:clipboard-list"

    @property
    def state(self):
        """Return total feedings today."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        summary = baby_data.get("daily_summary")
        if not summary:
            return None
        return summary.get("total_feedings", 0)

    @property
    def extra_state_attributes(self):
        """Return daily summary attributes."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return {}
        summary = baby_data.get("daily_summary")
        if not summary:
            return {}
        return {
            "formula_oz": summary.get("formula_oz", 0),
            "nursing_minutes": summary.get("nursing_minutes", 0),
            "diaper_count": summary.get("diaper_count", 0),
            "sleep_hours": summary.get("sleep_hours", 0),
        }


class BabyTrackerFeedingTimerSensor(BabyTrackerSensor):
    """Sensor showing minutes until next feeding is due."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_FEEDING_TIMER,
            "Next Feeding",
            "min",
        )

    def _get_baby_info(self):
        """Get the Baby object for this sensor's baby."""
        if not self.coordinator.data:
            return None
        babies = self.coordinator.data.get("babies", [])
        for baby in babies:
            if baby and hasattr(baby, "name") and baby.name == self._baby_name:
                return baby
        return self.coordinator.data.get("baby_info")

    def _compute_timer(self):
        """Compute feeding timer values."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return None, None, None, None

        time_data = baby_data.get("time_since_last_feeding")
        if not time_data:
            return None, None, None, None

        hours_since = time_data.get("hours_since_last_feeding")
        if hours_since is None:
            return None, None, None, None

        baby_info = self._get_baby_info()
        age_days = _get_baby_age_days(baby_info)
        threshold_hours, _ = _get_age_threshold(age_days, FEEDING_THRESHOLDS)

        minutes_remaining = int(threshold_hours * 60 - hours_since * 60)

        if minutes_remaining > 30:
            status = "ok"
        elif minutes_remaining > 0:
            status = "soon"
        else:
            status = "overdue"

        # Estimate next feeding time
        last_feed_time_str = time_data.get("last_feeding_time")
        next_feeding_time = None
        if last_feed_time_str:
            try:
                try:
                    lft = datetime.strptime(last_feed_time_str, "%Y-%m-%d %H:%M:%S %z")
                except ValueError:
                    lft = datetime.strptime(last_feed_time_str, "%Y-%m-%d %H:%M:%S")
                    lft = lft.replace(tzinfo=timezone.utc)
                from datetime import timedelta
                next_dt = lft + timedelta(hours=threshold_hours)
                next_feeding_time = next_dt.strftime("%Y-%m-%d %H:%M:%S %z")
            except Exception:
                pass

        return minutes_remaining, status, threshold_hours, next_feeding_time

    @property
    def icon(self):
        """Return icon based on status."""
        _, status, _, _ = self._compute_timer()
        if status == "overdue":
            return "mdi:timer-alert-outline"
        return "mdi:timer-outline"

    @property
    def state(self):
        """Return minutes remaining until next feeding."""
        minutes_remaining, _, _, _ = self._compute_timer()
        return minutes_remaining

    @property
    def extra_state_attributes(self):
        """Return feeding timer attributes."""
        minutes_remaining, status, threshold_hours, next_feeding_time = self._compute_timer()
        baby_data = self._get_baby_data()
        hours_since = None
        if baby_data:
            time_data = baby_data.get("time_since_last_feeding")
            if time_data:
                hours_since = time_data.get("hours_since_last_feeding")

        attrs = {
            "status": status,
            "threshold_hours": threshold_hours,
            "hours_since_last": round(hours_since, 2) if hours_since is not None else None,
        }
        if next_feeding_time:
            attrs["next_feeding_time"] = next_feeding_time
        return attrs


class BabyTrackerBedtimeAnalysisSensor(BabyTrackerSensor):
    """Sensor showing average bedtime with per-day data for graphing."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_BEDTIME_ANALYSIS,
            "Average Bedtime",
            None,
        )
        self._attr_icon = "mdi:weather-night"

    @property
    def state(self):
        """Return the average bedtime string."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return None
        analysis = baby_data.get("sleep_analysis")
        if not analysis:
            return None
        return analysis.get("avg_bedtime", "N/A")

    @property
    def extra_state_attributes(self):
        """Return bedtime analysis attributes for graphing."""
        baby_data = self._get_baby_data()
        if not baby_data:
            return {}
        analysis = baby_data.get("sleep_analysis")
        if not analysis:
            return {}
        return {
            "avg_wake_time": analysis.get("avg_wake_time"),
            "avg_sleep_duration_hours": analysis.get("avg_sleep_duration_hours"),
            "avg_bedtime_minutes": analysis.get("avg_bedtime_minutes"),
            "avg_wake_time_minutes": analysis.get("avg_wake_time_minutes"),
            "days_analyzed": analysis.get("days_analyzed"),
            "per_day": analysis.get("per_day", []),
        }