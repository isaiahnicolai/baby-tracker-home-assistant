"""Reading the local database: per-baby results, the time zone, and units."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from babytracker_client import BabyTrackerLocalDatabase
from babytracker_client.api import _get_local_timezone_offset_seconds
from helpers import COMMON, AVA, TWIN

CHICAGO = ZoneInfo("America/Chicago")


def at(utc_time):
    return datetime.strptime(utc_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")


def baby_record(baby, object_type, object_id, utc_time, **fields):
    return {**COMMON, "BCObjectType": object_type, "objectID": object_id, "baby": {"objectID": baby},
            "time": at(utc_time), "timestamp": at(utc_time), **fields}


def test_growth_is_read_per_baby(apply, tracker):
    apply(baby_record(AVA, "Growth", "G-E", "2026-10-01 10:00:00", weight={"value": 12.5, "englishMeasure": True}))
    apply(baby_record(TWIN, "Growth", "G-T", "2026-10-02 10:00:00", weight={"value": 5.1, "englishMeasure": False},
                      length={"value": 55, "englishMeasure": False}))
    apply(baby_record(AVA, "Growth", "G-E2", "2026-09-01 10:00:00", weight={"value": 9.0, "englishMeasure": True}))

    ava, twin = tracker.get_last_growth(AVA), tracker.get_last_growth(TWIN)
    assert (ava["id"], ava["weight"], ava["weight_unit"]) == ("G-E", 12.5, "lbs")
    assert (twin["id"], twin["weight"], twin["weight_unit"], twin["length_unit"]) == ("G-T", 5.1, "kg", "cm")
    assert [r["id"] for r in tracker.get_growth_records(baby_id=AVA)] == ["G-E", "G-E2"]
    assert [r["id"] for r in tracker.get_growth_records(baby_id=TWIN)] == ["G-T"]


def test_a_head_only_visit_does_not_blank_the_other_measures(apply, tracker):
    apply(baby_record(AVA, "Growth", "G1", "2026-09-01 10:00:00", weight={"value": 9.0, "englishMeasure": True},
                      length={"value": 21, "englishMeasure": True}))
    apply(baby_record(AVA, "Growth", "G2", "2026-10-01 10:00:00", head={"value": 36, "englishMeasure": False}))

    growth = tracker.get_last_growth(AVA)

    assert growth["id"] == "G2"
    assert (growth["weight"], growth["weight_unit"], growth["weight_time"]) == (9.0, "lbs", at("2026-09-01 10:00:00"))
    assert (growth["length"], growth["length_unit"], growth["length_time"]) == (21, "in", at("2026-09-01 10:00:00"))
    assert (growth["head"], growth["head_unit"], growth["head_time"]) == (36, "cm", at("2026-10-01 10:00:00"))
    assert growth["time"] == at("2026-10-01 10:00:00")


def test_baby_without_growth_has_none(apply, tracker):
    apply(baby_record(AVA, "Growth", "G-E", "2026-10-01 10:00:00", weight={"value": 12.5, "englishMeasure": True}))
    assert tracker.get_last_growth(TWIN) is None


def test_other_activities_are_read_per_baby(apply, tracker):
    for baby, object_id in ((AVA, "OA-E"), (TWIN, "OA-T")):
        apply(baby_record(baby, "OtherActivity", object_id, "2026-10-01 10:00:00",
                          desc={"objectID": "DESC", "name": "Tummy time"}, duration=5))
    assert [r["id"] for r in tracker.get_activity_records(baby_id=TWIN)] == ["OA-T"]
    assert [r["id"] for r in tracker.get_activity_records(baby_id=AVA)] == ["OA-E"]


@pytest.mark.parametrize("value, english, expected", [
    (38.2, False, ("°C", 100.76, 38.2)),
    (99.1, True, ("°F", 99.1, 37.28)),
    (100.4, True, ("°F", 100.4, 38.0)),
])
def test_temperature_carries_its_unit_and_both_conversions(apply, tracker, value, english, expected):
    apply(baby_record(AVA, "Temperature", "T1", "2026-10-30 10:00:00",
                      temperature={"value": value, "englishMeasure": english}))
    reading = tracker.get_last_temperature(AVA)
    assert (reading["unit"], reading["fahrenheit"], reading["celsius"]) == expected
    assert reading["temp"] == value


def test_tracker_works_in_the_zone_it_is_given(app_db):
    from babytracker_client import BabyTracker

    named = BabyTracker(db_path=str(app_db), time_zone="America/Chicago")
    assert named.tz == CHICAGO
    assert named.api._tz_offset() == -21600

    zone = BabyTracker(db_path=str(app_db), tz=ZoneInfo("Asia/Kolkata"))
    assert zone.tz == ZoneInfo("Asia/Kolkata")
    assert zone.api._tz_offset() == 19800
    assert _get_local_timezone_offset_seconds(ZoneInfo("America/New_York")) == -18000

    assert BabyTracker(db_path=str(app_db)).tz is None  # the system's zone


@pytest.fixture
def chicago_db(app_db, monkeypatch):
    """A database reading in Chicago time, where it is 23:00 on 2026-10-30."""
    db = BabyTrackerLocalDatabase(str(app_db), tz=CHICAGO)
    now = datetime(2026, 10, 30, 23, 0, tzinfo=CHICAGO)
    monkeypatch.setattr(db, "_now", lambda: now)
    return db


def test_today_starts_at_local_midnight(apply, chicago_db):
    # 03:00 UTC on the 31st is 22:00 on the 30th in Chicago: today
    apply(baby_record(AVA, "Diaper", "D-TODAY", "2026-10-31 03:00:00", status=0, amount=2))
    # 04:00 UTC on the 30th is 23:00 on the 29th: yesterday
    apply(baby_record(AVA, "Diaper", "D-YESTERDAY", "2026-10-30 04:00:00", status=0, amount=2))
    # 01:00 UTC on the 30th is 20:00 on the 29th: yesterday
    apply(baby_record(AVA, "Diaper", "D-EARLIER", "2026-10-30 01:00:00", status=0, amount=2))
    # 06:00 UTC on the 30th is 01:00 on the 30th: today
    apply(baby_record(AVA, "Diaper", "D-MORNING", "2026-10-30 06:00:00", status=0, amount=2))

    assert chicago_db.get_today_wet_diaper_count(AVA) == 2
    assert chicago_db.get_daily_summary(AVA)["diaper_count"] == 2


def test_night_sleep_is_judged_in_local_time(apply, chicago_db):
    # 01:00 UTC is 20:00 on the 28th in Chicago (CDT): bedtime
    apply(baby_record(AVA, "Sleep", "S-NIGHT", "2026-10-29 01:00:00", duration=600))
    # 18:00 UTC is 13:00 in Chicago: a nap, although it is evening in UTC
    apply(baby_record(AVA, "Sleep", "S-NAP", "2026-10-29 18:00:00", duration=60))

    analysis = chicago_db.get_sleep_analysis(AVA)
    assert analysis["days_analyzed"] == 1
    night = analysis["per_day"][0]
    assert (night["date"], night["bedtime"], night["bedtime_minutes"]) == ("2026-10-28", "8:00 PM", 20 * 60)
    assert (night["wake_time"], night["wake_time_minutes"]) == ("6:00 AM", 6 * 60)


def test_a_night_sleep_counts_only_its_part_after_midnight(apply, chicago_db):
    # 20:00 yesterday to 06:00 today in Chicago: 6 hours of it are today
    apply(baby_record(AVA, "Sleep", "S-NIGHT", "2026-10-30 01:00:00", duration=600))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 6.0


def test_a_sleep_running_past_midnight_counts_only_until_midnight(apply, chicago_db):
    # 22:00 today to 07:00 tomorrow in Chicago: 2 hours of it are today
    apply(baby_record(AVA, "Sleep", "S-LATE", "2026-10-31 03:00:00", duration=540))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 2.0


def test_the_sleeps_of_the_day_and_both_ends_add_up(apply, chicago_db):
    apply(baby_record(AVA, "Sleep", "S-NIGHT", "2026-10-30 01:00:00", duration=600))  # 6 h today
    apply(baby_record(AVA, "Sleep", "S-NAP", "2026-10-30 18:00:00", duration=90))     # 1.5 h
    apply(baby_record(AVA, "Sleep", "S-LATE", "2026-10-31 03:00:00", duration=540))   # 2 h today
    apply(baby_record(TWIN, "Sleep", "S-OTHER", "2026-10-30 18:00:00", duration=300))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 9.5


def test_a_sleep_in_progress_counts_up_to_now(apply, chicago_db):
    # Since 13:00 in Chicago; it is 23:00
    apply(baby_record(AVA, "Sleep", "S-NOW", "2026-10-30 18:00:00", duration=0))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 10.0


def test_a_sleep_in_progress_since_yesterday_counts_from_midnight(apply, chicago_db):
    # Since 23:30 yesterday, still asleep at 23:00 today: 23 hours of today
    apply(baby_record(AVA, "Sleep", "S-NOW", "2026-10-30 04:30:00", duration=0))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 23.0


def test_a_days_sleep_is_capped_at_24_hours(apply, chicago_db):
    for i in range(5):  # 50 hours that all start today
        apply(baby_record(AVA, "Sleep", f"S-{i}", f"2026-10-30 {6 + i:02d}:00:00", duration=600))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 24.0


def test_a_sleep_that_was_never_ended_adds_nothing(apply, chicago_db):
    apply(baby_record(AVA, "Sleep", "S-STRAY", "2026-10-26 15:00:00", duration=0))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 0
    # nor does it count as running into a day that has other sleeps
    apply(baby_record(AVA, "Sleep", "S-NAP", "2026-10-30 18:00:00", duration=60))
    assert chicago_db.get_daily_summary(AVA)["sleep_hours"] == 1.0


def test_last_wet_and_dirty_diapers_count_mixed_ones_for_both(apply, tracker):
    apply(baby_record(AVA, "Diaper", "D-WET", "2026-10-01 10:00:00", status=0, amount=2))
    apply(baby_record(AVA, "Diaper", "D-DIRTY", "2026-10-01 11:00:00", status=1, amount=2))
    apply(baby_record(AVA, "Diaper", "D-MIXED", "2026-10-01 12:00:00", status=2, amount=2))
    apply(baby_record(AVA, "Diaper", "D-DRY", "2026-10-01 13:00:00", status=0, amount=0))
    assert tracker.get_last_diaper(AVA)["status"] == "Dry"

    wet, dirty = tracker.get_last_wet_diaper(AVA), tracker.get_last_dirty_diaper(AVA)
    assert (wet["id"], dirty["id"]) == ("D-MIXED", "D-MIXED")  # the dry one counts for neither

    apply(baby_record(AVA, "Diaper", "D-WET2", "2026-10-01 14:00:00", status=0, amount=1))
    assert tracker.get_last_wet_diaper(AVA)["id"] == "D-WET2"
    assert tracker.get_last_dirty_diaper(AVA)["id"] == "D-MIXED"


def test_last_wet_and_dirty_diapers_are_per_baby_and_none_when_missing(apply, tracker):
    apply(baby_record(AVA, "Diaper", "D-A", "2026-10-01 10:00:00", status=1, amount=2))
    apply(baby_record(TWIN, "Diaper", "D-T", "2026-10-02 10:00:00", status=0, amount=0))  # dry
    assert tracker.get_last_wet_diaper(AVA) is None
    assert tracker.get_last_dirty_diaper(AVA)["id"] == "D-A"
    assert tracker.get_last_wet_diaper(TWIN) is None and tracker.get_last_dirty_diaper(TWIN) is None
