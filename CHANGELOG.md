# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-01

The first release. It syncs a Baby Tracker account with Home Assistant in
both directions, for one or more babies, using the same protocol the phone
app uses, and was tested against a real account with two babies.

### Syncing

- Signs in with your Baby Tracker account and joins it as a new device. The
  add-integration dialog only checks the password; joining the account and
  importing its history (about 3,000 records in 14 seconds) run in the
  background with a notification, the babies' entities appear when it is
  done, and an import interrupted by a restart picks up where it left off.
- Downloads are paged and resumable. Failures are retried and then skipped
  with a log entry, updates only overwrite older rows, and name clashes,
  conflicts, relives and repeated deletes are resolved as the Android app
  does.
- Records you add in Home Assistant are saved locally, queued and uploaded
  in order, so entries logged while the server is unreachable are sent on
  the next sync. A **Pending Uploads** sensor and a repair tell you when
  something has stayed unsent.
- Every record type the app syncs is supported: diapers, nursing, bottles
  (formula and pumped), solids and other feeds, sleep, pumping, growth,
  temperature, medicine, baths, tummy time and other activities,
  milestones, vaccines, joys and journal entries, doctor visits, and the
  app's selection lists (feed, sleep and sick descriptions, sleep and
  activity locations, allergen sources, doctors, medicines).
- Baby photos, their landscape versions and the pictures attached to
  entries are downloaded and kept in a private `baby_tracker` folder in your
  configuration directory, served only through image entities.
- One account per Home Assistant; a rejected password prompts for a new one
  instead of failing every refresh. Force Resync rebuilds the local copy.

### Babies and entities

- Each baby is its own device with its own entities, keyed by the baby's ID,
  so renaming a baby in the app keeps its entities and history. The
  integration reloads when babies are added or renamed.
- **Sensors** for the last feeding, diaper, sleep, pump, bath, medicine,
  temperature, growth measurement, milestone, vaccine, doctor visit and
  activity, with timestamps; daily counts and totals (feeds, diapers, bottle
  volume, nursing minutes, sleep, pumped milk); which breast is next; the
  next medicine dose; upcoming milestones and vaccines; **Recent Entries**
  with the last ten records and their IDs; and an Info sensor.
- **Alerts** (binary sensors, re-evaluated every minute): Is Sleeping, Night
  Mode, Feeding Overdue, Feed Due, Wake To Feed, Intake Low, Low Wet Diapers,
  Fever, Long Sleep, Sleep Due and Nap Running Long. Their thresholds are
  options, and `dismiss_alert` silences one.
- **Insights** calculated by this project from your data: corrected age,
  next feed prediction with day and night intervals, 24 hour intake against
  the expected range, wet and dirty diaper adequacy, WHO growth percentiles
  and weight gain, and a next nap prediction (Next Sleep, Expected Wake and
  Wake Window) from the baby's own wake windows within the typical range for
  their age.
- **Household view** on the Baby Tracker device: Next Feed Due, Next Feed
  Baby, Last Fed Baby, Babies Asleep, Feeds Today, Pumped Milk Inventory and
  Pending Uploads.
