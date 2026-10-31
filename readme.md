# Baby Tracker for Home Assistant

This custom component integrates the Baby Tracker app data with Home Assistant, allowing you to monitor and update your baby's activities through Home Assistant.

## Features

- **Multi-Baby Support**: Track multiple babies with separate sensors and data for each child
- **Automatic Syncing**: Synchronizes with the Baby Tracker servers to fetch the latest data
- **Comprehensive Sensors**: 20+ sensors per baby tracking feeding, diapers, sleep, growth, medicine, and more
- **Service Calls**: Add new records through Home Assistant service calls
- **Google Home Integration**: Log activities using voice commands through Google Home routines
- **Complete Activity Tracking**: Diapers, feeding (nursing/formula/pumped), sleep, temperature, bath, medicine, growth measurements, milestones, doctor visits, and vaccines

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add the URL: `https://github.com/isaiahnicolai/baby-tracker-home-assistant`
6. Select "Integration" as the category
7. Click "Add"
8. Find and install "Baby Tracker" in HACS

### Manual Installation

1. Download the latest release from this repository
2. Copy the `custom_components/baby_tracker` folder into your `/config/custom_components/` directory (so you end up with `/config/custom_components/baby_tracker/manifest.json`)
3. Restart Home Assistant

Requires Home Assistant 2024.12 or newer.

### Two or more babies

Each baby gets its own device with its own sensors and buttons (for example "Add Wet Diaper", "Add Dirty Diaper" and "Add Mixed Diaper"). When calling a service yourself, choose the baby with the **Baby** device picker or `baby_name`; one of them is required when the account has more than one baby. Pump sessions belong to the account rather than a baby.

### Using it from Python or the command line

The sync client in `custom_components/baby_tracker/client/` has no Home Assistant dependency. Install it from a checkout of this repo:

```bash
pip install -e .
```

That makes it importable as `babytracker_client` and adds a `babytracker` command:

```python
from babytracker_client import BabyTracker

tracker = BabyTracker(db_path="babytracker.db", time_zone="America/Chicago")
tracker.authenticate("you@example.com", "password", device_uuid="<a UUID you keep for this script>")
tracker.sync()
for baby in tracker.get_all_babies():
    print(baby.name, tracker.get_last_diaper(baby.object_id))
```

```bash
export BABYTRACKER_EMAIL=you@example.com   # the password is asked for, or read from BABYTRACKER_PASSWORD
babytracker babies
babytracker last diaper --baby Everly
babytracker add-diaper wet --baby Everly
babytracker devices
babytracker raw <device-uuid> --since 100   # decoded records exactly as the server sends them
```

Each client registers as its own device in the app. The CLI keeps its device ID and local database in `~/.babytracker`, separate from Home Assistant's.

### Development

The repo follows Home Assistant's [integration blueprint](https://github.com/ludeeus/integration_blueprint) setup:

1. Open the repo in VS Code and choose **Reopen in Container** (needs Docker). The dev container installs Home Assistant, the test harness and the client package (`scripts/setup`).
2. `scripts/develop` starts Home Assistant on http://localhost:8123 with this integration loaded from the repo and debug logging on. Its data lives in `config/`, which is git-ignored apart from `configuration.yaml`.
3. `scripts/test` runs the test suite; `scripts/lint` formats and lints with ruff.

Without VS Code, the same Home Assistant runs from the pinned Docker image, preconfigured:

```bash
cp .env.example .env              # fill in your Baby Tracker login (.env is git-ignored)
docker compose up -d
python scripts/bootstrap          # finishes onboarding (user dev / dev) and adds Baby Tracker
```

Open http://localhost:8123. The integration is mounted from the repo, so `docker compose restart` picks up code changes. `scripts/bootstrap` also works against `scripts/develop`. It joins your account as a new device, like any other Home Assistant install.

Tests:

- `tests/` covers the sync client against the app's real database schema (`tests/fixtures/app_schema.sql`, no data) with the sync server faked. These need only pytest: `pip install -e . pytest tzdata && pytest tests --ignore=tests/ha` works anywhere, including Windows.
- `tests/ha` starts an in-memory Home Assistant with `pytest-homeassistant-custom-component`. It only runs on Linux/macOS (the dev container or CI), and each harness version matches one Home Assistant release: bump `requirements_test.txt` and `requirements.txt` together.

