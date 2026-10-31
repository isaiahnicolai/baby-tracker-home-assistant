"""
Baby Tracker wrapper for Home Assistant.
This module re-exports the BabyTracker class and imports needed for Home Assistant.
"""

import os
import logging
from datetime import datetime, timezone

# Import the necessary components from the original implementation
from .core import BabyTracker
from .api import BabyTrackerAPI
from .database import BabyTrackerLocalDatabase
from .models import Baby

# Set version
__version__ = "0.1.0"

_LOGGER = logging.getLogger(__name__)
