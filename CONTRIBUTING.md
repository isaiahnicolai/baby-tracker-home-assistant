# Contributing

Thanks for helping. This file covers how the repository is laid out, how to run
it and its tests, and how to add support for a new kind of record. User
documentation is in [readme.md](readme.md); what changed between releases is in
[CHANGELOG.md](CHANGELOG.md).

## Layout

There are two layers, and the split matters:

```
custom_components/baby_tracker/      the Home Assistant integration (what HACS installs)
    __init__.py                      setup, migration and the DataUpdateCoordinator
    config_flow.py, const.py         config/options/reauth flows, constants
    sensor.py, binary_sensor.py,     entities (one platform per file)
    button.py, number.py, select.py,
    image.py, calendar.py, event.py
    services.py, services.yaml       service calls
    diagnostics.py, strings.json,    diagnostics, English strings, icons
    icons.json, translations/
    client/                          the sync client: no Home Assistant imports
        core.py                      BabyTracker: the public API (get_*, add_*, log_*, sync)
        api.py                       the Baby Tracker web API: login, sync, post_* records
        database.py                  read queries over the local SQLite database
        records.py                   wire format -> table mapping for every record type
        transaction.py               applies downloaded/queued transactions to the database
        insights.py                  pure functions: next feed, intake, percentiles
        cli.py                       the `babytracker` command
        data/                        WHO growth tables (see data/README.md)
blueprints/                          automation blueprints
tests/                               client tests (run anywhere)
tests/ha/                            integration tests (need Home Assistant)
scripts/                             dev container and dev Home Assistant helpers
```

The client keeps a local SQLite copy of your account in the Android app's own
schema and syncs it the way the app does. Anything in `client/` must stay free
of Home Assistant imports: `pyproject.toml` publishes that folder on its own as
`babytracker_client`, and the CLI and the tests rely on it. The integration
imports the client as `custom_components.baby_tracker.client`; everything
Home Assistant specific (entities, units, translations) belongs outside it.

## Setting up

The easiest way is the dev container: open the repository in VS Code and choose
**Reopen in Container** (needs Docker). It runs `scripts/setup`, which installs
the pinned Home Assistant, the test harness and the client package.

| Script | What it does |
| --- | --- |
| `scripts/setup` | installs `requirements.txt` (Home Assistant, test harness, ruff, the client) |
| `scripts/develop` | runs Home Assistant on http://localhost:8123 with the integration loaded from the repo; data lives in `config/` (git-ignored apart from `configuration.yaml`) |
| `scripts/test` | runs pytest over `tests` (pass extra arguments, for example `scripts/test -k diaper`) |
| `scripts/lint` | `ruff format` and `ruff check --fix` |
| `scripts/bootstrap` | finishes onboarding on a fresh dev Home Assistant (user `dev` / `dev`) and adds Baby Tracker using the account in `.env` |

Without VS Code, `docker-compose.yml` runs the same pinned Home Assistant image
with `config/` and the integration mounted from the repo:

```bash
cp .env.example .env              # fill in your Baby Tracker login (.env is git-ignored)
docker compose up -d
python scripts/bootstrap          # onboarding + adds the integration
docker compose restart            # after changing integration code
```

Open http://localhost:8123. The dev instance joins your real account as a new
device, like any other Home Assistant install, so use a test account if you
can.

## Tests

There are two suites.

**Client tests** (`tests/`, everything except `tests/ha`) exercise the sync
client against the Android app's real schema (`tests/fixtures/app_schema.sql`,
no data) with the sync server faked (`tests/conftest.py`). They need only
pytest and work on Windows, macOS and Linux:

```bash
pip install -e . pytest tzdata
pytest tests --ignore=tests/ha -q
```

**Integration tests** (`tests/ha`) start an in-memory Home Assistant with
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).
They run on Linux and macOS only: use the dev container, WSL, or let CI run them.