GitHub Actions runs both, plus hassfest and HACS validation.

## Configuration

### Through the UI

1. Go to Configuration > Integrations
2. Click on the "+ Add Integration" button
3. Search for "Baby Tracker"
4. Enter your Baby Tracker email and password
5. The integration will automatically sync and create sensors for each baby

### Through YAML (legacy method)

```yaml
# Example configuration.yaml entry
baby_tracker:
  email: your-email@example.com
  password: your-password
  scan_interval: 15 # Optional: minutes between updates (default: 15)
```

## Multi-Baby Support

The integration automatically creates sensors for **each baby** in your Baby Tracker account. Each baby gets their own set of sensors with unique entity IDs:

- **Entity ID format**: `sensor.{baby_name}_{sensor_type}`
- **Examples**:
  - `sensor.baby_name_last_diaper`
  - `sensor.baby_name_weight`
  - `sensor.baby_name_last_feeding`

All services accept an optional `baby_name` parameter. If not specified, the service will use the first/default baby.

## Available Sensors

After setting up the integration, the following sensors will be created **for each baby**:

### Activity Sensors

- **Last Feeding** - Time and type of last feeding (nursing, formula, or pumped)
- **Last Diaper** - Time and status of last diaper change
- **Last Sleep** - Time and duration of last sleep session
- **Last Nursing** - Details of last nursing session (left/right duration)
- **Last Bath** - Time of last bath
- **Last Temperature** - Most recent temperature reading
- **Currently Sleeping** - Binary sensor indicating if baby is currently asleep

### Summary Sensors (Last 7 Days)

- **Feeding Count** - Total number of feedings
- **Nursing Minutes** - Total nursing time
- **Bottle Oz** - Total bottle feeding in oz
- **Bottle ML** - Total bottle feeding in ml
- **Diaper Count** - Total diaper changes
- **Poopy Count** - Number of dirty diapers
- **Wet Count** - Number of wet diapers

### Health & Growth Sensors

- **Last Medicine** - Last medication administered
- **Last Pump** - Last pumping session details
- **Pump Summary** - 7-day pumping totals
- **Weight** - Most recent weight measurement
- **Length** - Most recent length/height measurement
- **Head Circumference** - Most recent head circumference

### Milestone & Medical Sensors

- **Last Milestone** - Most recent developmental milestone achieved
- **Last Doctor Visit** - Most recent doctor appointment or visit
- **Last Vaccine** - Most recent vaccine administered

## Service Calls

All services support multi-baby tracking with an optional `baby_name` parameter.

### Basic Activities

#### Add Diaper Change

```yaml
service: baby_tracker.add_diaper
data:
  baby_name: "Your Baby Name" # Optional - leave empty for first baby
  pee: true
  poo: false
  pee_color: 0 # Optional (0-5)
  poo_color: 0 # Optional (0-5)
  texture: 0 # Optional (0-5)
  amount: 2 # Optional (0-5)
  note: "Optional note"
```

#### Add Nursing Session

```yaml
service: baby_tracker.add_nursing
data:
  baby_name: "Your Baby Name" # Optional
  left_duration: 15 # Minutes
  right_duration: 10 # Minutes
  both_duration: 0 # Minutes
  finish_side: "Left" # "Left", "Right", or "Both"
  note: "Optional note"
```

#### Add Formula Feeding

```yaml
service: baby_tracker.add_formula
data:
  baby_name: "Your Baby Name" # Optional
  amount: 120 # Amount in ml (or oz if is_english_measure is true)
  is_english_measure: false # Optional (default: false)
  note: "Optional note"
```

#### Add Pumped Milk

```yaml
service: baby_tracker.add_pumped
data:
  baby_name: "Your Baby Name" # Optional
  amount: 90 # Amount in ml (or oz if is_english_measure is true)
  is_english_measure: false # Optional (default: false)
  note: "Optional note"
```

#### Add Temperature

```yaml
service: baby_tracker.add_temperature
data:
  baby_name: "Your Baby Name" # Optional
  temperature: 98.6
  is_fahrenheit: true # Optional (default: true)
  note: "Optional note"
```

### Additional Activities

#### Log Bath

```yaml
service: baby_tracker.log_bath
data:
  baby_name: "Your Baby Name" # Optional
  bath_type: "Bubble Bath" # Optional: "Bubble Bath", "Sponge Bath", "Shower", "Washed Hair"
  note: "Optional note"
```

