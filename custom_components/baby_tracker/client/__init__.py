"""
Baby Tracker sync client.

A plain-Python client for the Baby Tracker sync service, with no Home
Assistant dependency. The Home Assistant integration uses it, and it can
also be installed on its own (``pip install -e .`` at the repo root), which
makes it importable as ``babytracker_client`` and adds the ``babytracker``
command:

    from babytracker_client import BabyTracker

    tracker = BabyTracker(db_path="babytracker.db", time_zone="America/Chicago")
    tracker.authenticate(email, password, device_uuid)
    tracker.sync()
    for baby in tracker.get_all_babies():
        print(baby.name, tracker.get_last_diaper(baby.object_id))

Each client registers as its own device on the sync server, identified by
the device UUID passed to ``authenticate``. Reuse the same UUID and database
path between runs.
"""

from .api import AccountResetError, AuthenticationError, BabyTrackerAPI
from .core import BabyTracker
from .database import BabyTrackerLocalDatabase
from .models import Baby

__version__ = "0.4.0"

__all__ = [
    "AccountResetError",
    "AuthenticationError",
    "Baby",
    "BabyTracker",
    "BabyTrackerAPI",
    "BabyTrackerLocalDatabase",
]
