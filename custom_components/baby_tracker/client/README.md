# babytracker-client

A plain-Python client and command line for the sync service behind the
[Baby Tracker](https://nighp.com/babytracker/) app, with no Home Assistant
dependency. It is the library the
[Baby Tracker for Home Assistant](https://github.com/isaiahnicolai/baby-tracker-home-assistant)
integration is built on, packaged on its own so that other scripts and
projects can use it. It is installed from GitHub rather than PyPI.

> **Unofficial.** An independent project, not affiliated with or endorsed by
> the makers of Baby Tracker. It speaks the same protocol the phone app uses,
> worked out from how the app talks to its server. Keep the app's own backups,
> and read what it does before pointing it at your account.

## Install

```bash
# from the repository, at a release tag (or @main for the latest code)
pip install "git+https://github.com/isaiahnicolai/baby-tracker-home-assistant@v1.0.0"

# or the wheel attached to a release, no git needed
pip install https://github.com/isaiahnicolai/baby-tracker-home-assistant/releases/download/v1.0.0/babytracker_client-1.0.0-py3-none-any.whl
```

In a `requirements.txt`:

```
babytracker-client @ git+https://github.com/isaiahnicolai/baby-tracker-home-assistant@v1.0.0
```

Add `[photos]` to pull in Pillow and be able to attach photos to entries
(`pip install "babytracker-client[photos] @ git+https://github.com/isaiahnicolai/baby-tracker-home-assistant@v1.0.0"`).
It needs Python 3.11 or newer and otherwise depends only on `requests` and
`python-dateutil`.

## Use it from Python

```python
from babytracker_client import BabyTracker

tracker = BabyTracker(db_path="babytracker.db", time_zone="America/Chicago")
tracker.authenticate("you@example.com", "password", device_uuid="<a UUID you keep for this script>")
tracker.sync()

for baby in tracker.get_all_babies():
    print(baby.name, tracker.get_last_diaper(baby.object_id))
    print(tracker.get_insights(baby.object_id)["next_feed"])

ava = tracker.get_baby_by_name("Ava")
tracker.add_diaper(ava.object_id)            # a wet diaper now; poo=True for a dirty one
```

Each client registers as its own device on the account, identified by the
`device_uuid` you pass to `authenticate`. Keep the same UUID and database
path between runs: the database is a local copy of the account, `sync`
downloads what changed and uploads what you wrote, and the first sync replays
the account's history (a few seconds per few thousand records).

`BabyTracker` is the whole API. The main groups of methods:

- **Account**: `authenticate`, `sync`, `force_resync`, `pending_upload_count`,
  `get_all_babies`, `get_baby_by_name`, `download_baby_picture`.
- **Reading**: `get_last_<kind>` and `get_<kind>_records` for every record
  type (`get_last_diaper`, `get_last_feeding`, `get_last_sleep`,
  `is_currently_sleeping`, `get_growth_records`...), `get_recent_records`,
  `get_daily_summary`, `get_feeding_summary`, `get_sleep_analysis`,
  `get_events_between`, `get_pictures`, `get_latest_picture`.
- **Insights**: `get_insights` (corrected age, next feed, 24 hour intake,
  diaper adequacy, WHO growth percentiles, next sleep), `get_next_breast`,
  `get_next_medicine_dose`, `get_upcoming_milestones`,
  `get_upcoming_vaccines`, `get_pumped_milk_inventory`.
- **Writing**: `add_diaper`, `add_nursing`, `add_formula`, `add_pumped`,
  `add_other_feed`, `log_sleep_event`, `log_pump`, `log_growth`,
  `add_temperature`, `add_medicine`, `log_bath`, `add_activity`,
  `log_milestone`, `log_vaccine`, `log_doctor_visit`, `add_joy`,
  `attach_photo`, `delete_record`, `undo_last`, and `create_medicine` and
  `create_food` for the app's medicine and solids lists.

Every write is stored locally first and uploaded by `sync` (a write syncs by
itself when the server is reachable), so a script keeps working offline and
sends what it logged on the next sync. Each method's docstring describes its
arguments. Errors are `AuthenticationError` (wrong password or expired
session) and `AccountResetError` (the account was reset on the server;
`force_resync` rebuilds the local copy).

## Use it from the command line

```bash
export BABYTRACKER_EMAIL=you@example.com   # the password is asked for, or read from BABYTRACKER_PASSWORD
babytracker babies
babytracker last diaper --baby Ava
babytracker add-diaper wet --baby Ava
babytracker add-bottle --baby Ava --amount 4 --unit oz --type formula
babytracker add-nursing --baby Ava --left 10 --right 8
babytracker add-joy --baby Ava --note "First smile" --photo smile.jpg
babytracker attach-photo Diaper <object-id> bath.png
babytracker insights --baby Ava
babytracker next
babytracker calendar --baby Ava --days 2
babytracker recent --baby Ava --limit 10
babytracker delete Diaper <object-id> --yes
babytracker undo --baby Ava --yes
babytracker inventory
babytracker create-medicine Tylenol --amount 2.5 --unit ml --interval 6
babytracker create-food Banana
babytracker devices
babytracker raw <device-uuid> --since 100
```

Every command prints JSON. `--baby` is a baby's name and can be left out when
the account has only one baby; `--offline` skips the sync that normally runs
first. The CLI keeps its device ID and local database in `~/.babytracker`
(`--state-dir` changes that).

Run `babytracker` with no command for an **interactive shell** (built on [cmd2](https://cmd2.readthedocs.io/)): it signs in and syncs once, then takes the same commands with tab completion for commands, options and baby names, `help` and `help <command>`, a history kept between sessions (up and down arrows, `history`), and `set baby Ava` so `--baby` can be left out. In the shell the commands are spelled with underscores (`add_diaper wet`), and the hyphenated spellings work too.

```
$ babytracker
Baby Tracker shell. Babies: Ava, Noah.
Type help for the commands, help <command> for its options, set baby <name> to pick a baby, quit to leave.
babytracker> set baby Noah
babytracker> add_diaper wet
babytracker> last feeding
babytracker> quit
```

## Links

- [Repository, issues and the Home Assistant integration](https://github.com/isaiahnicolai/baby-tracker-home-assistant)
- [Changelog](https://github.com/isaiahnicolai/baby-tracker-home-assistant/blob/main/CHANGELOG.md)
- [Baby Tracker on Google Play](https://play.google.com/store/apps/details?id=com.nighp.babytracker_android) and the [App Store](https://apps.apple.com/us/app/baby-tracker-newborn-log/id779656557)

MIT licensed.