#### Log Pump Session

```yaml
service: baby_tracker.log_pump
data:
  baby_name: "Your Baby Name" # Optional
  left_duration: 15 # Minutes
  right_duration: 15 # Minutes
  left_amount: 3.5 # ml or oz
  right_amount: 4.0 # ml or oz
  is_english_scale: true # true for oz, false for ml
  note: "Optional note"
```

#### Log Medicine

```yaml
service: baby_tracker.log_medicine
data:
  baby_name: "Your Baby Name" # Optional
  medicine_name: "Vitamin D" # Must match a medicine in your Baby Tracker app
  amount: 1.0
  note: "Optional note"
```

#### Log Growth Measurement

```yaml
service: baby_tracker.log_growth
data:
  baby_name: "Your Baby Name" # Optional
  weight: 15.5 # lbs or kg
  length: 24.0 # inches or cm
  head: 16.5 # inches or cm
  is_english_weight_scale: true # true for lbs, false for kg
  is_english_length_scale: true # true for inches, false for cm
  note: "Doctor visit measurements"
```

#### Log Milestone

```yaml
service: baby_tracker.log_milestone
data:
  baby_name: "Your Baby Name" # Optional
  milestone_name: "First smile" # Must match a milestone in Baby Tracker
  note: "So adorable!"
```

**Available Milestones**: First smile, Raise head, Claps Hand, Slept through the night, First laugh, Babbles, Holds head steady, Rolls over, Sits without support, Crawls, Stands, First steps, First word, and more.

#### Log Doctor Visit

```yaml
service: baby_tracker.log_doctor_visit
data:
  baby_name: "Your Baby Name" # Optional
  is_appointment: true # true for scheduled appointment, false for sick visit
  visit_type: 0 # 0=General checkup, customize as needed
  note: "2-month checkup"
  doctor_note: "Everything looks great!"
  symptom: "" # Optional symptoms if sick visit
```

#### Log Vaccine

```yaml
service: baby_tracker.log_vaccine
data:
  baby_name: "Your Baby Name" # Optional
  vaccine_name: "DTaP" # Must match a vaccine in Baby Tracker
  note: "2-month vaccines"
```

**Available Vaccines**: HepB, RV (Rotavirus), DTaP, Hib, PCV (Pneumococcal), IPV (Polio), Influenza, MMR, Varicella, Hep A, and more.

### Utility Services

#### List All Babies

```yaml
service: baby_tracker.list_babies
```

Returns a list of all babies with their names, IDs, dates of birth, and gender.

#### Manually Sync

```yaml
service: baby_tracker.sync
```

Manually triggers a sync with Baby Tracker servers.

## Google Home Integration

You can use Google Home voice commands to log baby activities by creating Home Assistant scenes and exposing them to Google Assistant.

### Setup Instructions

1. **Enable Google Assistant integration** in Home Assistant
2. **Create scenes** for common activities (see examples below)
3. **Expose scenes to Google** in Configuration > Google Assistant
4. **Create Google Home routines** that trigger these scenes
5. **Use natural voice commands** to log activities

### Scene Examples

Create these scenes in your `scenes.yaml` or through the UI:

#### Diaper Scenes

```yaml
# Wet Diaper
- id: baby_wet_diaper
  name: "Wet Diaper"
  entities:
    script.log_wet_diaper:
      state: "on"

# Dirty Diaper
- id: baby_dirty_diaper
  name: "Dirty Diaper"
  entities:
    script.log_dirty_diaper:
      state: "on"

# Mixed Diaper
- id: baby_mixed_diaper
  name: "Mixed Diaper"
  entities:
    script.log_mixed_diaper:
      state: "on"
```

#### Bottle Feeding Scenes

**Note**: Google Assistant doesn't parse numbers well (like "6 oz" or "8 oz"), so we use size names instead:

```yaml
# Small Bottle (4 oz)
- id: baby_small_bottle
  name: "Small Bottle"
  entities:
    script.log_small_bottle:
      state: "on"

# Medium Bottle (6 oz)
- id: baby_medium_bottle
  name: "Medium Bottle"
  entities:
    script.log_medium_bottle:
      state: "on"

# Large Bottle (7 oz)
- id: baby_large_bottle
  name: "Large Bottle"
  entities:
    script.log_large_bottle:
      state: "on"

# Extra Large Bottle (8 oz)
- id: baby_extra_large_bottle
  name: "Extra Large Bottle"
  entities:
    script.log_extra_large_bottle:
      state: "on"
```

