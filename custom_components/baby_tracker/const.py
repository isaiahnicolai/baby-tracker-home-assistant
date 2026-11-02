"""Constants for the Baby Tracker integration."""

DOMAIN = "baby_tracker"
CONFIG_ENTRY_VERSION = 2  # the config flow's VERSION; async_migrate_entry brings older entries up to it
VERSION = "1.0.1"  # keep in sync with manifest.json and client/__init__.py

# Configuration
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_UNIT_SYSTEM = "unit_system"
CONF_DEVICE_UUID = "device_uuid"  # This integration's own device identity on the sync server
DEFAULT_SCAN_INTERVAL = 15  # minutes
DEFAULT_TITLE = "Baby Tracker"  # until the first sync names the babies
FIRST_SYNC_RETRY_SECONDS = 60  # wait before trying a failed first sync again
DEFAULT_UNIT_SYSTEM = "imperial"  # "imperial" (oz, lbs, F) or "metric" (ml, kg, C)

# Unit system options
UNIT_SYSTEM_IMPERIAL = "imperial"
UNIT_SYSTEM_METRIC = "metric"

# Alert settings in the options flow (see binary_sensor.py for how each is used)
CONF_FEEDING_OVERDUE_HOURS = "feeding_overdue_hours"  # 0 = by the baby's age (FEEDING_THRESHOLDS)
CONF_LOW_WET_MINIMUM = "low_wet_minimum"
CONF_NIGHT_START_HOUR = "night_start_hour"
CONF_NIGHT_END_HOUR = "night_end_hour"
CONF_FEVER_THRESHOLD = "fever_threshold"  # in the entry's temperature unit (F or C)
DEFAULT_FEEDING_OVERDUE_HOURS = 0

# Sleep recorded from another entity (a Snoo, an Owlet, a bed sensor...). The option is
# {baby_id: {sleep_source_entity, sleep_source_asleep_states, sleep_gap_minutes, sleep_min_minutes}}
CONF_SLEEP_SOURCES = "sleep_sources"
CONF_SLEEP_SOURCE_ENTITY = "sleep_source_entity"
CONF_SLEEP_SOURCE_ASLEEP_STATES = "sleep_source_asleep_states"
CONF_SLEEP_GAP_MINUTES = "sleep_gap_minutes"  # a wake shorter than this does not end the sleep
CONF_SLEEP_MIN_MINUTES = "sleep_min_minutes"  # a sleep shorter than this is never logged
DEFAULT_SLEEP_ASLEEP_STATES = ["on", "asleep", "sleeping"]
DEFAULT_SLEEP_GAP_MINUTES = 10
DEFAULT_SLEEP_MIN_MINUTES = 5
SLEEP_SOURCE_STORE_VERSION = 1

# Quiet mode: a baby who is no longer logged for an activity stops getting alerts and predictions
# for it. The option is {baby_id: "auto" | [group, ...]}; "auto" works it out from the records.
CONF_TRACKING = "tracking"
CONF_TRACKED_ACTIVITIES = "tracked_activities"  # the options flow field, per baby
TRACKING_AUTO = "auto"
TRACKING_WINDOW_DAYS = 14  # an activity logged within this long (or a baby this young) counts as tracked
TRACKING_GROUPS = ("feeds", "diapers", "sleep", "pumping", "medicine", "growth", "temperature")
REASON_NOT_TRACKED = "not_tracked"

# Sensor types
SENSOR_TYPE_LAST_FEEDING = "last_feeding"
SENSOR_TYPE_LAST_DIAPER = "last_diaper"
SENSOR_TYPE_LAST_SLEEP = "last_sleep"
SENSOR_TYPE_LAST_NURSING = "last_nursing"
SENSOR_TYPE_LAST_BATH = "last_bath"
SENSOR_TYPE_LAST_PUMP = "last_pump"
SENSOR_TYPE_PUMP_SUMMARY = "pump_summary"
SENSOR_TYPE_LAST_MEDICINE = "last_medicine"
SENSOR_TYPE_LAST_ACTIVITY = "last_activity"
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
SENSOR_TYPE_LAST_WET_DIAPER_TIME = "last_wet_diaper_time"
SENSOR_TYPE_LAST_DIRTY_DIAPER_TIME = "last_dirty_diaper_time"
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
ALERT_TYPE_SLEEP_DUE = "sleep_due"
ALERT_TYPE_WAKE_OVERDUE = "wake_overdue"

