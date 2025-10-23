# Baby Tracker Home Assistant Implementation Guide

## 📚 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Multi-Baby Support](#multi-baby-support)
3. [Adding New Activity Types](#adding-new-activity-types)
4. [Database Layer Patterns](#database-layer-patterns)
5. [Service Layer Patterns](#service-layer-patterns)
6. [Sensor Layer Patterns](#sensor-layer-patterns)
7. [Analytics & Predictions](#analytics--predictions)
8. [Feature Implementation Checklist](#feature-implementation-checklist)
9. [Testing & Validation](#testing--validation)
10. [Contributing Guidelines](#contributing-guidelines)

---

## Architecture Overview

### Component Structure

```
baby_tracker/
├── __init__.py           # Coordinator and integration setup
├── core.py               # BabyTracker wrapper (business logic)
├── database.py           # Database queries and data access
├── models.py             # Data models (Baby, Activity, etc.)
├── api.py                # API sync with Baby Tracker servers
├── sensor.py             # Home Assistant sensors
├── services.py           # Home Assistant services
├── services.yaml         # Service definitions
├── const.py              # Constants
├── config_flow.py        # Configuration UI
└── transaction.py        # Transaction handling
```

### Data Flow

```
User Action → Service Call → Core Method → Database Method → SQLite
                                                                ↓
                                                          Data Returns
                                                                ↓
Home Assistant ← Sensor Update ← Coordinator ← Core Method ← Database
```

### Current Features Status

✅ **Implemented:**

- Diaper tracking
- Nursing tracking
- Formula feeding
- Pumped milk
- Temperature
- Bath time
- Sleep tracking (with in-progress detection)

🚧 **In Progress:**

- Multi-baby support (database layer complete)

📋 **Planned:**

- Pump sessions
- Medicine improvements
- Growth tracking
- Milestones
- Doctor visits
- Vaccines
- Other activities
- Sick days
- Journal entries
- Joy moments
- Health questions
- Allergens
- Analytics & predictions

---

## Multi-Baby Support

### Overview

The Baby Tracker app natively supports multiple babies. Our integration should:

1. Auto-discover all babies in the database
2. Create baby-specific sensors (e.g., `sensor.everly_last_diaper`, `sensor.sibling_last_diaper`)
3. Allow services to target specific babies via `baby_name` parameter
4. Default to first baby if no baby specified

### Database Layer (✅ Complete)

**Methods Added:**

```python
def get_all_babies(self) -> List[Baby]:
    """Get all babies from database"""

def get_baby_by_name(self, name: str) -> Optional[Baby]:
    """Get specific baby by name"""
```

**Pattern for Activity Methods:**
All activity methods should accept optional `baby_id` parameter:

```python
def get_last_diaper_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
    if baby_id is None:
        # Get first baby
        cursor.execute("SELECT ID FROM Baby LIMIT 1")
        baby_id = cursor.fetchone()[0]

    # Query with baby_id
    cursor.execute("... WHERE BabyID = ?", (baby_id,))
```

### Coordinator Layer (TODO)

**Current:**

```python
return {
    "baby_info": baby_info,  # Single baby
    "last_feeding": last_feeding,
    ...
}
```

**Target:**

```python
babies = self.baby_tracker.get_all_babies()

data = {}
for baby in babies:
    data[baby.name] = {
        "baby_info": baby,
        "last_feeding": self.baby_tracker.get_last_feeding(baby.object_id),
        "last_diaper": self.baby_tracker.get_last_diaper(baby.object_id),
        ...
    }

return data
```

### Sensor Layer (TODO)

**Current Pattern:**

```python
class BabyTrackerLastDiaperSensor(BabyTrackerSensor):
    def __init__(self, coordinator, baby_name):
        self._attr_name = f"{baby_name} Last Diaper"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_last_diaper"
```

**Target Pattern:**

```python
class BabyTrackerLastDiaperSensor(BabyTrackerSensor):
    def __init__(self, coordinator, baby_name, baby_id):
        self._baby_id = baby_id
        self._attr_name = f"{baby_name} Last Diaper"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_{baby_name.lower()}_last_diaper"

    def _handle_coordinator_update(self):
        baby_data = self.coordinator.data.get(self._baby_name, {})
        last_diaper = baby_data.get("last_diaper")
        ...
```

**Sensor Setup:**

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []
    # Loop through all babies and create sensors for each
    for baby_name in coordinator.data.keys():
        baby_info = coordinator.data[baby_name]["baby_info"]
        sensors.extend([
            BabyTrackerLastDiaperSensor(coordinator, baby_name, baby_info.object_id),
            BabyTrackerLastSleepSensor(coordinator, baby_name, baby_info.object_id),
            ...
        ])

    async_add_entities(sensors, True)
```

### Service Layer (TODO)

**Add `baby_name` parameter to all services:**

```python
# services.py
DIAPER_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,  # Add this
    vol.Optional("pee", default=True): cv.boolean,
    ...
})

async def add_diaper(call: ServiceCall):
    data = call.data
    coordinator = _get_coordinator(hass)

    # Get baby_id from name
    baby_name = data.get("baby_name")
    baby_id = None
    if baby_name:
        baby = await hass.async_add_executor_job(
            coordinator.baby_tracker.db.get_baby_by_name, baby_name
        )
        baby_id = baby.object_id if baby else None

    # Pass baby_id to method
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.add_diaper,
        baby_id,  # Add this parameter
        ...
    )
```

```yaml
# services.yaml
add_diaper:
  fields:
    baby_name:
      name: Baby Name
      description: Name of the baby (optional, defaults to first baby)
      required: false
      example: "Everly"
      selector:
        text:
    pee: ...
```

---

## Adding New Activity Types

### Step-by-Step Template

Every new activity type follows this pattern:

#### 1. Database Layer (`database.py`)

```python
def get_last_[ACTIVITY]_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
    """
    Get the last [ACTIVITY] by querying the [TABLE] table directly.

    :param baby_id: Optional baby ID
    :return: Dictionary with [ACTIVITY] info or None
    """
    if not os.path.exists(self.db_path):
        raise ValueError("No database loaded")

    conn = sqlite3.connect(self.db_path)
    try:
        cursor = conn.cursor()

        # Get baby ID if not provided
        if baby_id is None:
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_row = cursor.fetchone()
            baby_id = baby_row[0] if baby_row else None
            if baby_id is None:
                return None

        # Query [TABLE] table directly
        cursor.execute("""
            SELECT ID, Time, [FIELD1], [FIELD2], ...
            FROM [TABLE]
            WHERE BabyID = ?
            ORDER BY Time DESC
            LIMIT 1
        """, (baby_id,))

        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "time": self._format_timestamp(row[1]) if row[1] else None,
                "raw_time": row[1],
                "[field1]": row[2],
                "[field2]": row[3],
                ...
            }
        return None
    finally:
        conn.close()

def get_[ACTIVITY]_records(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
    """Get historical [ACTIVITY] records"""
    # Similar pattern to above but return list

def log_[ACTIVITY](self, baby_id: Optional[str] = None, [PARAMS],
                   time: Optional[datetime] = None) -> bool:
    """Log a new [ACTIVITY] record"""
    import uuid

    if not os.path.exists(self.db_path):
        raise ValueError("No database loaded")

    conn = sqlite3.connect(self.db_path)
    try:
        cursor = conn.cursor()

        # Get baby ID if not provided
        if baby_id is None:
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_row = cursor.fetchone()
            baby_id = baby_row[0] if baby_row else None
            if baby_id is None:
                _LOGGER.error("No baby found in database")
                return False

        # Use provided time or current time
        if time is None:
            time = datetime.now(timezone.utc)

        activity_time = time.timestamp()
        timestamp = datetime.now(timezone.utc).timestamp()

        # Insert record
        cursor.execute("""
            INSERT INTO [TABLE] (
                ID, Timestamp, Time, BabyID, [FIELD1], [FIELD2], ...
            ) VALUES (?, ?, ?, ?, ?, ?, ...)
        """, (
            str(uuid.uuid4()),
            timestamp,
            activity_time,
            baby_id,
            [param1],
            [param2],
            ...
        ))

        conn.commit()
        _LOGGER.info(f"Logged [ACTIVITY]: ...")
        return True

    except Exception as e:
        _LOGGER.error(f"Error logging [ACTIVITY]: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
```

#### 2. Core Layer (`core.py`)

```python
def get_last_[ACTIVITY](self, baby_id=None):
    """Get the most recent [ACTIVITY]"""
    if not self.db:
        if os.path.exists(self.db_path):
            self.db = BabyTrackerLocalDatabase(self.db_path)
            self.api.local_db = self.db
        else:
            return None

    return self.db.get_last_[ACTIVITY]_direct(baby_id)

def log_[ACTIVITY](self, baby_id=None, [params], time=None):
    """Log a new [ACTIVITY] record"""
    if not self.db:
        if os.path.exists(self.db_path):
            self.db = BabyTrackerLocalDatabase(self.db_path)
            self.api.local_db = self.db
        else:
            return False

    return self.db.log_[ACTIVITY](baby_id=baby_id, [params], time=time)
```

#### 3. Coordinator (`__init__.py`)

```python
# In _async_update_data():
last_[ACTIVITY] = await self.hass.async_add_executor_job(
    self.baby_tracker.get_last_[ACTIVITY]
)

return {
    ...
    "last_[ACTIVITY]": last_[ACTIVITY],
}
```

#### 4. Constants (`const.py`)

```python
SENSOR_TYPE_LAST_[ACTIVITY] = "last_[ACTIVITY]"
```

#### 5. Sensor (`sensor.py`)

```python
from .const import SENSOR_TYPE_LAST_[ACTIVITY]

# Add to async_setup_entry sensors list:
BabyTrackerLast[Activity]Sensor(coordinator, baby_name),

# Create sensor class:
class BabyTrackerLast[Activity]Sensor(BabyTrackerSensor):
    """Sensor that displays info about the last [ACTIVITY]."""

    def __init__(self, coordinator, baby_name):
        super().__init__(
            coordinator,
            baby_name,
            SENSOR_TYPE_LAST_[ACTIVITY],
            "Last [Activity]",
            None,  # or appropriate unit
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "last_[ACTIVITY]" not in self.coordinator.data:
            return None

        last_activity = self.coordinator.data["last_[ACTIVITY]"]
        if not last_activity:
            return "unknown"

        # Return appropriate state
        return last_activity.get("[main_field]", "Unknown")

    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not self.coordinator.data or "last_[ACTIVITY]" not in self.coordinator.data:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        last_activity = self.coordinator.data["last_[ACTIVITY]"]
        if not last_activity:
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        # Set attributes
        attrs = {
            ATTR_TIME: last_activity.get("time"),
            "[field1]": last_activity.get("[field1]"),
            "[field2]": last_activity.get("[field2]"),
        }

        if last_activity.get("note"):
            attrs["note"] = last_activity.get("note")

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()
```

#### 6. Service (`services.py` + `services.yaml`)

**services.py:**

```python
[ACTIVITY]_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,
    vol.Required("[param1]"): ...,
    vol.Optional("[param2]", default=...): ...,
    vol.Optional("note", default=""): cv.string,
})

@callback
async def log_[ACTIVITY](call: ServiceCall):
    """Log a [ACTIVITY] record."""
    data = call.data
    coordinator = _get_coordinator(hass)

    # Get baby_id from name
    baby_id = None
    if data.get("baby_name"):
        baby = await hass.async_add_executor_job(
            coordinator.baby_tracker.db.get_baby_by_name, data["baby_name"]
        )
        baby_id = baby.object_id if baby else None

    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.log_[ACTIVITY],
        baby_id,
        data.get("[param1]"),
        data.get("[param2]"),
        data.get("note", ""),
        None  # time
    )

    if not result:
        _LOGGER.error("Failed to log [ACTIVITY]")
        return False

    await coordinator.async_refresh()
    return True

# Register service:
hass.services.async_register(
    DOMAIN, "log_[ACTIVITY]", log_[ACTIVITY], schema=[ACTIVITY]_SCHEMA
)
```

**services.yaml:**

```yaml
log_[ACTIVITY]:
  name: Log [Activity]
  description: Log a [ACTIVITY] to Baby Tracker
  fields:
    baby_name:
      name: Baby Name
      description: Name of the baby (optional)
      required: false
      selector:
        text:
    [param1]:
      name: [Param1]
      description: [Description]
      required: true
      selector: [appropriate_selector]
    note:
      name: Note
      description: Optional note
      required: false
      selector:
        text:
```

---

## Database Layer Patterns

### Common Query Patterns

#### Get Last Activity

```sql
SELECT ID, Time, [fields]
FROM [TABLE]
WHERE BabyID = ?
ORDER BY Time DESC
LIMIT 1
```

#### Get Activity History

```sql
SELECT ID, Time, [fields]
FROM [TABLE]
WHERE BabyID = ?
ORDER BY Time DESC
LIMIT ?
```

#### Get Activity in Date Range

```sql
SELECT ID, Time, [fields]
FROM [TABLE]
WHERE BabyID = ?
  AND Time >= ?
  AND Time <= ?
ORDER BY Time DESC
```

#### Join with Description Tables

```sql
SELECT a.*, d.Name as DescName
FROM [TABLE] a
LEFT JOIN [DESC_TABLE] d ON a.DescID = d.ID
WHERE a.BabyID = ?
ORDER BY a.Time DESC
```

### Timestamp Handling

**Unix Timestamp to DateTime:**

```python
def _format_timestamp(self, unix_timestamp):
    """Convert Unix timestamp to formatted datetime string"""
    if unix_timestamp is None:
        return None
    try:
        dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return None
```

**DateTime to Unix Timestamp:**

```python
activity_time = time.timestamp()  # time is datetime object
```

### Baby ID Resolution

**Standard pattern for all methods:**

```python
# Get baby ID if not provided
if baby_id is None:
    cursor.execute("SELECT ID FROM Baby LIMIT 1")
    baby_row = cursor.fetchone()
    baby_id = baby_row[0] if baby_row else None

    if baby_id is None:
        return None  # or [] for list methods
```

---

## Service Layer Patterns

### Service Schema Pattern

```python
[SERVICE]_SCHEMA = vol.Schema({
    vol.Optional("baby_name"): cv.string,  # Always include for multi-baby
    vol.Required("required_field"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("optional_field", default="default"): cv.string,
    vol.Optional("note", default=""): cv.string,
})
```

### Service Handler Pattern

```python
@callback
async def [service_name](call: ServiceCall):
    """[Description]"""
    data = call.data
    coordinator = _get_coordinator(hass)

    # 1. Get baby_id from name
    baby_id = None
    if data.get("baby_name"):
        baby = await hass.async_add_executor_job(
            coordinator.baby_tracker.db.get_baby_by_name,
            data["baby_name"]
        )
        baby_id = baby.object_id if baby else None

    # 2. Call business logic method
    result = await hass.async_add_executor_job(
        coordinator.baby_tracker.[method_name],
        baby_id,
        data.get("param1"),
        data.get("param2"),
        ...
    )

    # 3. Handle result
    if not result or result.get("status") != "success":
        _LOGGER.error(f"Failed to [action]: {result.get('message', '')}")
        return False

    # 4. Refresh coordinator to update sensors
    await coordinator.async_refresh()
    return True
```

---

## Sensor Layer Patterns

### Sensor State Patterns

**Simple Value:**

```python
@property
def state(self):
    return last_activity.get("value", 0)
```

**Status String:**

```python
@property
def state(self):
    status = last_activity.get("status")
    return status if status else "unknown"
```

**Conditional State:**

```python
@property
def state(self):
    if last_activity.get("in_progress"):
        return "active"
    else:
        return f"{last_activity.get('duration')} min"
```

### Attribute Patterns

**Basic Attributes:**

```python
attrs = {
    ATTR_TIME: activity.get("time"),
    "field1": activity.get("field1"),
    "field2": activity.get("field2"),
}
```

**Calculated Attributes:**

```python
duration = activity.get("duration", 0)
if duration:
    hours = int(duration // 60)
    minutes = int(duration % 60)
    attrs["duration_hours"] = hours
    attrs["duration_minutes"] = minutes
    attrs["duration_formatted"] = f"{hours}h {minutes}m"
```

**Conditional Attributes:**

```python
if activity.get("note"):
    attrs["note"] = activity.get("note")

if activity.get("in_progress"):
    attrs["status"] = "active"
    attrs["current_duration"] = calculate_duration(activity["start_time"])
```

---

## Analytics & Predictions

### Framework Design

Create a new file: `analytics.py`

```python
"""Analytics and prediction models for Baby Tracker"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import statistics

_LOGGER = logging.getLogger(__name__)

class BabyAnalytics:
    """Analytics engine for baby activity patterns"""

    def __init__(self, database):
        self.db = database

    def predict_next_feeding(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Predict when the next feeding will be needed based on historical patterns.

        Returns:
            {
                "predicted_time": datetime,
                "confidence": float (0-1),
                "average_interval": minutes,
                "recent_pattern": [intervals]
            }
        """
        # Get last 20 feedings
        feedings = self.db.get_feeding_records(limit=20, baby_id=baby_id)

        if len(feedings) < 3:
            return None  # Not enough data

        # Calculate intervals between feedings
        intervals = []
        for i in range(len(feedings) - 1):
            time1 = feedings[i]["raw_time"]
            time2 = feedings[i+1]["raw_time"]
            interval = (time1 - time2) / 60  # minutes
            intervals.append(interval)

        # Calculate average and standard deviation
        avg_interval = statistics.mean(intervals)
        std_dev = statistics.stdev(intervals) if len(intervals) > 1 else 0

        # Predict next feeding time
        last_feeding_time = feedings[0]["raw_time"]
        predicted_timestamp = last_feeding_time + (avg_interval * 60)
        predicted_time = datetime.fromtimestamp(predicted_timestamp, tz=timezone.utc)

        # Calculate confidence (lower std_dev = higher confidence)
        confidence = max(0, 1 - (std_dev / avg_interval)) if avg_interval > 0 else 0

        return {
            "predicted_time": predicted_time.isoformat(),
            "predicted_timestamp": predicted_timestamp,
            "confidence": round(confidence, 2),
            "average_interval_minutes": round(avg_interval, 1),
            "std_deviation_minutes": round(std_dev, 1),
            "recent_intervals": [round(i, 1) for i in intervals[:5]],
            "pattern_quality": "stable" if std_dev < avg_interval * 0.3 else "variable"
        }

    def analyze_sleep_patterns(self, baby_id: Optional[str] = None, days: int = 7) -> Dict:
        """
        Analyze sleep patterns over recent days.

        Returns insights about sleep quality, duration trends, timing patterns
        """
        # Get sleep records for the period
        sleep_records = self.db.get_sleep_records(limit=100, baby_id=baby_id)

        # Filter to date range
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_timestamp = cutoff_time.timestamp()
        recent_sleeps = [s for s in sleep_records if s["raw_time"] >= cutoff_timestamp]

        if not recent_sleeps:
            return {"error": "No sleep data in period"}

        # Calculate metrics
        durations = [s["duration"] for s in recent_sleeps if s["duration"] > 0]
        avg_duration = statistics.mean(durations) if durations else 0
        total_sleep = sum(durations)
        sleep_count = len(durations)

        # Find longest sleep
        longest = max(durations) if durations else 0

        # Identify sleep times (hour of day)
        sleep_hours = []
        for s in recent_sleeps:
            dt = datetime.fromtimestamp(s["raw_time"], tz=timezone.utc)
            sleep_hours.append(dt.hour)

        # Most common sleep time
        if sleep_hours:
            most_common_hour = statistics.mode(sleep_hours)
        else:
            most_common_hour = None

        return {
            "period_days": days,
            "total_sleeps": sleep_count,
            "average_duration_minutes": round(avg_duration, 1),
            "total_sleep_minutes": total_sleep,
            "total_sleep_hours": round(total_sleep / 60, 1),
            "longest_sleep_minutes": longest,
            "average_sleeps_per_day": round(sleep_count / days, 1),
            "most_common_bedtime_hour": most_common_hour,
            "sleep_quality_score": self._calculate_sleep_quality(durations, days)
        }

    def _calculate_sleep_quality(self, durations: List[float], days: int) -> str:
        """Calculate sleep quality based on duration patterns"""
        if not durations:
            return "unknown"

        avg = statistics.mean(durations)
        total_hours_per_day = sum(durations) / 60 / days

        # Quality heuristics (adjust based on baby age)
        if total_hours_per_day >= 14 and avg >= 90:
            return "excellent"
        elif total_hours_per_day >= 12 and avg >= 60:
            return "good"
        elif total_hours_per_day >= 10:
            return "fair"
        else:
            return "needs_attention"

    def detect_feeding_pattern_changes(self, baby_id: Optional[str] = None) -> Dict:
        """
        Detect significant changes in feeding patterns that might indicate
        growth spurts, illness, or other changes.
        """
        # Compare last 3 days to previous 7 days
        recent = self._get_feeding_stats(baby_id, days=3)
        baseline = self._get_feeding_stats(baby_id, days=7, offset_days=3)

        if not recent or not baseline:
            return {"status": "insufficient_data"}

        # Calculate percentage changes
        freq_change = (recent["frequency"] - baseline["frequency"]) / baseline["frequency"] * 100
        duration_change = (recent["avg_duration"] - baseline["avg_duration"]) / baseline["avg_duration"] * 100

        insights = []

        if abs(freq_change) > 20:
            direction = "increased" if freq_change > 0 else "decreased"
            insights.append(f"Feeding frequency {direction} by {abs(freq_change):.0f}%")

        if abs(duration_change) > 20:
            direction = "increased" if duration_change > 0 else "decreased"
            insights.append(f"Feeding duration {direction} by {abs(duration_change):.0f}%")

        return {
            "status": "analyzed",
            "recent_stats": recent,
            "baseline_stats": baseline,
            "frequency_change_percent": round(freq_change, 1),
            "duration_change_percent": round(duration_change, 1),
            "insights": insights,
            "alert": len(insights) > 0
        }

    def _get_feeding_stats(self, baby_id: Optional[str], days: int, offset_days: int = 0) -> Optional[Dict]:
        """Get feeding statistics for a time period"""
        feedings = self.db.get_feeding_records(limit=200, baby_id=baby_id)

        # Filter to date range
        end_time = datetime.now(timezone.utc) - timedelta(days=offset_days)
        start_time = end_time - timedelta(days=days)

        end_timestamp = end_time.timestamp()
        start_timestamp = start_time.timestamp()

        period_feedings = [
            f for f in feedings
            if start_timestamp <= f["raw_time"] <= end_timestamp
        ]

        if not period_feedings:
            return None

        # Calculate stats
        count = len(period_feedings)
        frequency = count / days  # feedings per day

        # Average duration for nursing
        durations = [
            f.get("total_duration", 0)
            for f in period_feedings
            if f.get("type") == "Nursing" and f.get("total_duration")
        ]
        avg_duration = statistics.mean(durations) if durations else 0

        return {
            "count": count,
            "frequency": frequency,
            "avg_duration": avg_duration
        }

    def growth_velocity(self, baby_id: Optional[str] = None, metric: str = "weight") -> Optional[Dict]:
        """
        Calculate growth velocity (rate of change) for weight/height/head.

        Args:
            metric: "weight", "height", or "head"
        """
        growth_records = self.db.get_growth_records(limit=20, baby_id=baby_id)

        if len(growth_records) < 2:
            return None

        # Extract measurements and times
        measurements = []
        for record in growth_records:
            value = record.get(metric)
            if value and value > 0:
                measurements.append({
                    "time": record["raw_time"],
                    "value": value
                })

        if len(measurements) < 2:
            return None

        # Sort by time (oldest first)
        measurements.sort(key=lambda x: x["time"])

        # Calculate velocity (change per day)
        first = measurements[0]
        last = measurements[-1]

        value_change = last["value"] - first["value"]
        time_change_days = (last["time"] - first["time"]) / 86400  # seconds to days

        velocity = value_change / time_change_days if time_change_days > 0 else 0

        return {
            "metric": metric,
            "current_value": last["value"],
            "previous_value": first["value"],
            "change": value_change,
            "days_tracked": round(time_change_days, 1),
            "velocity_per_day": round(velocity, 3),
            "velocity_per_week": round(velocity * 7, 2),
            "velocity_per_month": round(velocity * 30, 2),
            "trend": "increasing" if velocity > 0 else "decreasing" if velocity < 0 else "stable"
        }
```

### Prediction Sensors

Create sensors that display predictions:

```python
class BabyTrackerNextFeedingPredictionSensor(BabyTrackerSensor):
    """Sensor that predicts next feeding time"""

    @property
    def state(self):
        prediction = self.coordinator.data.get("feeding_prediction")
        if not prediction:
            return "unknown"

        # Return time until next feeding
        predicted_timestamp = prediction["predicted_timestamp"]
        now = datetime.now(timezone.utc).timestamp()
        minutes_until = (predicted_timestamp - now) / 60

        if minutes_until < 0:
            return "overdue"
        elif minutes_until < 60:
            return f"{int(minutes_until)} min"
        else:
            hours = int(minutes_until / 60)
            mins = int(minutes_until % 60)
            return f"{hours}h {mins}m"

    def _handle_coordinator_update(self):
        prediction = self.coordinator.data.get("feeding_prediction")
        if not prediction:
            self._attr_extra_state_attributes = {}
            return

        attrs = {
            "predicted_time": prediction["predicted_time"],
            "confidence": prediction["confidence"],
            "average_interval": prediction["average_interval_minutes"],
            "pattern_quality": prediction["pattern_quality"],
            "recent_intervals": prediction["recent_intervals"]
        }

        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()
```

---

## Feature Implementation Checklist

Use this checklist for each new feature:

### Phase 1: Database Layer

- [ ] Add `get_last_[ACTIVITY]_direct(baby_id)` method
- [ ] Add `get_[ACTIVITY]_records(limit, baby_id)` method
- [ ] Add `log_[ACTIVITY](baby_id, params, time)` method
- [ ] Test queries with `sqlite3` directly
- [ ] Verify multi-baby support (test with multiple baby IDs)

### Phase 2: Core Layer

- [ ] Add wrapper methods in `core.py`
- [ ] Test methods work end-to-end

### Phase 3: Coordinator

- [ ] Add data fetch in `_async_update_data()`
- [ ] Test data appears in coordinator

### Phase 4: Constants

- [ ] Add sensor type constant to `const.py`

### Phase 5: Sensor

- [ ] Import constants in `sensor.py`
- [ ] Create sensor class
- [ ] Add sensor to setup list
- [ ] Test sensor shows data
- [ ] Test sensor attributes

### Phase 6: Service

- [ ] Add schema to `services.py`
- [ ] Add service handler
- [ ] Register service
- [ ] Add to unregister list
- [ ] Add service definition to `services.yaml`
- [ ] Test service call works
- [ ] Test coordinator refresh after service

### Phase 7: Documentation

- [ ] Add docstrings
- [ ] Add usage examples
- [ ] Update README

---

## Testing & Validation

### Manual Testing Checklist

**Database Layer:**

```python
# Test in Python console
from database import BabyTrackerLocalDatabase
db = BabyTrackerLocalDatabase("babytracker.db")

# Test get methods
result = db.get_last_[ACTIVITY]_direct()
print(result)

# Test log methods
success = db.log_[ACTIVITY]([params])
print(success)

# Verify in database
# sqlite3 babytracker.db "SELECT * FROM [TABLE] ORDER BY Time DESC LIMIT 1"
```

**Service Testing:**

1. Go to Developer Tools > Services in Home Assistant
2. Select `baby_tracker.log_[ACTIVITY]`
3. Enter test data
4. Call service
5. Check sensor updates
6. Verify in database

**Sensor Testing:**

1. Check sensor entity appears
2. Verify state is correct
3. Check attributes contain expected data
4. Trigger update and verify refresh

### Multi-Baby Testing

```python
# Add second baby to database for testing
db = BabyTrackerLocalDatabase("babytracker.db")
conn = sqlite3.connect("babytracker.db")
cursor = conn.cursor()

cursor.execute("""
    INSERT INTO Baby (ID, Name, DOB, Gender)
    VALUES (?, ?, ?, ?)
""", ("test-baby-2-id", "TestBaby", 1704067200.0, 1))

conn.commit()
conn.close()

# Test multi-baby methods
babies = db.get_all_babies()
print(f"Found {len(babies)} babies")

baby2 = db.get_baby_by_name("TestBaby")
print(f"TestBaby ID: {baby2.object_id}")

# Test activity with specific baby
result = db.get_last_diaper_direct(baby2.object_id)
print(result)
```

---

## Contributing Guidelines

### Code Style

- Follow PEP 8
- Use type hints where possible
- Add docstrings to all public methods
- Use meaningful variable names
- Keep methods focused (single responsibility)

### Commit Messages

```
feat: Add pump session tracking
fix: Correct baby_id parameter handling in services
docs: Update IMPLEMENTATION_GUIDE with growth tracking
refactor: Simplify sleep detection logic
test: Add multi-baby test cases
```

### Pull Request Template

```markdown
## Description

[Describe what this PR adds/fixes]

## Type of Change

- [ ] New feature
- [ ] Bug fix
- [ ] Documentation
- [ ] Refactoring

## Testing

- [ ] Tested manually in Home Assistant
- [ ] Tested with database queries
- [ ] Tested multi-baby support
- [ ] Added test cases

## Checklist

- [ ] Code follows style guidelines
- [ ] Added/updated docstrings
- [ ] Updated IMPLEMENTATION_GUIDE if needed
- [ ] Updated README if needed
- [ ] Services.yaml updated if applicable

## Screenshots (if applicable)

[Add screenshots of new sensors/services]
```

---

## Quick Reference: Activity Types

| Activity       | Table            | Key Fields                                                       | Notes                                  |
| -------------- | ---------------- | ---------------------------------------------------------------- | -------------------------------------- |
| Diaper         | `Diaper`         | Status, PeeColor, PooColor, Amount, Texture                      | Status: 0=Wet, 1=Poopy, 2=Mixed, 3=Dry |
| Nursing        | `Nursing`        | LeftDuration, RightDuration, BothDuration, FinishSide            | Durations in minutes                   |
| Formula        | `Formula`        | Amount, IsEnglishScale                                           | Amount in ml or oz                     |
| Pumped         | `Pumped`         | Amount, IsEnglishScale                                           | Amount in ml or oz                     |
| Sleep          | `Sleep`          | Duration, LocationID, DescID                                     | Duration=0 means in progress           |
| Bath           | `Bath`           | DescID                                                           | Links to BathDesc for type             |
| Pump           | `Pump`           | LeftAmount, RightAmount, LeftDuration, RightDuration, Amount     | Breast pump session                    |
| Temperature    | `Temperature`    | Temp, TempUnit                                                   | Unit: 0=F, 1=C                         |
| Medicine       | `Medicine`       | MedID, Amount                                                    | Links to MedicineSelection             |
| Growth         | `Growth`         | Weight, Length, Head, IsEnglishWeightScale, IsEnglishLengthScale | Track measurements                     |
| Milestone      | `Milestone`      | MilestoneID                                                      | Links to MilestoneSelection            |
| DoctorVisit    | `DoctorVisit`    | DoctorID, DoctorText                                             | Links to DoctorSelection               |
| Vaccine        | `Vaccine`        | VaccineID                                                        | Links to VaccineSelection              |
| OtherActivity  | `OtherActivity`  | DescID, LocationID, Duration                                     | Custom activities                      |
| Sick           | `Sick`           | SickID, Symptom, Severity                                        | Links to SickDesc                      |
| Journal        | `Journal`        | Note, Title                                                      | Free-form entries                      |
| Joy            | `Joy`            | Note                                                             | Happy moments                          |
| HealthQuestion | `HealthQuestion` | Question, Answer                                                 | Track concerns                         |
| Allergen       | `Allergen`       | AllergenID, Reaction                                             | Links to AllergenSourceSelection       |
| OtherFeed      | `OtherFeed`      | FeedID, Amount                                                   | Supplements, solids                    |

---

## Next Steps

### Immediate Priorities

1. **Complete Multi-Baby Support** (Phase 1)

   - Update coordinator for multi-baby data structure
   - Update all sensors for baby-specific entities
   - Add baby_name parameter to all services

2. **High-Value Features** (Phase 2)

   - Pump sessions (62 existing records!)
   - Medicine tracking improvements
   - Growth tracking
   - Analytics foundation

3. **Remaining Activities** (Phase 3)

   - Milestones, Doctor Visits, Vaccines
   - Other Activities, Sick Days
   - Journal, Joy, Health Questions, Allergens

4. **Advanced Features** (Phase 4)
   - Complete analytics engine
   - Prediction models
   - Growth charts
   - Pattern analysis

### Getting Started

**To add your next feature:**

1. Pick a feature from the list
2. Follow the "Adding New Activity Types" template
3. Work through the checklist
4. Test thoroughly
5. Commit with clear message
6. Move to next feature!

**Recommended order:**

1. Pump sessions (you have data!)
2. Medicine (you have data!)
3. Growth (essential for development tracking)
4. Other activities (you have 7 records)
5. Everything else based on your needs

---

## Support & Questions

- Check this guide first
- Look at existing implementations (Bath, Sleep are good examples)
- Check database with `sqlite3 babytracker.db`
- Test incrementally at each layer

Happy coding! 🍼👶