### Script Examples

Create corresponding scripts in `scripts.yaml`:

```yaml
log_wet_diaper:
  alias: Log Wet Diaper
  sequence:
    - service: baby_tracker.add_diaper
      data:
        pee: true
        poo: false

log_dirty_diaper:
  alias: Log Dirty Diaper
  sequence:
    - service: baby_tracker.add_diaper
      data:
        pee: false
        poo: true

log_mixed_diaper:
  alias: Log Mixed Diaper
  sequence:
    - service: baby_tracker.add_diaper
      data:
        pee: true
        poo: true

log_small_bottle:
  alias: Log Small Bottle
  sequence:
    - service: baby_tracker.add_formula
      data:
        amount: 4
        is_english_measure: true

log_medium_bottle:
  alias: Log Medium Bottle
  sequence:
    - service: baby_tracker.add_formula
      data:
        amount: 6
        is_english_measure: true

log_large_bottle:
  alias: Log Large Bottle
  sequence:
    - service: baby_tracker.add_formula
      data:
        amount: 7
        is_english_measure: true

log_extra_large_bottle:
  alias: Log Extra Large Bottle
  sequence:
    - service: baby_tracker.add_formula
      data:
        amount: 8
        is_english_measure: true
```

### Google Home Routine Setup

In the Google Home app, create routines like:

**Diaper Change Routine:**

- **When**: "Add a dirty diaper" OR "Log a dirty diaper" OR "Record a dirty diaper" OR "Baby had a dirty diaper"
- **Action**: Activate scene "Dirty Diaper"

**Bottle Feeding Routine:**

- **When**: "Add an extra large bottle" OR "Log an extra large bottle" OR "Record an extra large bottle"
- **Action**: Activate scene "Extra Large Bottle"

### Example Voice Commands

Once set up, you can say:

- "Hey Google, add a dirty diaper"
- "Hey Google, log a wet diaper"
- "Hey Google, record a mixed diaper"
- "Hey Google, add a medium bottle"
- "Hey Google, log an extra large bottle"
- "Hey Google, record a small bottle"

## Dashboard Card Examples

Here are ready-to-use Lovelace card configurations you can add to your dashboard. Simply copy and paste into your dashboard YAML or use the visual editor.

### Quick Overview Card

A compact card showing the most important information:

```yaml
type: entities
title: Baby Status
entities:
  - entity: sensor.baby_name_last_feeding
    name: Last Feeding
  - entity: sensor.baby_name_last_diaper
    name: Last Diaper
  - entity: sensor.baby_name_last_sleep
    name: Last Sleep
  - entity: binary_sensor.baby_name_currently_sleeping
    name: Sleeping Now
  - entity: sensor.baby_name_last_temperature
    name: Temperature
```

### Daily Summary Glance Card

Shows today's totals at a glance:

```yaml
type: glance
title: Today's Summary
entities:
  - entity: sensor.baby_name_feeding_count
    name: Feedings
  - entity: sensor.baby_name_diaper_count
    name: Diapers
  - entity: sensor.baby_name_nursing_minutes
    name: Nursing
  - entity: sensor.baby_name_bottle_oz
    name: Bottle (oz)
```

### Growth Tracking Card

Monitor your baby's growth measurements:

```yaml
type: entities
title: Growth Measurements
entities:
  - entity: sensor.baby_name_weight
    name: Weight
  - entity: sensor.baby_name_length
    name: Length
  - entity: sensor.baby_name_head
    name: Head Circumference
  - entity: sensor.baby_name_last_growth
    type: attribute
    attribute: time
    name: Last Measured
```

### Medical History Card

Track medical information:

```yaml
type: entities
title: Medical History
entities:
  - entity: sensor.baby_name_last_doctor_visit
    name: Last Doctor Visit
  - entity: sensor.baby_name_last_vaccine
    name: Last Vaccine
  - entity: sensor.baby_name_last_medicine
    name: Last Medicine
```

### Milestone Tracker Card

Celebrate developmental milestones:

