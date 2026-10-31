# Baby Tracker for Home Assistant

This custom component integrates the Baby Tracker app data with Home Assistant, allowing you to monitor and update your baby's activities through Home Assistant.

## Features

- **Multi-Baby Support**: Track multiple babies with separate sensors and data for each child
- **Automatic Syncing**: Synchronizes with the Baby Tracker servers to fetch the latest data
- **Comprehensive Sensors**: 20+ sensors per baby tracking feeding, diapers, sleep, growth, medicine, and more
- **Household view, calendar and events**: sensors across all babies, a calendar and an Activity event entity per baby, and [blueprints](#blueprints) for notifications
- **Service Calls**: Add new records through Home Assistant service calls
- **Controls**: Set a bottle size, bottle type, medicine and amount once, then log with one button; time nursing with Start/End buttons
- **Undo**: An Undo Last Entry button per baby, and `undo_last` and `delete_record` services, take back a mis-pressed button
- **Alert settings and repairs**: Tune the alert thresholds in the options, and see sync problems on Home Assistant's Repairs page
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

### Upgrading from 0.2

Version 0.3 changes how several entities report their state, so check your dashboards and automations after upgrading. [CHANGELOG.md](CHANGELOG.md#breaking-changes-in-030) has the full list. The ones that most often need a fix:

- **Enum states are lowercase.** *Last Diaper* is `wet`, `poopy`, `mixed` or `dry` (it used to be `Wet`, `Poopy`, ...), and *Last Feeding* is `nursing`, `formula`, `pumped` or `supplement`. Update any `is_state(...)` or `states(...) == ...` check. The `status` attribute keeps its capitalised text.
- **States are numbers and timestamps, not text.** Durations are minutes and volumes, weights and lengths are numbers with units. Use the new *Last Feeding Time*, *Last Diaper Time* and *Last Sleep Time* timestamp sensors instead of parsing text. Times in attributes are still text in the form `2026-10-30 11:00:00 +0000`, so parse them with `strptime(value, '%Y-%m-%d %H:%M:%S %z')`.
- **Bottle oz is gone.** *Bottle oz* and *Bottle ml* are now one *Bottle Volume* sensor that keeps the entity of *Bottle ml*, so an upgraded install has `sensor.<baby>_bottle_ml` and a new one has `sensor.<baby>_bottle_volume`. Point anything that used `sensor.<baby>_bottle_oz` at it; the oz totals are in its `bottle_amount_oz` attribute.
- **Photos moved out of `www/`.** The `/local/baby_tracker/...` URLs no longer work; use each baby's *Photo* image entity and delete `www/baby_tracker`. See [Photos](#photos).
- **Config entries are migrated to version 2 on their own.** Back up first if you may want to go back to 0.2, because 0.2 cannot open a migrated entry.

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
babytracker add-bottle --baby Everly --amount 4 --unit oz --type formula   # or --unit ml, --type pumped
babytracker add-nursing --baby Everly --left 10 --right 8                  # minutes per side
babytracker insights --baby Everly          # next feed, 24 hour intake, diapers, growth percentiles
babytracker next                            # each baby's predicted next feed, and who is due first
babytracker calendar --baby Everly --days 2 # feeds, sleeps, baths, visits and medicines
babytracker recent --baby Everly --limit 10 # newest records, with the type and ID `delete` takes
babytracker delete Diaper <object-id> --yes # delete a record on every device
babytracker undo --baby Everly --yes        # delete the newest record from the last day
babytracker inventory                       # pumped milk in store
babytracker devices
babytracker raw <device-uuid> --since 100   # decoded records exactly as the server sends them
```

Every command prints JSON. `--baby` is a baby's name and can be left out when the account has only one baby; `--offline` skips the sync that normally runs first.

Each client registers as its own device in the app. The CLI keeps its device ID and local database in `~/.babytracker`, separate from Home Assistant's.

### Development

[CONTRIBUTING.md](CONTRIBUTING.md) covers the layout, adding a record type and running the tests. In short, the repo follows Home Assistant's [integration blueprint](https://github.com/ludeeus/integration_blueprint) setup:

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

- **Entity ID format**: `<domain>.<baby name>_<entity name>`. The examples in this README use a baby called Everly (and Ann Marie as a second baby); use your own baby's name.
- **Examples**:
  - `sensor.everly_last_diaper`
  - `sensor.everly_weight`
  - `sensor.everly_last_feeding`
  - `button.everly_add_bottle`

All services take an optional `baby_name` parameter (or pick the baby's device). If you leave it out, the service uses the baby when there is only one, and refuses to guess when there are several.

## Available Sensors

After setting up the integration, the following entities will be created **for each baby**. States are numbers or timestamps (not text) wherever they can be, so history graphs, statistics and automations work on them directly. The details are in attributes: times of the record as text, notes, durations per side, and so on.

The integration's **Units** setting (imperial or metric, changeable in the options) decides how volumes, weights, lengths and temperatures are shown. Volumes, weights and lengths are stored as mL, kg and cm and displayed in fl oz, lb and in for imperial; you can still pick another unit in the entity's settings.

### Activity Sensors

| Sensor | State | Unit and class |
| --- | --- | --- |
| Last Feeding | Type of the last feeding: `nursing`, `formula`, `pumped` or `supplement` | enum |
| Last Feeding Time | When the last feeding was | timestamp |
| Last Diaper | Status of the last change: `wet`, `poopy`, `mixed` or `dry` | enum |
| Last Diaper Time | When the last diaper change was | timestamp |
| Last Sleep | Minutes slept, or so far if the baby is asleep now (the `sleeping` attribute says which) | min, duration |
| Last Sleep Time | When the last sleep started | timestamp |
| Last Nursing | Minutes of the last nursing session (left, right and both in attributes) | min, duration |
| Last Bath | Type of the last bath | text |
| Last Activity | Name of the last other activity, such as tummy time (`duration` in minutes and `time` in attributes) | text |
| Temperature | Most recent temperature, in the entry's unit | °F or °C, temperature |
| Time Since Last Feeding | Minutes since the last feeding; `feeding_status` and `needs_feeding` are attributes | min, duration |
| Next Feeding | Minutes until the age-based feeding limit (negative once overdue) | min, duration |
| Average Bedtime | Average night bedtime of the last two weeks, with a per-day list in the attributes | text |
| Daily Summary | Feedings so far today; formula, nursing minutes, diapers and sleep hours in attributes | feedings |

### Summary Sensors (Last 7 Days)

These are totals over a rolling 7 days (the `window_days` attribute says so), updated on every refresh.

| Sensor | State | Unit and class |
| --- | --- | --- |
| Feedings | Total number of feedings | feedings |
| Nursing Minutes | Total nursing time | min, duration |
| Bottle Volume | Formula and pumped milk from the bottle (oz equivalents in the attributes). Replaces the old *Bottle oz* and *Bottle ml* sensors; it keeps the entity of *Bottle ml* | mL, volume |
| Diapers | Total diaper changes | diapers |
| Poopy Diapers | Dirty diapers, mixed ones included; `last_poopy_time` and `hours_since_last_poopy` in the attributes | diapers |
| Wet Diapers | Wet diapers, mixed ones included | diapers |

### Health & Growth Sensors

| Sensor | State | Unit and class |
| --- | --- | --- |
| Last Medicine | Name of the last medicine given | text |
| Last Pump | Total from the last pump session, whichever unit it was logged in | mL, volume |
| Pump Summary (diagnostic) | 7-day pumping total; sessions and durations in attributes | mL, volume |
| Weight | Most recent weight | kg, weight |
| Length | Most recent length/height | cm, distance |
| Head Circumference | Most recent head circumference | cm, distance |

### Milestone & Medical Sensors

| Sensor | State | Unit and class |
| --- | --- | --- |
| Last Milestone | Name of the most recent milestone | text |
| Last Doctor Visit | When the most recent doctor appointment or visit was | timestamp |
| Last Vaccine | Name of the most recent vaccine | text |

### Alerts, Night Mode and Housekeeping

- **Alerts** (`binary_sensor`): Feeding Overdue, No Poop, Low Wet Diapers, Fever, Long Sleep, plus the three insight alerts below. Their thresholds can be changed in the [options](#options)
- **Night Mode** (`binary_sensor`): on while the baby sleeps at night, 19:00 to 07:00 unless you change the [night hours](#options)
- **Nursing** (`binary_sensor`): on while a [nursing timer](#nursing-timer) is running
- **Info** (diagnostic sensor): the baby's age, with date of birth and other details in attributes
- **Photo** and **Photo Landscape** (`image`): the baby's photo from the app, and its wide version when the app has one. See [Photos](#photos)
- **Recent Entries** (diagnostic sensor): the baby's newest records, with the type and ID that `delete_record` takes. See [Undoing a mistake](#undoing-a-mistake)
- **Sync Now** and **Force Resync** (configuration buttons on the *Baby Tracker* device)
- **Buttons** for quick logging: wet/dirty/mixed diapers, bath, start/end sleep, and the [controls and buttons](#controls-and-buttons) below (bottle, medicine, nursing timer, tummy time)
- **Fixed-size bottle buttons** (3 to 8 oz) and **Give Tylenol**: still available, and kept on installs that already have them. They are switched off by default on new installs now that *Add Bottle* and *Give Medicine* cover them; turn them on from the entity settings if you want them

### Photos

Each baby's photo is shown by its **Photo** image entity (for example `image.everly_photo`), for dashboards and picture cards. If the app also has a landscape (wide) version of the photo, the baby gets a **Photo Landscape** entity (`image.everly_photo_landscape`) too, which suits banner cards; it is created when the integration is set up, so reload it after adding a landscape photo in the app. The files are kept in a private `baby_tracker` folder in your Home Assistant configuration directory (photos attached to activities go in its `pictures` subfolder) and are only served through the image entity, which needs a login or the entity's access token. They are **not** under `www`, so nobody can fetch them without logging in.

Earlier versions saved photos in `www/baby_tracker`, where anyone who could reach Home Assistant could fetch them without logging in. Those old copies are not deleted for you: remove the `www/baby_tracker` folder. Home Assistant shows a [repair](#repairs) on *Settings > Repairs* while it exists.

## Controls and Buttons

Each baby has a few settings that the logging buttons use, so a bottle of any size or any medicine is one tap:

| Entity (for Everly) | What it is |
| --- | --- |
| `number.everly_bottle_size` | How much the Add Bottle button logs. Ounces in 0.5 steps from 1 to 12 for an imperial entry; mL in steps of 10 from 30 to 360 for a metric one. Starts at 4 oz / 120 mL |
| `select.everly_bottle_type` | `formula` or `pumped`: which kind of bottle Add Bottle logs |
| `button.everly_add_bottle` | Logs a bottle of the Bottle Size, as formula or pumped milk (Bottle Type) |
| `select.everly_medicine` | Which of your account's medicines (the ones in the app) Give Medicine logs. Starts on the first |
| `number.everly_medicine_amount` | The dose Give Medicine logs, in 0.1 steps. Choosing a medicine sets it to that medicine's usual amount from the app (when it has one), and its `unit` attribute shows the medicine's unit. Give Medicine uses the usual amount if this is 0 or unset |
| `button.everly_give_medicine` | Logs a dose of the selected medicine |
| `number.everly_tummy_time_minutes` | How long Log Tummy Time logs. Starts at 15 |
| `button.everly_log_tummy_time` | Logs that much tummy time |
| `button.everly_undo_last_entry` | Deletes the baby's newest record from the last 24 hours. See [Undoing a mistake](#undoing-a-mistake) |

The settings are remembered across restarts. A bottle size saved in the other unit (after switching the entry between imperial and metric) is not reused. Under the same device you will also find the existing *Add Wet/Dirty/Mixed Diaper*, *Log Bath* and *Start/End Sleep* buttons.

A second press of the same button within 3 seconds is ignored (it is logged at info level), so a double tap or an automation that fires twice does not log a record twice. Logging a record asks for a refresh of the sensors, which Home Assistant spreads out if several come together.

A dashboard card for a baby:

```yaml
type: entities
title: Everly
entities:
  - select.everly_bottle_type
  - number.everly_bottle_size
  - button.everly_add_bottle
  - select.everly_medicine
  - number.everly_medicine_amount
  - button.everly_give_medicine
  - button.everly_log_tummy_time
```

### Undoing a mistake

**Undo Last Entry** (`button.everly_undo_last_entry`) deletes the newest record of any kind for that baby, as long as it is less than 24 hours old, and it is removed on your other devices too the next time they sync. It does nothing but report "Nothing to undo" when there is no such record, and a double tap deletes only one. Home Assistant logs what was deleted at info level, fires a `baby_tracker_undo` event on the bus and an `undo` event on the baby's Activity event entity.

The **Recent Entries** sensor (`sensor.everly_recent_entries`, a diagnostic entity) shows the newest record in its state, for example `wet diaper` or `formula 4 oz`, and the last ten in its `records` attribute, each with `object_type`, `object_id`, `time`, `kind` and `note`. Use the `object_type` and `object_id` with the [`delete_record` service](#undo-last-and-delete-record) to delete an older record.

### Nursing Timer

Like Start/End Sleep, the nursing buttons time a session and log it when it ends:

- `button.everly_start_nursing_left` and `button.everly_start_nursing_right` start the timer on that side. Pressing the other side while it runs switches over and keeps the time so far.
- `button.everly_end_nursing` stops the timer and logs one nursing record, dated when the session started, with the minutes spent on each side (at least one minute in total) and the side you finished on.
- `binary_sensor.everly_nursing` is on while a timer runs, with the `side` being nursed and `started_at` as attributes.

The running timer is kept in Home Assistant, not in the Baby Tracker app, so it is lost if Home Assistant restarts. If logging fails (for example, the server is down), the timer keeps running and you can press End Nursing again.

## Options

Choose **Configure** on the integration to change:

| Option | What it does |
| --- | --- |
| Update interval | Minutes between refreshes (default 15) |
| Units | Imperial or metric for volumes, weights, lengths and temperatures |
| Feeding overdue after (hours) | Feeding Overdue turns on this long after the last feeding. 0 (the default) uses the baby's age: 3.5 hours for a newborn, up to 6 for older babies |
| Wet diapers expected per day | Low Wet Diapers turns on after 8 pm when there have been fewer than this many (default 4) |
| Night starts at / Night ends at | The hours (0-23) Night Mode uses; default 19 and 7. Night can run past midnight |
| Fever temperature | Fever turns on at or above this, in the unit chosen above. Leave blank for 100.4 °F (38.0 °C) |

The options are saved as `scan_interval`, `unit_system`, `feeding_overdue_hours`, `low_wet_minimum`, `night_start_hour`, `night_end_hour` and `fever_threshold`. The integration reloads when you save them.

## Repairs

Problems you can act on show up on *Settings > Repairs*:

- **Old baby photos are publicly readable**: the `www/baby_tracker` folder from earlier versions still exists. Delete it; the photos are kept privately now. The repair goes away on its own after you delete it and restart or reload the integration.
- **Baby Tracker records aren't reaching the server**: records logged in Home Assistant have stayed unsent for more than 3 refreshes in a row. They are kept and sent when the server accepts them; the repair clears once they have gone.
- **Baby Tracker account was reset**: the account was reset or recreated in the app, so the data here belongs to the old group and syncing has stopped. Press Force Resync. The repair clears after the next successful sync.

Refreshes, service calls and button presses never write to the local database at the same time, and the database waits up to 10 seconds for a lock rather than failing.

## Insights

Alongside the raw logs, each baby gets a few derived entities. They are recalculated on every refresh from what you have logged, and show as unknown when there is not enough data (no weight, no feeds, and so on).

| Entity | What it shows |
| --- | --- |
| `sensor.<baby>_next_feed` | Timestamp of the next expected feed, from the median of recent feed intervals (day and night separately), with the interval, basis and sample size as attributes |
| `sensor.<baby>_feed_interval` | The usual time between feeds, in hours |
| `sensor.<baby>_intake_24h` | Bottle milk (formula and pumped) over the last 24 hours, with the expected range for the baby's weight. Shown in fl oz when the integration is set to imperial units |
| `sensor.<baby>_intake_status` | `low`, `ok`, `high` or `unknown` against that range |
| `sensor.<baby>_diaper_adequacy` | `ok`, `low` or `unknown` for wet and dirty diapers in the last 24 hours, for the baby's age |
| `sensor.<baby>_weight_percentile`, `_length_percentile`, `_head_percentile` | Percentile of the latest measurement on the WHO growth standard (attributes give z-score and the 3rd, 50th and 97th percentile values in kg or cm) |
| `sensor.<baby>_weight_gain` | Grams per day between the latest two weights at least 5 days apart, with the expected range |
| `sensor.<baby>_corrected_age` | Age in days corrected for prematurity (diagnostic) |
| `binary_sensor.<baby>_intake_low` | On when intake status is `low` |
| `binary_sensor.<baby>_feed_due` | On once the predicted next feed time has passed |
| `binary_sensor.<baby>_wake_to_feed` | On when a young baby has gone past the longest sensible gap between feeds |

The numbers rest on published guidance: roughly 150-200 ml of milk per kg of body weight per day (AAP and NHS feeding guidance, capped at 960 ml), the WHO Child Growth Standards for percentiles (read from the CDC's copy of the tables, bundled in `custom_components/baby_tracker/client/data`), and, for babies born before 37 weeks, age corrected for prematurity until 24 months as the AAP recommends. Feed timing, diaper and weight gain ranges are rules of thumb, not measurements of your baby. **These entities are not medical advice and cannot diagnose anything.** Every baby is different; talk to your pediatrician or health visitor about any worry about feeding, diapers or growth.

The three binary sensors work like the other alerts: they can be dismissed with `baby_tracker.dismiss_alert` using their entity ID.

### Alerts that follow the clock

Feed Due, Wake To Feed, Feeding Overdue, Night Mode, Time Since Last Feeding and Next Feeding depend on the time of day, not only on new records, so they are re-evaluated **every minute** rather than once per refresh. Feed Due turns on at the predicted time even if the next refresh is fifteen minutes away. Every alert also has a `baby_name` attribute, handy in notification templates.

## Derived sensors

These are worked out from the records the app already stores, on every refresh.

| Entity | What it shows |
| --- | --- |
| `sensor.<baby>_which_breast_next` | `left`, `right` or `unknown`: the side the last nursing or pump session did not finish on. It uses the app's own rule: the latest nursing session is compared with the latest pump session (inventory adjustments don't count) and the more recent one decides. Like the app, it looks at every baby's nursing, since the mother is the same. Attributes: `last_side`, `last_type` (`nursing` or `pump`), `last_time` |
| `sensor.<baby>_next_medicine_dose` | Timestamp when the baby's last medicine can be given again: the time it was given plus the interval set on that medicine in the app. Unknown when the medicine has no interval. Attributes: `medicine_name`, `amount`, `unit`, `last_given`, `interval_minutes` |
| `sensor.<baby>_upcoming_milestones` | Name of the next milestone the baby hasn't logged yet, youngest `for_age_months` first. Attributes: `count` and an `upcoming` list (the first ten) |
| `sensor.<baby>_upcoming_vaccines` | Name of the next vaccine the baby hasn't had, in the same way |

Upcoming milestones and vaccines are the app's own lists, ordered by the age in months each is expected at, minus what has been logged for that baby. Nothing says a baby is behind schedule: the first item is simply the first one not yet ticked off.

## Household view

The *Baby Tracker* device (the one with the Sync Now button) holds sensors that look across all your babies:

| Entity | What it shows |
| --- | --- |
| `sensor.baby_tracker_next_feed_due` | Timestamp of the earliest predicted next feed among the babies. Attributes: `baby` (whose it is) and `predictions` (every baby's predicted time) |
| `sensor.baby_tracker_next_feed_baby` | Name of the baby who is due to feed first |
| `sensor.baby_tracker_last_fed_baby` | Name of the baby fed most recently; the `time` attribute says when |
| `sensor.baby_tracker_babies_asleep` | How many babies are asleep now; the `babies` attribute lists them |
| `sensor.baby_tracker_feeds_today` | Feedings so far today across all babies; `per_baby` has each one's count |
| `sensor.baby_tracker_pumped_milk_inventory` | Pumped milk in store: everything pumped (including inventory adjustments you made in the app) minus everything fed from the pump, like the app's own inventory. Shown in the entry's volume unit. Can go negative if feeds were logged without the pumping |
| `sensor.baby_tracker_pending_uploads` (diagnostic) | Records logged from Home Assistant that the Baby Tracker server hasn't received yet |

## Calendar

Each baby has a calendar (for example `calendar.baby_name_calendar`) showing their feeds, sleeps, baths, doctor visits and medicines, so you can scroll back through a day or a week in the Calendar panel or a calendar card. A sleep lasts as long as it did (a sleep still in progress runs up to now); everything else is a 15-minute event. The calendar entity's own state is on while the most recent event is still running, and its message is that event.

## Event entities

Each baby has an **Activity** event entity (`event.baby_name_activity`). It fires when a refresh finds something new, with one of these event types: `feeding`, `diaper`, `sleep_start`, `sleep_end`, `bath`, `medicine` or `undo` (an entry was deleted with Undo Last Entry or the `undo_last` service). The details (type, time, medicine name and so on) are attributes of the event. In an automation:

```yaml
triggers:
  - trigger: state
    entity_id: event.baby_name_activity
    attribute: event_type
    to: sleep_end
```

The `baby_tracker_feeding`, `baby_tracker_diaper` and `baby_tracker_sleep` events on the event bus are still fired as before. Nothing fires on the first refresh after startup.

## Blueprints

Ready-made automations in [`blueprints/automation/baby_tracker`](blueprints/automation/baby_tracker). Import one with its button, or in Home Assistant go to **Settings > Automations & Scenes > Blueprints > Import Blueprint** and paste the file's address.

| Blueprint | What it does | Import |
| --- | --- | --- |
| Feed due notification | Notifies a phone when a baby's Feed Due turns on, with the baby's name in the message | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fisaiahnicolai%2Fbaby-tracker-home-assistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbaby_tracker%2Ffeed_due_notification.yaml) |
| Wake to feed | Notifies a phone when a baby should be woken to eat | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fisaiahnicolai%2Fbaby-tracker-home-assistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbaby_tracker%2Fwake_to_feed.yaml) |
| Daily intake summary | At a time you choose, sends how much milk the baby has had in 24 hours (by default only when it is low) | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fisaiahnicolai%2Fbaby-tracker-home-assistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbaby_tracker%2Flow_intake_daily.yaml) |

The address pattern is `https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=<URL-encoded address of the blueprint file on GitHub>`. Each blueprint asks which baby's sensor to watch and which phone (a device with the Home Assistant app) to notify; create one automation per baby.

## Service Calls

All services support multi-baby tracking with an optional `baby_name` parameter.

Every service that adds a record (all of the ones below except the utility services) also takes an optional **`time`**: when it happened, for logging something afterwards. Without it the record is dated now. A time without a time zone is in Home Assistant's time zone. In the UI it is a date and time picker.

```yaml
service: baby_tracker.add_diaper
data:
  baby_name: "Your Baby Name"
  poo: true
  time: "2026-03-01 09:30:00" # Optional - an hour ago, say, instead of now
```

Where a service takes a unit (oz or ml, pounds or kilograms, inches or centimeters, Fahrenheit or Celsius) and you leave it out, it follows the integration's **Units** setting.

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
  is_english_measure: false # Optional (default: follows the Units setting)
  note: "Optional note"
```

#### Add Pumped Milk

```yaml
service: baby_tracker.add_pumped
data:
  baby_name: "Your Baby Name" # Optional
  amount: 90 # Amount in ml (or oz if is_english_measure is true)
  is_english_measure: false # Optional (default: follows the Units setting)
  note: "Optional note"
```

#### Add Temperature

```yaml
service: baby_tracker.add_temperature
data:
  baby_name: "Your Baby Name" # Optional
  temperature: 98.6
  is_fahrenheit: true # Optional (default: follows the Units setting)
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
  is_english_scale: true # true for oz, false for ml (default: follows the Units setting)
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
  is_english_weight_scale: true # true for lbs, false for kg (default: follows the Units setting)
  is_english_length_scale: true # true for inches, false for cm (default: follows the Units setting)
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

#### Log Activity

Tummy time and other activities. If your account already has an activity of that name it is reused; otherwise a new one is created.

```yaml
service: baby_tracker.log_activity
data:
  baby_name: "Your Baby Name" # Optional
  activity_name: "Tummy Time" # Optional (default: Tummy Time)
  duration: 15 # Minutes
  time: "2026-03-01 09:30:00" # Optional
  note: "Optional note"
```

#### Add Solids

```yaml
service: baby_tracker.add_solids
data:
  baby_name: "Your Baby Name" # Optional
  food_name: "Banana" # Must match a food in your Baby Tracker app's solids list
  amount: 2
  unit: "tbsp" # Optional
  is_english_measure: true # Optional (default: follows the Units setting)
  note: "First taste"
```

### Utility Services

#### Undo Last and Delete Record

```yaml
service: baby_tracker.undo_last
data:
  baby_name: "Your Baby Name" # Optional if you have only one baby (or pick the baby's device)
  within_hours: 24 # Optional: only undo a record this recent (default 24)
```

Deletes the baby's newest record of any kind, here and on the other devices. It fails with "Nothing to undo" if there is no record in that window.

```yaml
service: baby_tracker.delete_record
data:
  object_type: Diaper # Diaper, Nursing, Formula, Pumped, OtherFeed, Sleep, Temperature, Medication, Bath, Growth, Milestone, Vaccine, OtherActivity, Joy, Journal or DoctorVisit
  object_id: "0B1C2D3E-..." # From the Recent Entries sensor's records attribute
  baby_name: "Your Baby Name" # Optional: only used to report the deletion on that baby's Activity event
```

Deletes one record by type and ID. It fails with an error message if there is no such record.

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

#### Force Resync

```yaml
service: baby_tracker.force_resync
```

Deletes the local copy of the data and downloads everything again, for when the sync group was reset in the app. Records that were never uploaded are sent first; if that fails nothing is deleted. The **Force Resync** button does the same.

#### Dismiss Alerts

```yaml
service: baby_tracker.dismiss_alert
data:
  baby_name: "Your Baby Name" # Optional
  alert_type: feed_due # Optional: feeding_overdue, no_poop, low_wet_diapers, fever, long_sleep, intake_low, feed_due or wake_to_feed
  entity_id: binary_sensor.everly_feed_due # Optional - dismiss one alert by its entity
```

Dismissed until the condition clears and comes back. `baby_tracker.dismiss_all_alerts` dismisses every active alert (a baby's, with `baby_name`).

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
  - entity: sensor.everly_last_feeding
    name: Last Feeding
  - entity: sensor.everly_last_diaper
    name: Last Diaper
  - entity: sensor.everly_last_sleep
    name: Last Sleep
  - type: attribute
    entity: sensor.everly_last_sleep
    attribute: sleeping
    name: Sleeping Now
  - entity: sensor.everly_temperature
    name: Temperature
```

### Daily Summary Glance Card

Shows the 7-day totals at a glance (for today's alone, use the attributes of `sensor.everly_daily_summary`):

```yaml
type: glance
title: Last 7 Days
entities:
  - entity: sensor.everly_feedings
    name: Feedings
  - entity: sensor.everly_diapers
    name: Diapers
  - entity: sensor.everly_nursing_minutes
    name: Nursing
  - entity: sensor.everly_bottle_volume # sensor.everly_bottle_ml if you upgraded from 0.2
    name: Bottles
```

### Growth Tracking Card

Monitor your baby's growth measurements:

```yaml
type: entities
title: Growth Measurements
entities:
  - entity: sensor.everly_weight
    name: Weight
  - entity: sensor.everly_length
    name: Length
  - entity: sensor.everly_head_circumference
    name: Head Circumference
  - type: attribute
    entity: sensor.everly_weight
    attribute: time
    name: Last Measured
```

### Medical History Card

Track medical information:

```yaml
type: entities
title: Medical History
entities:
  - entity: sensor.everly_last_doctor_visit
    name: Last Doctor Visit
  - entity: sensor.everly_last_vaccine
    name: Last Vaccine
  - entity: sensor.everly_last_medicine
    name: Last Medicine
```

### Milestone Tracker Card

Celebrate developmental milestones:

```yaml
type: entities
title: Milestones
entities:
  - entity: sensor.everly_last_milestone
    name: Latest Milestone
  - type: attribute
    entity: sensor.everly_last_milestone
    attribute: time
    name: Achieved On
  - type: attribute
    entity: sensor.everly_last_milestone
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
title: Baby Tracker - Everly
cards:
  - type: glance
    entities:
      - sensor.everly_feedings
      - sensor.everly_diapers
      - sensor.everly_nursing_minutes
    show_name: true
    show_icon: true

  - type: entities
    title: Recent Activity
    entities:
      - sensor.everly_last_feeding
      - sensor.everly_last_diaper
      - sensor.everly_last_sleep
      - sensor.everly_last_bath

  - type: entities
    title: Health & Growth
    entities:
      - sensor.everly_weight
      - sensor.everly_length
      - sensor.everly_temperature
      - sensor.everly_last_medicine
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
        title: Everly
        entities:
          - sensor.everly_last_feeding
          - sensor.everly_last_diaper
          - sensor.everly_feedings

      - type: entities
        title: Ann Marie
        entities:
          - sensor.ann_marie_last_feeding
          - sensor.ann_marie_last_diaper
          - sensor.ann_marie_feedings
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
    - entity_id: "sensor.everly_*"
    - entity_id: "binary_sensor.everly_*"
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
  - entity: sensor.everly_daily_summary # feedings so far today, so each day's highest value is its total
    type: column
    name: Daily Feedings
    group_by:
      func: max
      duration: 1d
```

## Automation Examples

### Notification When Baby Wakes Up

```yaml
automation:
  - alias: "Baby Woke Up"
    trigger:
      platform: state
      entity_id: sensor.everly_last_sleep
      attribute: sleeping # true while the baby is asleep
      from: true
      to: false
    action:
      - service: notify.mobile_app
        data:
          title: "Baby's Awake!"
          message: "Everly just woke up after {{ states('sensor.everly_last_sleep') }} minutes of sleep"
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
            Today's totals for Everly:
            - Feedings: {{ states('sensor.everly_daily_summary') }}
            - Diapers: {{ state_attr('sensor.everly_daily_summary', 'diaper_count') }}
            - Nursing minutes: {{ state_attr('sensor.everly_daily_summary', 'nursing_minutes') }}
            - Sleep hours: {{ state_attr('sensor.everly_daily_summary', 'sleep_hours') }}
            - Current weight: {{ states('sensor.everly_weight') }} {{ state_attr('sensor.everly_weight', 'unit_of_measurement') }}
```

### Reminder to Feed Baby

The *Last Feeding Time* sensor is a timestamp, so it needs no parsing. (The *Feed Due* alert and the [blueprints](#blueprints) do this from a prediction instead of a fixed three hours.)

```yaml
automation:
  - alias: "Feeding Reminder"
    trigger:
      platform: template
      value_template: >
        {{ has_value('sensor.everly_last_feeding_time')
           and (now() - states('sensor.everly_last_feeding_time') | as_datetime).total_seconds() > 10800 }}
    action:
      - service: notify.mobile_app
        data:
          title: "Feeding Time!"
          message: "It's been over 3 hours since Everly's last feeding"
```

### Medicine Logged Notification

The sensor's state is the medicine's name; the `time` attribute is when it was given, in UTC (`2026-10-30 11:00:00 +0000`).

```yaml
automation:
  - alias: "Medicine Reminder"
    trigger:
      platform: state
      entity_id: sensor.everly_last_medicine
    condition:
      - condition: template
        value_template: >
          {{ 'Vitamin D' in states('sensor.everly_last_medicine') }}
    action:
      - service: notify.mobile_app
        data:
          title: "Vitamin D Given"
          message: >
            Vitamin D logged at
            {{ strptime(state_attr('sensor.everly_last_medicine', 'time'), '%Y-%m-%d %H:%M:%S %z') | as_local }}
```

### Age-Based Sleep Monitoring

Monitor if your baby got enough sleep based on their age. Today's hours of sleep are in the `sleep_hours` attribute of the Daily Summary sensor; a small helper sensor makes them easy to use:

**Step 1: Create a template sensor for daily sleep (add to `configuration.yaml`):**

```yaml
template:
  - sensor:
      - name: "Everly Total Sleep Today"
        unique_id: everly_total_sleep_today
        unit_of_measurement: "hours"
        state: "{{ state_attr('sensor.everly_daily_summary', 'sleep_hours') | float(0) }}"
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
          age_days: "{{ state_attr('sensor.everly_info', 'age_days') | int(0) }}"
          age_months: "{{ (age_days / 30.44) | round(0, 'floor') | int }}"

          # Get today's total sleep hours
          sleep_hours: "{{ states('sensor.everly_total_sleep_today') | float(0) }}"

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
            Everly ({{ age_months }} months old) only slept {{ sleep_hours }} hours today.

            Recommended: {{ recommended_sleep }} hours total
            ({{ sleep_breakdown }})

            Deficit: {{ (recommended_sleep | float - sleep_hours) | round(1) }} hours
          data:
            priority: high
            tag: "baby_sleep_alert"
```

**Simpler Version (using estimated age):**

If you'd rather not work the age out from the Info sensor, you can set it by hand:

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
        value_template: "{{ states('sensor.everly_total_sleep_today') | float < 14 }}"
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
```

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

Alert if baby hasn't had a dirty diaper for too long (important for health monitoring).

The *Poopy Diapers* sensor (`sensor.everly_poopy_diapers`) counts dirty and mixed diapers over 7 days and carries `last_poopy_time` (text such as `2026-10-30 11:00:00 +0000`) and `hours_since_last_poopy` as attributes, so you do not have to look through the diaper history. The *No Poop* alert (`binary_sensor.everly_no_poop`) already does this with age-based limits (24, 48 or 72 hours) and can be used as a trigger on its own. The *Last Diaper* sensor's state is one of `wet`, `poopy`, `mixed` or `dry`.

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
          {% set hours = state_attr('sensor.everly_poopy_diapers', 'hours_since_last_poopy') %}
          {{ hours is number and hours > 24 }}
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ No Dirty Diaper Alert"
          message: >
            It's been over 24 hours since Everly's last dirty diaper
            ({{ state_attr('sensor.everly_poopy_diapers', 'last_poopy_time') }}).
            The last diaper was {{ states('sensor.everly_last_diaper') }}.
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
          last_diaper_time: "{{ state_attr('sensor.everly_last_diaper', 'time') }}"
          last_diaper_status: "{{ states('sensor.everly_last_diaper') }}"

          # Hours since the last dirty (poopy or mixed) diaper; 0 when there has never been one
          hours_since_dirty: "{{ state_attr('sensor.everly_poopy_diapers', 'hours_since_last_poopy') | float(0) }}"

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
            Everly ({{ baby_age_months }} months) hasn't had a dirty diaper in {{ hours_since_dirty | round(1) }} hours.

            Normal for {{ baby_age_months }} months: Within {{ max_hours_threshold }} hours

            Last diaper: {{ last_diaper_status }} at {{ last_diaper_time }}
          data:
            priority: high
            tag: "dirty_diaper_alert"
```

**Using the Hours Since Last Dirty Diaper:**

Simpler approach: at 6 PM, check whether the last dirty diaper was before midnight. The Poopy Diapers sensor counts the last 7 days, so it cannot tell "today" on its own:

```yaml
automation:
  - alias: "Daily Dirty Diaper Check"
    trigger:
      - platform: time
        at: "18:00:00"  # Check at 6 PM daily
    condition:
      - condition: template
        value_template: >
          {% set hours = state_attr('sensor.everly_poopy_diapers', 'hours_since_last_poopy') %}
          {{ hours is number and hours > now().hour + now().minute / 60 }}
    action:
      - service: notify.mobile_app
        data:
          title: "No Dirty Diaper Today"
          message: >
            Everly hasn't had a dirty diaper yet today. The last one was
            {{ state_attr('sensor.everly_poopy_diapers', 'hours_since_last_poopy') }} hours ago.
            Last diaper: {{ states('sensor.everly_last_diaper') }} at {{ state_attr('sensor.everly_last_diaper', 'time') }}
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
          {% set hours = state_attr('sensor.everly_poopy_diapers', 'hours_since_last_poopy') %}
          {{ hours is number and hours > 48 }}
    action:
      - service: notify.mobile_app
        data:
          title: "🚨 Constipation Warning"
          message: >
            URGENT: Everly hasn't had a dirty diaper in over 48 hours.

            Last dirty diaper: {{ state_attr('sensor.everly_poopy_diapers', 'last_poopy_time') }}

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
- **Records Not Reaching the App**: Look at *Settings > Repairs* (see [Repairs](#repairs)) and press **Sync Now**
- **A Button Did Nothing**: Pressing the same button again within 3 seconds is ignored on purpose
- **Sensors Not Appearing**: Restart Home Assistant after installation
- **Multi-Baby Issues**: Use the `list_babies` service to see all babies and their names
- **Google Home Not Working**: Ensure scenes are exposed in Google Assistant configuration and routines are set up correctly

- **Reporting a Problem**: Use **Download diagnostics** on the integration's page and attach the file to your issue. Your email, password and device ID are removed from it

## Privacy Notice

This integration stores your Baby Tracker credentials locally to sync with the Baby Tracker servers. No data is sent to third parties. All data is stored in a local SQLite database in your Home Assistant configuration directory. Baby and activity photos are kept in a private `baby_tracker` folder there and are only shown by the Photo image entities, which need a login.

## Database Location

The integration stores baby data in: `{config_directory}/baby_tracker.db`

This database is automatically synced with the Baby Tracker servers at the configured interval.

## Support

For issues and feature requests, please submit them through the GitHub repository's issue tracker.

## Credits

This integration provides a local interface to the Baby Tracker app (https://www.baby-tracker.com/). All trademarks belong to their respective owners. It is an independent project and is not affiliated with or endorsed by the makers of Baby Tracker.

The growth percentiles use the [WHO Child Growth Standards](https://www.who.int/tools/child-growth-standards/standards) (2006) for 0 to 24 months, as published by the US CDC. The tables are bundled unmodified in [`custom_components/baby_tracker/client/data`](custom_components/baby_tracker/client/data), which lists their sources.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Isaiah Nicolai. The bundled WHO growth data is not covered by this license: the CDC publishes its copy as US government work (public domain), and the underlying standards are the WHO's.