```bash
pip install -r requirements_test.txt -e .
scripts/test -q              # runs both suites
```

Each release of the test harness matches one Home Assistant release. When you
bump Home Assistant, change `homeassistant` in `requirements.txt`, the
harness pin in `requirements_test.txt` and the image tag in
`docker-compose.yml` together.

GitHub Actions runs the client tests on Python 3.11 to 3.14, the integration
tests, hassfest and (for public repositories) HACS validation. Run
`scripts/lint` before you push; the ruff settings are in `.ruff.toml`.

## Versions and releases

The version appears in four places that must agree: `manifest.json`,
`pyproject.toml`, `client/__init__.py` (`__version__`) and `const.py`
(`VERSION`). Add an entry to `CHANGELOG.md` for every user-visible change.
Publishing a GitHub release runs `.github/workflows/release.yml`, which zips
`custom_components/baby_tracker` into `baby_tracker.zip` and attaches it to the
release, which is what HACS installs.

## Adding a record type

Say the app gains a record type, or you want a new kind of log. Work from the
bottom up.

1. **Store it: `client/records.py`.** Add a `RecordType` to `RECORD_TYPES`
   mapping the transaction's JSON to the table's columns. Copy the Android
   app's `putValues` for that class, and say so in a comment where the
   mapping is not obvious. `baby=True` if it carries a `BabyID`,
   `activity=False` for a plain selection, and `embedded` for nested
   selections that should be stored if missing. Add an entry to `ALIASES`
   for alternative wire names, and to `BABY_REFERENCE_TABLES` if the table
   has a `BabyID` (baby merges re-point it). The sync engine then merges
   downloaded records of this type with no further code.
2. **Read it: `client/database.py`.** Add a `get_last_<kind>_direct` (and any
   summary) query to `BabyTrackerLocalDatabase`, following a neighbouring
   one such as `get_last_bath_direct`. Times are stored as Unix seconds, and "today"
   and day buckets use the time zone the database was created with.
3. **Write it: `client/api.py`.** Add `post_<kind>` to the API class. It
   builds the wire JSON the apps send and calls `_post_record`, which saves
   the record locally, queues it in `TransactionLog` and uploads it, leaving
   it queued when the server is unreachable.
4. **Expose it: `client/core.py`.** Add a `get_last_<kind>` that opens the
   database, and an `add_<kind>` or `log_<kind>` that checks
   `is_authenticated`, defaults the time to now and calls the API. Methods
   named `add_*` and `log_*` are wrapped in the tracker's lock
   automatically. Add the kind to `LAST` in `client/cli.py` if it makes
   sense on the command line.
5. **Surface it in Home Assistant.** Load the data in the coordinator's
   `_async_update_data` (`__init__.py`), add a sensor class in `sensor.py`
   (and to the list at the bottom), a service in `services.py` with a schema,
   a description in `services.yaml` and names in `strings.json`, and an icon
   in `icons.json`. Every entity needs a `translation_key` with its English
   name in `strings.json`. Add the English text to `translations/en.json` too.
6. **Test it.** A client test in `tests/` using the `tracker`, `server` and
   `app_db` fixtures (look at `tests/test_writes.py` and
   `tests/test_records.py`), and, if it adds entities or services, a test in
   `tests/ha/test_integration.py`.
7. **Document it:** the readme's sensor and service tables and a CHANGELOG
   line.

## Code style

- Python 3.11 or newer for the client; the integration follows the Python of
  the pinned Home Assistant release. Line length is 120.
- Keep files' existing line endings; do not reformat files you are not
  otherwise changing.
- Keep Home Assistant imports out of `client/`.
- Entity IDs and unique IDs are part of the public interface: do not rename
  them without a migration.

## Commit messages and pull requests

Write the subject in the imperative and explain why in the body. In the pull
request, say what you changed and how you tested it. If you could not run the
`tests/ha` suite locally, say so and let CI run it.