```yaml
type: entities
title: Milestones
entities:
  - entity: sensor.baby_name_last_milestone
    name: Latest Milestone
  - type: attribute
    entity: sensor.baby_name_last_milestone
    attribute: time
    name: Achieved On
  - type: attribute
    entity: sensor.baby_name_last_milestone
    attribute: note
    name: Notes
```

### Quick Action Buttons Card

Add buttons for common tasks (requires custom:button-card or use scripts):

```yaml
type: vertical-stack
cards:
  - type: horizontal-stack
    cards:
      - type: button
        name: Wet Diaper
        tap_action:
          action: call-service
          service: script.log_wet_diaper
        icon: mdi:water

      - type: button
        name: Dirty Diaper
        tap_action:
          action: call-service
          service: script.log_dirty_diaper
        icon: mdi:emoticon-poop

  - type: horizontal-stack
    cards:
      - type: button
        name: Small Bottle
        tap_action:
          action: call-service
          service: script.log_small_bottle
        icon: mdi:baby-bottle

      - type: button
        name: Medium Bottle
        tap_action:
          action: call-service
          service: script.log_medium_bottle
        icon: mdi:baby-bottle-outline
```

### Complete Baby Dashboard Card

A comprehensive card showing all activity:

```yaml
type: vertical-stack
title: Baby Tracker - Baby Name
cards:
  - type: glance
    entities:
      - sensor.baby_name_feeding_count
      - sensor.baby_name_diaper_count
      - sensor.baby_name_nursing_minutes
    show_name: true
    show_icon: true

  - type: entities
    title: Recent Activity
    entities:
      - sensor.baby_name_last_feeding
      - sensor.baby_name_last_diaper
      - sensor.baby_name_last_sleep
      - sensor.baby_name_last_bath

  - type: entities
    title: Health & Growth
    entities:
      - sensor.baby_name_weight
      - sensor.baby_name_length
      - sensor.baby_name_last_temperature
      - sensor.baby_name_last_medicine
```

### Multi-Baby Dashboard

If you have multiple babies, create tabs or use conditional cards:

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: "# Baby Tracker"

  - type: horizontal-stack
    cards:
      - type: entities
        title: Baby Name
        entities:
          - sensor.baby_name_last_feeding
          - sensor.baby_name_last_diaper
          - sensor.baby_name_feeding_count

      - type: entities
        title: Baby Two
        entities:
          - sensor.baby_two_last_feeding
          - sensor.baby_two_last_diaper
          - sensor.baby_two_feeding_count
```

### Auto-Entities Card (Dynamic)

Automatically shows all sensors for a baby (requires HACS custom:auto-entities):

```yaml
type: custom:auto-entities
card:
  type: entities
  title: All Baby Sensors
filter:
  include:
    - entity_id: "sensor.baby_name_*"
    - entity_id: "binary_sensor.baby_name_*"
  exclude:
    - state: "unknown"
    - state: "unavailable"
sort:
  method: name
```

### Feeding Timeline Card

Track feeding patterns (requires custom:apexcharts-card):

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Feeding Timeline
series:
  - entity: sensor.baby_name_feeding_count
    type: column
    name: Daily Feedings
    group_by:
      func: sum
      duration: 1d
```

## Automation Examples

### Notification When Baby Wakes Up

```yaml
automation:
  - alias: "Baby Woke Up"
    trigger:
      platform: state
      entity_id: binary_sensor.baby_name_currently_sleeping
      from: "on"
      to: "off"
    action:
      - service: notify.mobile_app
        data:
          title: "Baby's Awake!"
          message: "Baby Name just woke up after {{ state_attr('sensor.baby_name_last_sleep', 'duration') }} minutes of sleep"
```

### Daily Summary Notification

```yaml
automation:
  - alias: "Daily Baby Report"
    trigger:
      platform: time
      at: "20:00:00"
    action:
      - service: notify.mobile_app
        data:
          title: "Daily Baby Summary"
          message: >
            Today's totals for Baby Name:
            - Feedings: {{ states('sensor.baby_name_feeding_count') }}
            - Diapers: {{ states('sensor.baby_name_diaper_count') }}
            - Nursing minutes: {{ states('sensor.baby_name_nursing_minutes') }}
            - Current weight: {{ states('sensor.baby_name_weight') }} lbs
```

### Reminder to Feed Baby

