"""
Baby Tracker sync client.

A plain-Python client for the Baby Tracker sync service, with no Home
Assistant dependency. The Home Assistant integration uses it, and it is
also packaged on its own (``pip install git+https://github.com/isaiahnicolai/baby-tracker-home-assistant``), which
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

__version__ = "1.0.3"

__all__ = [
    "AccountResetError",
    "AuthenticationError",
    "Baby",
    "BabyTracker",
    "BabyTrackerAPI",
    "BabyTrackerLocalDatabase",
]
