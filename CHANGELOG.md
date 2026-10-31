# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/) (while it is below 1.0, a minor
version may contain breaking changes).

## [0.3.0] - 2026-10-31

This release makes the entities usable in dashboards, automations and
voice assistants, and adds insights, controls and a household view. **It
contains breaking changes**: read [Breaking changes](#breaking-changes-in-030)
before upgrading.

### Breaking changes in 0.3.0

- **Enum states are lowercase.** Sensors that reported a label now report a
  lowercase value: the last diaper is `wet`, `poopy`, `mixed` or `dry` (it
  was `Wet`, `Poopy`, ...). Update any `is_state(...)`, `states(...)` or
  template trigger that compared against the old capitalised text.
- **Numeric states replace text.** Durations are minutes, volumes are mL,
  weights are kg, lengths are cm and temperatures use the entry's unit, all
  as numbers with a unit and device class. Timestamps are real timestamps
  (aware datetimes) rather than text. Templates that parsed the old text
  to get a number can use the number directly, and `as_timestamp(states(...))`
  works on the new timestamp sensors. Attributes that carry a time are
  still text, in the form `2026-10-30 11:00:00 +0000`.
- **The Bottle oz sensor is gone.** Bottle oz and Bottle ml are one
  **Bottle Volume** sensor (the ml sensor's unique ID is kept). Its state is
  a number in mL, shown in oz when the entry's unit system is imperial; the
  oz totals are still available as attributes. The old `Bottle oz` registry
  entries are removed on upgrade.
- **Photos moved out of `www/`.** Baby and activity photos are now kept in a
  private `<config>/baby_tracker` folder instead of `www/baby_tracker`,
  where `/local/` served them to anyone without a login. The `/local/...`
  URL and the Info sensor's entity picture are gone; each baby has a
  **Photo** image entity instead. A repair issue and a log warning tell you
  when photos from an older version are still under `www/baby_tracker`, so
  you can delete them.
- **Config entry version 2.** Each entry now stores its own `device_uuid`
  (this used to be done during setup; it is now an `async_migrate_entry`
  step). The migration runs by itself, but an entry that has been migrated
  cannot be opened by 0.2.x, so back up before upgrading if you might go
  back.
- **Services take a time and follow the unit setting.** Every service that
  adds or logs a record accepts an optional `time`. Temperature, growth and
  pump units default to the entry's unit system instead of fixed values.
- **New installs no longer enable the fixed-size bottle and Tylenol
  buttons.** They are disabled by default; use the new Add Bottle and Give
  Medicine buttons with the Bottle Size and Medicine controls instead.
  Existing installs keep them.

### Added

- **Insights per baby**: corrected age, next feed prediction (with day and
  night intervals and wake-by guidance), 24 hour intake against the
  expected range, wet and dirty diaper adequacy, WHO growth percentiles for
  weight, length and head circumference, and weight gain. They appear as
  sensors (Next Feed, Feed Interval, Intake 24h, Intake Status, Diaper
  Adequacy, Weight/Length/Head Percentile, Weight Gain, Corrected Age) and
  as alerts (Intake Low, Feed Due, Wake To Feed).
- **Household view**: on the Baby Tracker device, Next Feed Due, Next Feed
  Baby (who is due first), Last Fed Baby, Babies Asleep, Feeds Today,
  Pumped Milk Inventory and Pending Uploads.
- **More per-baby sensors**: Which Breast Next, Next Medicine Dose,
  Upcoming Milestones and Upcoming Vaccines, Last Activity, and Last
  Feeding Time, Last Diaper Time and Last Sleep Time timestamps.
- **A calendar and an Activity event entity per baby.** The event entity
  fires where the bus events are, so automations can trigger on
  `event.*_activity`.
- **Controls**: Bottle Size and Medicine Amount numbers, Bottle Type and
  Medicine selects (restored after a restart), and Tummy Time Minutes. The
  Add Bottle, Give Medicine and Log Tummy Time buttons use them.
- **Nursing timer**: Start Nursing Left, Start Nursing Right and End
  Nursing buttons with a Nursing binary sensor. The record is written when
  you press End.
- **New services**: `log_activity` and `add_solids`.
- **Blueprints** for feed due, wake to feed and a daily intake summary.
- **Alert options** in the options flow: feeding-overdue hours, minimum wet
  diapers, night hours and fever temperature.
- **Repairs** for photos left under `www/`, records stuck unsent for
  several refreshes, and an account that was reset (Force Resync needed).
- **Diagnostics** (credentials redacted): babies, last sync, pending
  uploads, insights, controls and running nursing timers.
- **Image entities** for baby photos.
- **Entity translations and `icons.json`**; services and exceptions are
  documented in `strings.json`.
- **Command line**: `babytracker insights`, `next`, `calendar`,
  `inventory`, `add-bottle` and `add-nursing` join the existing commands.
- **Client API**: `get_insights`, `get_events_between`,
  `get_pumped_milk_inventory`, `get_next_breast`, `get_next_medicine_dose`,
  `get_upcoming_milestones`, `get_upcoming_vaccines`,
  `pending_upload_count`, `add_other_feed`, `add_activity` and
  `get_last_activity`.
- **Sync protocol completed**: activity pictures are downloaded and kept
  (with a retry limit), pictures can be uploaded, `logout` ends the server
  session, and the app's conflict, relive and repeated-delete messages are
  sent back as the Android app does.
- MIT license.

### Changed

- Sensors have device classes, state classes and units, so they work with
  long-term statistics and the standard history graphs. Sync Now and Force Resync
  are config entities; Info and Pump Summary are diagnostic.
- Temperature, weight, length and volume sensors show the unit chosen for
  the entry rather than Home Assistant's own unit system.
- Buttons ignore a repeat press within 3 seconds, and writes ask for a
  debounced refresh, so a double tap does not log a record twice.
- Feed Due, Wake To Feed, Feeding Overdue, Night Mode and the feeding
  timers re-evaluate every minute instead of waiting for the next refresh.
- Every database connection waits up to 10 seconds for a lock and uses
  write-ahead logging, and one lock covers syncs and writes, so a refresh
  and a service call never interleave.
- `add_activity` reuses the account's activity description of that name
  instead of creating a new one each time.
- `dismiss_alert` accepts the `intake_low`, `feed_due` and `wake_to_feed`
  alerts. `force_resync` is documented in `services.yaml`.
- `manifest.json` declares `integration_type: hub`.

### Fixed

- Growth and other-activity reads are filtered by baby; the newest
  measurement of any baby used to show for every baby.
- Time zones: "today", day buckets and night sleep use Home Assistant's
  time zone rather than the host's or UTC.
- Temperature readings carry their unit, and the fever alert compares the
  Fahrenheit value.
- Joy and Journal records are merged, and `NursingSession` is read as
  Nursing.
- Sleep clamps a negative duration; growth stores measures and scale flags
  as the Android app does.
- Nursing durations are minutes, not seconds.
- The 24 hour intake total is rounded so floating point noise cannot push
  an exactly-on-the-bound total over it.
- A failed Force Resync no longer leaves the integration signed out until a
  restart; syncing signs in again by itself.
- An upload failure no longer makes every entity unavailable.
- A sleep ended within its first minute is ended (duration at least 1 min),
  and old never-ended sleeps are not shown as in progress.
- Records logged in Home Assistant are no longer re-merged on the next
  sync, so a record deleted on the phone cannot come back.
- Pump totals are summed in millilitres, exclude inventory adjustments and
  count per-side amounts; a head-only growth row no longer blanks Weight
  and Length.
- The nursing timer survives reloads and restarts; a failed button press can
  be retried at once.
- Fever ignores readings older than 24 hours; Fever, Low Wet Diapers and
  Long Sleep re-evaluate every minute.
- A transient photo download failure is retried instead of remembered.
- Only one account can be added (`single_config_entry`); the registry
  migration cannot capture account-level entities.
- A sleep left running (duration 0) for more than 24 hours is no longer
  reported as in progress by the last-sleep reads, `is_currently_sleeping`
  or the Long Sleep alert; it is still the last sleep, with `is_sleeping`
  false. This is the same window that stops Wake Up from ending it.

## [0.2.0] - 2026-10-30

### Added

- **Multiple babies.** Each baby gets its own device and entities, keyed by
  the baby's ID, so renaming a baby in the app keeps its entities and
  history. Services take a Baby device picker as well as `baby_name`.
  The integration reloads when babies are added or renamed.
- **Device identity.** Each install registers as its own device in the app,
  with a device ID that survives a rebuild of the local database.
- **Options and reauth flows.** Update interval and units can be changed
  after setup, and a rejected password prompts for a new one instead of
  failing every refresh.
- **Standalone client and CLI.** The sync client lives in
  `custom_components/baby_tracker/client/` with no Home Assistant
  dependency and installs as `babytracker_client`. The `babytracker`
  command has `babies`, `sync`, `devices`, `last`, `add-diaper`, `raw` and
  `logout`.
- **HACS layout**: `custom_components/baby_tracker/`, `hacs.json`,
  documentation and issue-tracker links.
- Tests for the client (against the Android app's real schema, with the
  server faked) and for the integration, GitHub Actions for both, hassfest,
  and a dev container with `docker compose` and `scripts/bootstrap`.

### Changed

- **The sync engine was rebuilt on the Android app's rules.** Downloads are
  paged and resumable, failures are retried and then skipped with a log
  entry, updates only overwrite older rows, name clashes and conflicts are
  resolved as the app does, and records you add are saved locally, queued
  and uploaded in order, so offline taps are sent on the next sync.
- Records are stored with a table-driven registry that matches the app, and
  pump, growth, milestone and vaccine records now sync.
- Entity names come from the baby's device, so new installs get
  `button.everly_add_wet_diaper` rather than a doubled
  `button.baby_tracker_everly_everly_add_wet_diaper`. Existing entity IDs
  are unchanged.
- The YAML configuration path was removed; set up the integration from the
  UI.

[0.3.0]: https://github.com/isaiahnicolai/baby-tracker-home-assistant/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/isaiahnicolai/baby-tracker-home-assistant/releases/tag/v0.2.0