```yaml
automation:
  - alias: "Feeding Reminder"
    trigger:
      platform: template
      value_template: >
        {{ (as_timestamp(now()) - as_timestamp(states.sensor.baby_name_last_feeding.attributes.time)) > 10800 }}
    action:
      - service: notify.mobile_app
        data:
          title: "Feeding Time!"
          message: "It's been over 3 hours since Baby Name's last feeding"
```

### Low Medicine Alert

```yaml
automation:
  - alias: "Medicine Reminder"
    trigger:
      platform: state
      entity_id: sensor.baby_name_last_medicine
    condition:
      - condition: template
        value_template: >
          {{ 'Vitamin D' in states('sensor.baby_name_last_medicine') }}
    action:
      - service: notify.mobile_app
        data:
          title: "Vitamin D Given"
          message: "Vitamin D logged at {{ state_attr('sensor.baby_name_last_medicine', 'time') }}"
```

### Age-Based Sleep Monitoring

Monitor if your baby got enough sleep based on their age. This requires creating a helper sensor first:

**Step 1: Create a template sensor to track daily sleep (add to `configuration.yaml`):**

```yaml
template:
  - sensor:
      - name: "Baby Name Total Sleep Today"
        unique_id: baby_name_total_sleep_today
        unit_of_measurement: "hours"
        state: >
          {% set ns = namespace(total=0) %}
          {% set today = now().date() %}
          {% for state in states.sensor.baby_name_last_sleep.attributes.history | default([]) %}
            {% set sleep_date = state.time | as_datetime | as_local %}
            {% if sleep_date.date() == today %}
              {% set ns.total = ns.total + (state.duration | int) %}
            {% endif %}
          {% endfor %}
          {{ (ns.total / 60) | round(1) }}
```

**Step 2: Create automation to check sleep at end of day:**

```yaml
automation:
  - alias: "Check Baby Sleep - Age Based"
    trigger:
      - platform: time
        at: "21:00:00"  # Check at 9 PM
    action:
      - variables:
          # Calculate baby's age in months
          baby_dob: "{{ state_attr('sensor.baby_name_last_feeding', 'baby_dob') }}"
          age_days: "{{ (now() - strptime(baby_dob, '%Y-%m-%d')).days }}"
          age_months: "{{ (age_days / 30.44) | round(0, 'floor') | int }}"

          # Get today's total sleep hours
          sleep_hours: "{{ states('sensor.baby_name_total_sleep_today') | float(0) }}"

          # Determine recommended sleep based on age
          recommended_sleep: >
            {% if age_months < 1 %}
              16
            {% elif age_months < 3 %}
              15.5
            {% elif age_months < 6 %}
              15
            {% elif age_months < 9 %}
              14
            {% elif age_months < 12 %}
              14
            {% elif age_months < 18 %}
              14
            {% elif age_months < 24 %}
              13.5
            {% else %}
              13
            {% endif %}

          # Get age-based sleep breakdown for message
          sleep_breakdown: >
            {% if age_months < 1 %}
              8-9 hours at night, 8 hours during the day
            {% elif age_months < 3 %}
              8-9 hours at night, 7 hours during the day
            {% elif age_months < 6 %}
              9-10 hours at night, 4-5 hours during the day
            {% elif age_months < 9 %}
              10 hours at night, 4 hours during the day
            {% elif age_months < 12 %}
              11 hours at night, 3 hours during the day
            {% elif age_months < 18 %}
              11 hours at night, 3 hours during the day
            {% elif age_months < 24 %}
              11 hours at night, 2.5 hours during the day
            {% else %}
              11 hours at night, 2 hours during the day
            {% endif %}

      - condition: template
        value_template: "{{ sleep_hours < (recommended_sleep | float) }}"

      - service: notify.mobile_app
        data:
          title: "⚠️ Low Sleep Alert"
          message: >
            Baby Name ({{ age_months }} months old) only slept {{ sleep_hours }} hours today.

            Recommended: {{ recommended_sleep }} hours total
            ({{ sleep_breakdown }})

            Deficit: {{ (recommended_sleep | float - sleep_hours) | round(1) }} hours
          data:
            priority: high
            tag: "baby_sleep_alert"
```

**Simpler Version (using estimated age):**

If you don't have DOB in sensor attributes, you can manually set the age:

```yaml
automation:
  - alias: "Sleep Check - 6 Month Old"
    trigger:
      - platform: time
        at: "21:00:00"
    variables:
      # Manually set your baby's age in months
      baby_age_months: 6
      recommended_hours: 14  # For 6-month-old
      nighttime_hours: 10
      daytime_hours: 4
    condition:
      - condition: template
        # Assuming you track daily sleep somehow
        value_template: "{{ states('sensor.baby_name_sleep_today') | float < 14 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Sleep Reminder"
          message: >
            Baby didn't get enough sleep today!
            Recommended for {{ baby_age_months }} months:
            • Total: {{ recommended_hours }} hours
            • Night: {{ nighttime_hours }} hours
            • Day: {{ daytime_hours }} hours

**Sleep Recommendations by Age:**

| Age | Total Hours | Night Sleep | Day Sleep |
|-----|-------------|-------------|-----------|
| Newborn | 16 | 8-9 | 8 |
| 1 month | 15.5 | 8-9 | 7 |
| 3 months | 15 | 9-10 | 4-5 |
| 6 months | 14 | 10 | 4 |
| 9 months | 14 | 11 | 3 |
| 1 year | 14 | 11 | 3 |
| 1.5 years | 13.5 | 11 | 2.5 |
| 2 years | 13 | 11 | 2 |

### Dirty Diaper Monitoring

Alert if baby hasn't had a dirty diaper for too long (important for health monitoring):

**Basic Version - Fixed Time Alert:**

```yaml
automation:
  - alias: "No Dirty Diaper Alert"
    trigger:
      - platform: time_pattern
        hours: "/3"  # Check every 3 hours
    condition:
      - condition: template
        value_template: >
          {% set last_diaper = state_attr('sensor.baby_name_last_diaper', 'status') %}
          {% set last_time = state_attr('sensor.baby_name_last_diaper', 'time') %}
          {% set hours_since = ((as_timestamp(now()) - as_timestamp(strptime(last_time, '%Y-%m-%d %H:%M:%S'))) / 3600) | round(1) %}
          {{ (last_diaper in ['Wet', 'Clean']) and hours_since > 24 }}
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ No Dirty Diaper Alert"
          message: >
            It's been over 24 hours since Baby Name's last dirty diaper.
            Last diaper was {{ state_attr('sensor.baby_name_last_diaper', 'status') }}
            at {{ state_attr('sensor.baby_name_last_diaper', 'time') }}.
          data:
            priority: high
            tag: "dirty_diaper_alert"
```

**Advanced Version - Age-Based Monitoring:**

Different age groups have different normal patterns for bowel movements:

```yaml
automation:
  - alias: "Dirty Diaper Check - Age Based"
    trigger:
      - platform: time_pattern
        hours: "/2"  # Check every 2 hours
    action:
      - variables:
          # Get last diaper info
          last_diaper_time: "{{ state_attr('sensor.baby_name_last_diaper', 'time') }}"
          last_diaper_status: "{{ state_attr('sensor.baby_name_last_diaper', 'status') }}"

          # Calculate hours since last dirty diaper
          hours_since_dirty: >
            {% set count = states('sensor.baby_name_poopy_count') | int(0) %}
            {% if count == 0 %}
              {% set last_time = state_attr('sensor.baby_name_last_diaper', 'time') %}
              {% if last_time %}
                {{ ((as_timestamp(now()) - as_timestamp(strptime(last_time, '%Y-%m-%d %H:%M:%S'))) / 3600) | round(1) }}
              {% else %}
                0
              {% endif %}
            {% else %}
              0
            {% endif %}

          # Calculate baby's age (if you have DOB in attributes)
          baby_age_months: 6  # Manually set, or calculate from DOB

          # Determine alert threshold based on age
          max_hours_threshold: >
            {% if baby_age_months < 1 %}
              12
            {% elif baby_age_months < 3 %}
              18
            {% elif baby_age_months < 6 %}
              24
            {% elif baby_age_months < 12 %}
              36
            {% else %}
              48
            {% endif %}

      - condition: template
        value_template: "{{ hours_since_dirty | float > max_hours_threshold | float }}"

      - service: notify.mobile_app
        data:
          title: "⚠️ Dirty Diaper Alert"
          message: >
            Baby Name ({{ baby_age_months }} months) hasn't had a dirty diaper in {{ hours_since_dirty | round(1) }} hours.

            Normal for {{ baby_age_months }} months: Within {{ max_hours_threshold }} hours

            Last diaper: {{ last_diaper_status }} at {{ last_diaper_time }}
          data:
            priority: high
            tag: "dirty_diaper_alert"