# Nap Running Long turns on this long after the expected wake time
WAKE_OVERDUE_GRACE_MINUTES = 30

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
FEVER_THRESHOLD_C = 38.0
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

# Per-baby controls (number/select entities) and the buttons that use them
DEFAULT_BOTTLE_OZ = 4
DEFAULT_BOTTLE_ML = 120
DEFAULT_MEDICINE_AMOUNT = 1.0
DEFAULT_TUMMY_TIME_MINUTES = 15
BOTTLE_TYPE_FORMULA = "formula"
BOTTLE_TYPE_PUMPED = "pumped"

# Entities of the account as a whole (not of one baby), as the part of their unique ID after
# "baby_tracker_<email>_": the household sensors are keyed "system_<type>" (see sensor.py's
# HOUSEHOLD_SENSORS), the two account buttons by their name. Migrating entities from baby
# names to baby IDs must leave these alone, whatever a baby is called.
ACCOUNT_ENTITY_KEYS = frozenset({
    "sync_now",
    "force_resync",
    *(f"system_{key}" for key in (
        "next_feed_due", "next_feed_baby", "last_fed_baby", "babies_asleep", "feeds_today",
        "pending_uploads", "pumped_milk_inventory",
    )),
})

# A second press of the same button within this many seconds is ignored
BUTTON_DEBOUNCE_SECONDS = 3

# Running nursing timers are saved (helpers.storage) so they survive a restart or reload;
# one started longer ago than this was forgotten, and is dropped when loaded
NURSING_STORE_VERSION = 1
NURSING_TIMER_MAX_AGE_HOURS = 24

# A temperature reading older than this no longer counts towards the fever alert
FEVER_WINDOW_HOURS = 24

# Repairs (see strings.json "issues")
ISSUE_UPLOADS_PENDING = "uploads_pending"
ISSUE_ACCOUNT_RESET = "account_reset"
ISSUE_CUSTOM_SENTENCES = "custom_sentences"  # the Assist sentence file is not installed or is out of date
UPLOADS_PENDING_REFRESHES = 3  # raise the issue once records stay unsent for more refreshes than this

# Event names
EVENT_FEEDING = "baby_tracker_feeding"
EVENT_DIAPER = "baby_tracker_diaper"
EVENT_SLEEP = "baby_tracker_sleep"
EVENT_UNDO = "baby_tracker_undo"

# Records the delete_record service takes (the client's record type names), and how far back Undo Last Entry looks
DELETABLE_RECORD_TYPES = [
    "Diaper", "Nursing", "Formula", "Pumped", "OtherFeed", "Sleep", "Temperature", "Medication", "Bath",
    "Growth", "Milestone", "Vaccine", "OtherActivity", "Joy", "Journal", "DoctorVisit",
]
# Records the attach_photo service takes: the deletable ones that are synced (doctor visits are kept here only)
ATTACHABLE_RECORD_TYPES = [record_type for record_type in DELETABLE_RECORD_TYPES if record_type != "DoctorVisit"]
UNDO_WINDOW_HOURS = 24
RECENT_RECORDS_LIMIT = 10  # how many records the Recent Entries sensor lists
NOTHING_TO_UNDO = "Nothing to undo"  # what the client's undo_last reports when there is no record in the window

# What a baby's Activity event entity can report
ACTIVITY_EVENT_TYPES = ["feeding", "diaper", "sleep_start", "sleep_end", "bath", "medicine", "photo", "undo"]
SIGNAL_ACTIVITY = "baby_tracker_activity"  # dispatcher signal, suffixed with the config entry ID


def activity_signal(entry_id):
    """The dispatcher signal the coordinator sends when a baby has a new activity."""
    return f"{SIGNAL_ACTIVITY}_{entry_id}"


SIGNAL_CONTROL = "baby_tracker_control"  # sent when the coordinator changes a baby's control itself


def control_signal(entry_id):
    """The dispatcher signal for a control (a number or select value) the coordinator set itself."""
    return f"{SIGNAL_CONTROL}_{entry_id}"


# Entities worked out from the clock re-evaluate this often between refreshes
CLOCK_TICK_SECONDS = 60

# How far back the calendar's "current event" looks for the most recent thing that happened
CALENDAR_LOOKBACK_DAYS = 3

# Bedtime analysis
BEDTIME_ANALYSIS_DAYS = 14
