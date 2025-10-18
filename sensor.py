"""Sensor platform for Baby Tracker integration."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple 


from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    SENSOR_TYPE_LAST_FEEDING,
    SENSOR_TYPE_LAST_DIAPER,
    SENSOR_TYPE_LAST_TEMPERATURE,
    SENSOR_TYPE_FEEDING_COUNT,
    SENSOR_TYPE_NURSING_MINUTES,
    SENSOR_TYPE_BOTTLE_OZ,
    SENSOR_TYPE_BOTTLE_ML,
    SENSOR_TYPE_DIAPER_COUNT,
    SENSOR_TYPE_POOPY_COUNT,
    SENSOR_TYPE_WET_COUNT,
    UNIT_MINUTES,
    UNIT_FEEDINGS,
    UNIT_DIAPERS,
    UNIT_OZ,
    UNIT_ML,
    UNIT_F,
    UNIT_C,
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
    
    # Get baby info from coordinator to use in sensor naming
    baby_info = coordinator.data.get("baby_info", {})
    baby_name = baby_info.name if baby_info else "Baby"
    
    # Define all sensors to create
    sensors = [
        BabyTrackerLastFeedingSensor(coordinator, baby_name),
        BabyTrackerLastDiaperSensor(coordinator, baby_name),
        BabyTrackerLastTemperatureSensor(coordinator, baby_name),
        BabyTrackerFeedingCountSensor(coordinator, baby_name),
        BabyTrackerNursingMinutesSensor(coordinator, baby_name),
        BabyTrackerBottleOzSensor(coordinator, baby_name),
        BabyTrackerBottleMlSensor(coordinator, baby_name),
        BabyTrackerDiaperCountSensor(coordinator, baby_name),
        BabyTrackerPoopyCountSensor(coordinator, baby_name),
        BabyTrackerWetCountSensor(coordinator, baby_name),
        BabyTrackerTimeSinceLastFeedingSensor(coordinator, baby_name),

    ]
    
    async_add_entities(sensors, True)


class BabyTrackerSensor(CoordinatorEntity, SensorEntity):
    """Base class for Baby Tracker sensors."""

    def __init__(self, coordinator, baby_name, sensor_type, sensor_name, unit):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._baby_name = baby_name
        self._attr_name = f"{baby_name} {sensor_name}"
        self._attr_unit_of_measurement = unit
        self._attr_extra_state_attributes = {}
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_{sensor_type}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.email)},
            "name": f"Baby Tracker ({baby_name})",
            "manufacturer": "Baby Tracker",
            "model": "API Integration",
            "sw_version": "0.1.0",
        }

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


class BabyTrackerTimeSinceLastFeedingSensor(CoordinatorEntity, SensorEntity):
    """Sensor that displays time since last feeding in hours and minutes."""

    def __init__(self, coordinator, baby_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._attr_name = f"{baby_name} Time Since Last Feeding"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_time_since_last_feeding"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.email)},
            "name": f"Baby Tracker ({baby_name})",
            "manufacturer": "Baby Tracker",
            "model": "API Integration",
            "sw_version": "0.1.0",
        }
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
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "time_since_last_feeding" not in self.coordinator.data:
            return "Unknown"
            
        feeding_data = self.coordinator.data["time_since_last_feeding"]
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
        if not self.coordinator.data or "time_since_last_feeding" not in self.coordinator.data:
            return {}
            
        feeding_data = self.coordinator.data["time_since_last_feeding"]
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
        if not self.coordinator.data or "last_feeding" not in self.coordinator.data:
            return None
            
        feeding = self.coordinator.data["last_feeding"]
        if not feeding:
            return "Unknown"
            
        # Return feeding type as state
        return feeding.get("type", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "last_feeding" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        feeding = self.coordinator.data["last_feeding"]
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
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            return None
            
        # For now, just report when the last poopy diaper was
        diaper_summary = self.coordinator.data["diaper_summary"]
        if not diaper_summary or "last_poopy_time" not in diaper_summary:
            return "Unknown"
            
        return diaper_summary.get("last_poopy_time", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        diaper_summary = self.coordinator.data["diaper_summary"]
        if not diaper_summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "hours_since_last_poopy": diaper_summary.get("hours_since_last_poopy"),
            ATTR_POOPY_STREAK: diaper_summary.get("poopy_streak"),
            "total_diapers": diaper_summary.get("total_diapers"),
            "wet_count": diaper_summary.get("wet_count"),
            "poopy_count": diaper_summary.get("poopy_count"),
            "mixed_count": diaper_summary.get("mixed_count"),
        }
        
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
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            return None
            
        # For now, just report when the last poopy diaper was
        diaper_summary = self.coordinator.data["diaper_summary"]
        if not diaper_summary or "last_poopy_time" not in diaper_summary:
            return "Unknown"
            
        return diaper_summary.get("last_poopy_time", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        diaper_summary = self.coordinator.data["diaper_summary"]
        if not diaper_summary:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            "hours_since_last_poopy": diaper_summary.get("hours_since_last_poopy"),
            ATTR_POOPY_STREAK: diaper_summary.get("poopy_streak"),
            "total_diapers": diaper_summary.get("total_diapers"),
            "wet_count": diaper_summary.get("wet_count"),
            "poopy_count": diaper_summary.get("poopy_count"),
            "mixed_count": diaper_summary.get("mixed_count"),
        }
        
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
            UNIT_F,  # Default to Fahrenheit, can be overridden later
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "last_temperature" not in self.coordinator.data:
            return None
            
        temp = self.coordinator.data["last_temperature"]
        if not temp:
            return None
            
        # Return temperature in F by default
        return temp.get("temp")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "last_temperature" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        temp = self.coordinator.data["last_temperature"]
        if not temp:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        # Set attributes
        attrs = {
            ATTR_TIME: temp.get("time"),
            ATTR_TEMPERATURE_F: temp.get("temp"),  # Assuming temp is in F
            ATTR_TEMPERATURE_C: (temp.get("temp") - 32) * 5/9,  # Convert to C
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
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("total_feedings", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["feeding_summary"]
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
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("nursing_total_minutes", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["feeding_summary"]
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
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("bottle_amount_oz", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["feeding_summary"]
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
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["feeding_summary"]
        if not summary:
            return None
            
        return summary.get("bottle_amount_ml", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "feeding_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["feeding_summary"]
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
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("total_diapers", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["diaper_summary"]
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
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("poopy_count", 0) + summary.get("mixed_count", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["diaper_summary"]
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
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            return None
            
        summary = self.coordinator.data["diaper_summary"]
        if not summary:
            return None
            
        return summary.get("wet_count", 0) + summary.get("mixed_count", 0)

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "diaper_summary" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
            
        summary = self.coordinator.data["diaper_summary"]
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