```

**Using Poopy Count Sensor:**

Simpler approach using the daily poopy count:

```yaml
automation:
  - alias: "Daily Dirty Diaper Check"
    trigger:
      - platform: time
        at: "18:00:00"  # Check at 6 PM daily
    condition:
      - condition: numeric_state
        entity_id: sensor.baby_name_poopy_count
        below: 1
    action:
      - service: notify.mobile_app
        data:
          title: "No Dirty Diaper Today"
          message: >
            Baby Name hasn't had a dirty diaper yet today ({{ states('sensor.baby_name_poopy_count') }} so far).
            Last diaper: {{ states('sensor.baby_name_last_diaper') }} at {{ state_attr('sensor.baby_name_last_diaper', 'time') }}
          data:
            tag: "daily_dirty_diaper_check"
```

**Constipation Warning (Multiple Days):**

Alert if no dirty diapers for 2+ days (more serious):

```yaml
automation:
  - alias: "Constipation Alert"
    trigger:
      - platform: time
        at: "09:00:00"  # Check once daily at 9 AM
    condition:
      - condition: template
        value_template: >
          {% set last_time_str = state_attr('sensor.baby_name_last_diaper', 'time') %}
          {% if last_time_str %}
            {% set last_time = strptime(last_time_str, '%Y-%m-%d %H:%M:%S') %}
            {% set hours_ago = (as_timestamp(now()) - as_timestamp(last_time)) / 3600 %}
            {% set last_status = state_attr('sensor.baby_name_last_diaper', 'status') %}
            {{ (last_status in ['Wet', 'Clean']) and hours_ago > 48 }}
          {% else %}
            false
          {% endif %}
    action:
      - service: notify.mobile_app
        data:
          title: "🚨 Constipation Warning"
          message: >
            URGENT: Baby Name hasn't had a dirty diaper in over 48 hours.

            Last dirty diaper: {{ state_attr('sensor.baby_name_last_diaper', 'time') }}

            Consider contacting your pediatrician if this continues.
          data:
            priority: high
            notification_icon: "mdi:alert-circle"
            tag: "constipation_alert"
            actions:
              - action: "CALL_DOCTOR"
                title: "Call Doctor"
```

**Normal Bowel Movement Frequency by Age:**

| Age | Normal Frequency |
|-----|------------------|
| Newborn (0-1 month) | 4-12 times per day |
| 1-3 months | 2-4 times per day |
| 3-6 months | 1-2 times per day |
| 6-12 months | 1 time per day or every other day |
| 1+ years | 1 time per day or every 2 days |

**Important Notes:**
- Breastfed babies may go several days without a dirty diaper after 6 weeks (this is normal!)
- Formula-fed babies typically have more regular bowel movements
- If baby shows signs of discomfort, bloating, or straining, contact pediatrician regardless of time
- These automations are helpers, not medical advice - always consult your doctor with concerns

## Troubleshooting

- **Connection Issues**: If you're having trouble connecting, check that your Baby Tracker credentials are correct
- **Data Not Updating**: Try manually triggering a sync with the `baby_tracker.sync` service
- **Missing Data**: Make sure the database path is writeable by Home Assistant
- **Sensors Not Appearing**: Restart Home Assistant after installation
- **Multi-Baby Issues**: Use the `list_babies` service to see all babies and their names
- **Google Home Not Working**: Ensure scenes are exposed in Google Assistant configuration and routines are set up correctly

## Privacy Notice

This integration stores your Baby Tracker credentials locally to sync with the Baby Tracker servers. No data is sent to third parties. All data is stored in a local SQLite database in your Home Assistant configuration directory.

## Database Location

The integration stores baby data in: `{config_directory}/baby_tracker.db`

This database is automatically synced with the Baby Tracker servers at the configured interval.

## Support

For issues and feature requests, please submit them through the GitHub repository's issue tracker.

## Credits

This integration provides a local interface to the Baby Tracker app (https://www.baby-tracker.com/). All trademarks belong to their respective owners.
