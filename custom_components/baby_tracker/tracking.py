"""Which activities each baby is still logged for, so the rest can go quiet."""
from datetime import UTC, datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import CONF_TRACKING, TRACKING_AUTO, TRACKING_GROUPS, TRACKING_WINDOW_DAYS

# Where each group's newest record sits in a baby's data (the first listed that has a time wins)
GROUP_RECORDS = {
    "feeds": ("last_feeding", "last_feed_time", "last_nursing"),
    "diapers": ("last_diaper",),
    "sleep": ("last_sleep",),
    "pumping": ("last_pump",),
    "medicine": ("last_medicine",),
    "growth": ("last_growth",),
    "temperature": ("last_temperature",),
}


def _moment(value):
    """An aware datetime from a client time string (taken as UTC when it has no zone), else None."""
    if not value:
        return None
    try:
        moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except (TypeError, ValueError):
        moment = dt_util.parse_datetime(str(value))
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def detect_tracking(baby, data, now):
    """
    {group: bool} from the baby's records: a group is tracked when its newest record is within
    TRACKING_WINDOW_DAYS. A baby younger than that tracks everything (nothing logged yet is not
    "stopped"). An older baby with nothing ever logged in a group is not tracking it.
    """
    window = timedelta(days=TRACKING_WINDOW_DAYS)
    born = _moment(getattr(baby, "dob", None))
    if born is not None and now - born < window:
        return dict.fromkeys(TRACKING_GROUPS, True)
    tracking = {}
    for group, keys in GROUP_RECORDS.items():
        tracked = False
        for key in keys:
            record = data.get(key) or {}
            if group == "sleep" and record.get("is_sleeping"):
                tracked = True
            moment = _moment(record.get("time"))
            if moment is not None and now - moment <= window:
                tracked = True
        tracking[group] = tracked
    return tracking


def resolve_tracking(options, baby, data, now):
    """(tracking dict, mode) for one baby: the override from the options flow, else detection."""
    setting = (options.get(CONF_TRACKING) or {}).get(baby.object_id, TRACKING_AUTO)
    if isinstance(setting, (list, tuple)):
        return {group: group in setting for group in TRACKING_GROUPS}, "manual"
    return detect_tracking(baby, data, now), "auto"


def is_tracked(baby_data, group):
    """Whether a baby's group is tracked (True when the data carries no verdict)."""
    return ((baby_data or {}).get("tracking") or {}).get(group, True)


GROUP_PHRASES = {
    "feeds": "Feeds", "diapers": "Diapers", "sleep": "Naps", "pumping": "Pumping sessions",
    "medicine": "Medicines", "growth": "Measurements", "temperature": "Temperatures",
}


def not_tracked_phrase(group, baby_name):
    """What Assist says when asked about something that is not being logged for the baby."""
    return f"{GROUP_PHRASES.get(group, group.capitalize())} aren't being tracked for {baby_name}"
