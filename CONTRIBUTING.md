# Contributing

Thanks for taking a look. Bug reports, small fixes and new features are all
welcome, and you don't need to ask before opening a pull request. This page is
a map of the code and how to run it, not a set of rules. The user
documentation is in [readme.md](readme.md).

## How the code fits together

There are two layers:

- **`custom_components/baby_tracker/client/`** is a plain-Python client for
  the Baby Tracker sync service. It keeps a local SQLite copy of the account in
  the Android app's own schema and syncs it the way the app does. It has no
  Home Assistant imports, which is what lets it ship on its own as
  `babytracker_client` with the `babytracker` command.
- **`custom_components/baby_tracker/`** is the Home Assistant integration on
  top of it: the coordinator in `__init__.py`, one file per entity platform,
  `services.py` and `services.yaml`, the Assist intents in `intent.py`, and the
  strings and icons.

Inside the client, `core.py` is the public `BabyTracker` API, `api.py` talks to
the server, `database.py` holds the read queries, `records.py` maps every
record type between the wire format and the tables, `transaction.py` applies
synced changes, `insights.py` has the predictions and percentiles, and
`cli.py` is the command line.

The decompiled Android app was the reference for the protocol and the record
formats. When something about the wire format looks odd, it is usually
copying what the app does.

## Running it

The quickest way to a working setup is the dev container: open the repository
in VS Code and choose **Reopen in Container**. `scripts/develop` then starts
Home Assistant on http://localhost:8123 with the integration loaded from the
repo.

Without VS Code, Docker Compose runs the same Home Assistant:

```bash
cp .env.example .env              # your Baby Tracker login (.env is git-ignored)
docker compose up -d
python scripts/bootstrap          # finishes onboarding (user dev / dev) and adds the integration
docker compose restart            # after changing integration code
```

The dev instance joins your real account as a new device, like any other
install, so a test account is a good idea if you have one.

## Tests

- **Client tests** (`tests/`) run anywhere, Windows included, against the
  app's real schema with the server faked:
  `pip install -e . pytest tzdata && pytest tests --ignore=tests/ha -q`.
- **Integration tests** (`tests/ha`) need the Home Assistant test harness and
  run on Linux and macOS (the dev container or WSL):
  `pip install -r requirements_test.txt -e . && scripts/test -q`.

If you can't run the integration tests, open the pull request anyway: CI runs
both suites, hassfest and HACS validation. `scripts/lint` runs ruff with the
settings in `.ruff.toml`.

## Adding something new

There is no fixed recipe, but a new kind of record usually touches these
places, from the bottom up:

1. `client/records.py`: map the record's fields to its table (the Android
   app's `putValues` for that class is the reference).
2. `client/api.py` and `client/core.py`: a `post_<kind>` that builds the wire
   record, and a public `add_<kind>` or `get_last_<kind>`.
3. The integration: load it in the coordinator, then add a sensor, a service
   (with `services.yaml` and `strings.json` entries) or whatever fits.
4. A test or two, and a line in the readme and `CHANGELOG.md`.

Neighbouring code is the best guide: most things have a close cousin already.
A few things are worth keeping in mind:

- Keep Home Assistant imports out of `client/`.
- Entity and unique IDs are what people's dashboards and automations point
  at, so renaming one needs a registry migration.
- Files keep their existing line endings.

## Releases

For maintainers: the version lives in `manifest.json`, `pyproject.toml`,
`client/__init__.py` and `const.py`. Publishing a GitHub release runs
`.github/workflows/release.yml`, which checks the tag against the version and
attaches `baby_tracker.zip` (what HACS installs) and the client wheel. When
bumping Home Assistant, change `requirements.txt`, the harness pin in
`requirements_test.txt` and the image tag in `docker-compose.yml` together.

The integration's icon and logo are in `custom_components/baby_tracker/brand/`,
which Home Assistant 2026.3 and later show on the integration page.