- **Controls**: Add Wet/Dirty/Mixed Diaper, Add Bottle with Bottle Size and
  Bottle Type, Give Medicine with Medicine and Medicine Amount (the amount
  follows the medicine's usual dose), Log Tummy Time, Log Bath, Start and
  End Sleep, a nursing timer (Start Nursing Left/Right, End Nursing, a
  Nursing binary sensor) and Undo Last Entry. Buttons ignore a repeat press
  within 3 seconds.
- **Photo**, **Photo Landscape** and **Latest Photo** image entities, a
  **calendar** per baby, and an **Activity event** entity that fires for
  every new record, photo and undo (with matching bus events).
- States are numbers with units, device classes and state classes, so they
  work with long-term statistics and history graphs; enum states are
  lowercase; units follow the entry's unit setting. Entity translations,
  icons and diagnostics (credentials redacted) are included.

### Services

- Logging services for every record type (diapers, bottles, nursing, solids,
  sleep, pumping, growth, temperature, medicine, bath, tummy time and other
  activities, joys), timers (`start_sleep`/`end_sleep`,
  `start_nursing`/`end_nursing`), `undo_last`, `delete_record`,
  `dismiss_alert`, `sync_now` and `force_resync`. Every logging service
  accepts an optional `time`, and the baby is chosen with a device picker or
  `baby_name`.
- **Photos from Home Assistant.** `log_joy` logs a joy with an optional
  photo, and `attach_photo` adds a photo to an existing entry, from a file in
  the `baby_tracker`, `www` or `media` folder or from a camera or image
  entity snapshot. They appear on the phone like photos taken in the app.
- **Undo and delete.** `undo_last` removes a baby's newest record and
  `delete_record` one by type and ID; the deletion reaches the phone on its
  next sync.
- **New medicines and foods.** `create_medicine` (name, usual dose, unit,
  hours between doses, prescription) and `create_food` add an entry to the
  app's medicine and solids lists; an existing name is left alone. The new
  medicine appears in the Medicine select. `log_medicine` and `add_solids`
  take `create: true` to create an unknown name instead of failing.

### Sleep from another entity

- In the options, each baby can take their sleep from any Home Assistant
  entity (a Snoo or Owlet state sensor, a bed sensor, an `input_boolean`):
  you choose the states that mean asleep, how long a wake must last to end
  the sleep and the shortest sleep to log. The start is back-dated to when
  the entity went to sleep, the end is dated when it woke, and a restart
  mid-sleep loses nothing. A **Sleep Source** diagnostic sensor shows what
  the integration thinks.

### Quiet mode

- A baby counts as tracked for an activity (feeds, diapers, sleep, pumping,
  medicine, growth, temperature) when something in it was logged in the last
  14 days. For a group that is not tracked, its alerts stay off, its
  predictions read unknown with `reason: not_tracked`, the household
  sensors skip that baby and Assist says so. The per-baby options step can
  override the detection.

### Voice control (Assist)

- Log diapers, bottles, sleeps, nursing sessions and temperatures by voice,
  and ask when a baby last ate, when the next feed or nap is, how much they
  have had today, when they will wake and whether they are asleep. Home
  Assistant only reads sentence files from `<config>/custom_sentences/`, so
  a repair offers to write the English file there with your babies' names.
  The intents are also available to AI conversation agents as tools.

### Blueprints and repairs

- Blueprints for feed due, wake to feed, sleep due, new photo and a daily
  intake summary.
- Repairs for the Assist sentence file, records stuck unsent and an
  account that was reset.

### Client library and command line

- The sync client lives in `custom_components/baby_tracker/client/`, has no
  Home Assistant dependency and is packaged as `babytracker-client` (with a
  `photos` extra for Pillow), installable with pip from this repository or
  the wheel attached to each release, so other projects can use it too. The `babytracker` command has `babies`,
  `sync`, `devices`, `last`, `recent`, `next`, `insights`, `calendar`,
  `inventory`, `add-diaper`, `add-bottle`, `add-nursing`, `add-joy`,
  `attach-photo`, `create-medicine`, `create-food`, `delete`, `undo`, `raw`
  and `logout`, and with no command opens an interactive shell (cmd2) with
  the same commands, tab completion for commands, options and baby names,
  a persistent history and `set baby` to pick a default baby.

### Project

- HACS layout with a zipped release, Home Assistant 2024.12 or newer, brand
  images on the integration page (2026.3 and newer), tests for the client
  and the integration with GitHub Actions and hassfest, a dev container with
  `docker compose` and `scripts/bootstrap`, and an MIT license.

[1.0.0]: https://github.com/isaiahnicolai/baby-tracker-home-assistant/releases/tag/v1.0.0
