"""Constants for the Baby Tracker integration."""

DOMAIN = "baby_tracker"
VERSION = "0.2.0"  # keep in sync with manifest.json and client/__init__.py

# Configuration
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_UNIT_SYSTEM = "unit_system"
CONF_DEVICE_UUID = "device_uuid"  # This integration's own device identity on the sync server
DEFAULT_SCAN_INTERVAL = 15  # minutes
DEFAULT_UNIT_SYSTEM = "imperial"  # "imperial" (oz, lbs, F) or "metric" (ml, kg, C)

# Unit system options
UNIT_SYSTEM_IMPERIAL = "imperial"
UNIT_SYSTEM_METRIC = "metric"

# Sensor types
SENSOR_TYPE_LAST_FEEDING = "last_feeding"
SENSOR_TYPE_LAST_DIAPER = "last_diaper"
SENSOR_TYPE_LAST_SLEEP = "last_sleep"
SENSOR_TYPE_LAST_NURSING = "last_nursing"
SENSOR_TYPE_LAST_BATH = "last_bath"
SENSOR_TYPE_LAST_PUMP = "last_pump"
SENSOR_TYPE_PUMP_SUMMARY = "pump_summary"
SENSOR_TYPE_LAST_MEDICINE = "last_medicine"
SENSOR_TYPE_LAST_GROWTH = "last_growth"
SENSOR_TYPE_LAST_MILESTONE = "last_milestone"
SENSOR_TYPE_LAST_DOCTOR_VISIT = "last_doctor_visit"
SENSOR_TYPE_LAST_VACCINE = "last_vaccine"
SENSOR_TYPE_WEIGHT = "weight"
SENSOR_TYPE_LENGTH = "length"
SENSOR_TYPE_HEAD = "head"
SENSOR_TYPE_LAST_TEMPERATURE = "last_temperature"
SENSOR_TYPE_FEEDING_COUNT = "feeding_count"
SENSOR_TYPE_NURSING_MINUTES = "nursing_minutes"
SENSOR_TYPE_BOTTLE_VOLUME = "bottle_ml"  # keeps the unique ID of the old "Bottle ml" sensor
SENSOR_TYPE_LAST_FEEDING_TIME = "last_feeding_time"
SENSOR_TYPE_LAST_DIAPER_TIME = "last_diaper_time"
SENSOR_TYPE_LAST_SLEEP_TIME = "last_sleep_time"
SENSOR_TYPE_DIAPER_COUNT = "diaper_count"
SENSOR_TYPE_POOPY_COUNT = "poopy_count"
SENSOR_TYPE_WET_COUNT = "wet_count"
SENSOR_TYPE_TIME_SINCE_LAST_FEEDING = "time_since_last_feeding"
SENSOR_TYPE_TIME_SINCE_FEEDING = "time_since_last_feeding"
SENSOR_TYPE_IS_SLEEPING = "is_sleeping"

# Units
UNIT_FEEDINGS = "feedings"
UNIT_DIAPERS = "diapers"

# Days covered by the feeding, diaper and pump summaries
SUMMARY_DAYS = 7

# Directory (under the Home Assistant config directory) for baby and activity photos.
# Private: served only through the image entities, which need a login.
PHOTO_DIR_NAME = "baby_tracker"

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

# Alert types
ALERT_TYPE_FEEDING_OVERDUE = "feeding_overdue"
ALERT_TYPE_NO_POOP = "no_poop"
ALERT_TYPE_LOW_WET_DIAPERS = "low_wet_diapers"
ALERT_TYPE_FEVER = "fever"
ALERT_TYPE_LONG_SLEEP = "long_sleep"
ALERT_TYPE_INTAKE_LOW = "intake_low"
ALERT_TYPE_FEED_DUE = "feed_due"
ALERT_TYPE_WAKE_TO_FEED = "wake_to_feed"

# Alert thresholds - (min_days, max_days, value)
FEEDING_THRESHOLDS = [
    (0, 30, 3.5),
    (31, 90, 4.5),
    (91, 180, 5.5),
    (181, 99999, 6.0),
]

NO_POOP_THRESHOLDS = [
    (0, 42, 24),
    (43, 180, 48),
    (181, 99999, 72),
]

LONG_SLEEP_THRESHOLDS = [
    (0, 30, 4.0),
    (31, 90, 6.0),
    (91, 180, 8.0),
    (181, 99999, 12.0),
]

# Scalar thresholds
FEVER_THRESHOLD_F = 100.4
LOW_WET_THRESHOLD = 4
LOW_WET_CHECK_HOUR = 20
LOW_WET_MIN_AGE_DAYS = 3

# Alert attribute keys
ATTR_ALERT_TYPE = "alert_type"
ATTR_THRESHOLD = "threshold"
ATTR_CURRENT_VALUE = "current_value"
ATTR_BABY_AGE_DAYS = "baby_age_days"
ATTR_AGE_BRACKET = "age_bracket"
ATTR_DISMISSED = "dismissed"

# New sensor types
SENSOR_TYPE_DAILY_SUMMARY = "daily_summary"
SENSOR_TYPE_FEEDING_TIMER = "feeding_timer"
SENSOR_TYPE_BEDTIME_ANALYSIS = "bedtime_analysis"

# Night mode constants
NIGHT_START_HOUR = 19  # 7 PM
NIGHT_END_HOUR = 7     # 7 AM

# Event names
EVENT_FEEDING = "baby_tracker_feeding"
EVENT_DIAPER = "baby_tracker_diaper"
EVENT_SLEEP = "baby_tracker_sleep"

# Bedtime analysis
BEDTIME_ANALYSIS_DAYS = 14
