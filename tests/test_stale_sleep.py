"""A sleep left running (duration 0) is in progress for a day, no longer."""
from datetime import UTC, datetime, timedelta

from helpers import COMMON, EVERLY


def record(object_type, object_id, hours_ago, **fields):
    time = (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S +0000")
    return {**COMMON, "BCObjectType": object_type, "objectID": object_id, "time": time, **fields}


def test_a_sleep_started_today_is_in_progress(tracker, apply):
    apply(record("Sleep", "NOW", hours_ago=2, duration=0))
    last = tracker.get_last_sleep(EVERLY)
    assert last["is_sleeping"] and last["status"] == "sleeping"
    assert 115 <= last["current_duration"] <= 125
    assert tracker.is_currently_sleeping(EVERLY) is True


def test_an_old_unended_sleep_is_not_in_progress(tracker, apply):
    apply(record("Sleep", "STRAY", hours_ago=30, duration=0, note="forgot"))
    last = tracker.get_last_sleep(EVERLY)
    # Still the last sleep, so its time and note are there, but nothing is running
    assert last["id"] == "STRAY" and last["note"] == "forgot" and last["duration"] == 0
    assert last["is_sleeping"] is False and last["status"] == "awake"
    assert last["current_duration"] == 0
    assert tracker.is_currently_sleeping(EVERLY) is False


def test_the_in_progress_window_is_the_one_used_to_end_a_sleep(tracker, apply):
    from babytracker_client.database import IN_PROGRESS_SLEEP_SECONDS

    just_inside = IN_PROGRESS_SLEEP_SECONDS / 3600 - 0.1
    apply(record("Sleep", "EDGE", hours_ago=just_inside, duration=0))
    assert tracker.is_currently_sleeping(EVERLY) is True
    assert tracker.log_sleep_event(EVERLY, is_start=False)["status"] == "success"
    assert tracker.is_currently_sleeping(EVERLY) is False
