"""Constants for the Baby Tracker integration."""

DOMAIN = "baby_tracker"

# Configuration
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 15  # minutes

# Sensor types
SENSOR_TYPE_LAST_FEEDING = "last_feeding"
SENSOR_TYPE_LAST_DIAPER = "last_diaper"
SENSOR_TYPE_LAST_TEMPERATURE = "last_temperature"
SENSOR_TYPE_FEEDING_COUNT = "feeding_count"
SENSOR_TYPE_NURSING_MINUTES = "nursing_minutes"
SENSOR_TYPE_BOTTLE_OZ = "bottle_oz"
SENSOR_TYPE_BOTTLE_ML = "bottle_ml"
SENSOR_TYPE_DIAPER_COUNT = "diaper_count"
SENSOR_TYPE_POOPY_COUNT = "poopy_count"
SENSOR_TYPE_WET_COUNT = "wet_count"
SENSOR_TYPE_TIME_SINCE_LAST_FEEDING = "time_since_last_feeding"  
SENSOR_TYPE_TIME_SINCE_FEEDING = "time_since_last_feeding"

# Units
UNIT_MINUTES = "min"
UNIT_FEEDINGS = "feedings"
UNIT_DIAPERS = "diapers"
UNIT_OZ = "oz"
UNIT_ML = "ml"
UNIT_F = "°F"
UNIT_C = "°C"

# Attribute keys
ATTR_BABY_NAME = "baby_name"
ATTR_BABY_DOB = "baby_dob"
ATTR_BABY_GENDER = "baby_gender"
ATTR_TIME = "time"
ATTR_DURATION = "duration"
ATTR_AMOUNT = "amount"
ATTR_TYPE = "type"
ATTR_FEEDING_DETAILS = "feeding_details"
ATTR_DIAPER_DETAILS = "diaper_details"
ATTR_TEMPERATURE_F = "temperature_f"
ATTR_TEMPERATURE_C = "temperature_c"
ATTR_POOPY_STREAK = "poopy_streak"
