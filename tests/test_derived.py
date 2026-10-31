"""Answers worked out from stored records: breast side, next dose, upcoming milestones, milk inventory, calendar."""
from datetime import UTC, datetime, timedelta

import pytest
from helpers import COMMON, EVERLY, MILESTONE, TWIN, VACCINE


def at(utc_time):
    return datetime.strptime(utc_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S +0000")


def record(object_type, object_id, utc_time, baby=EVERLY, **fields):
    """A record another device made, at a UTC time."""
    return {**COMMON, "BCObjectType": object_type, "objectID": object_id, "baby": {"objectID": baby},
            "time": at(utc_time), "timestamp": at(utc_time), **fields}


def volume(value, english=False):
    return {"value": value, "englishMeasure": english}


def selection(object_type, object_id, name, **fields):
    return {"BCObjectType": object_type, "objectID": object_id, "name": name,
            "timestamp": COMMON["timestamp"], **fields}


# --- Which breast next ---

def test_no_nursing_or_pumping_means_unknown(tracker):
    assert tracker.get_next_breast() == {
        "next_side": "unknown", "last_side": "unknown", "last_type": None, "last_time": None}


@pytest.mark.parametrize("finish_side, expected", [(1, "right"), (2, "left"), (0, "unknown")])
def test_next_breast_is_the_side_the_last_nursing_did_not_finish_on(apply, tracker, finish_side, expected):
    apply(record("Nursing", "N1", "2026-10-01 08:00:00", finishSide=finish_side, leftDuration=5))
    state = tracker.get_next_breast()
    assert state["next_side"] == expected
    assert state["last_type"] == "nursing" and state["last_time"] == at("2026-10-01 08:00:00")


def test_a_later_pump_session_decides_the_side(apply, tracker):
    apply(record("Nursing", "N1", "2026-10-01 08:00:00", finishSide=2, leftDuration=5))  # finished right
    apply(record("Pump", "P1", "2026-10-01 09:00:00", finishSide=1, amount=volume(100)))  # then pumped, ending left
    state = tracker.get_next_breast()
    assert (state["next_side"], state["last_side"], state["last_type"]) == ("right", "left", "pump")

    # And a nursing session after that takes over again
    apply(record("Nursing", "N2", "2026-10-01 11:00:00", finishSide=2, rightDuration=5))
    assert tracker.get_next_breast()["next_side"] == "left"


def test_inventory_adjustments_and_future_records_do_not_count(apply, tracker):
    apply(record("Nursing", "N1", "2026-10-01 08:00:00", finishSide=2, leftDuration=5))
    apply(record("Pump", "ADJ", "2026-10-01 09:00:00", finishSide=1, label="InventoryAdjustment", amount=volume(50)))
    apply(record("Nursing", "FUTURE", "2999-01-01 08:00:00", finishSide=1, leftDuration=5))
    state = tracker.get_next_breast()
    assert (state["next_side"], state["last_type"]) == ("left", "nursing")


def test_next_breast_looks_at_every_baby_unless_told_otherwise(apply, tracker):
    apply(record("Nursing", "N-E", "2026-10-01 08:00:00", baby=EVERLY, finishSide=1, leftDuration=5))
    apply(record("Nursing", "N-T", "2026-10-01 10:00:00", baby=TWIN, finishSide=2, rightDuration=5))
    assert tracker.get_next_breast()["next_side"] == "left"  # the mother's last side, whichever baby
    assert tracker.get_next_breast(EVERLY)["next_side"] == "right"


# --- Next medicine dose ---

def medicine(object_id, utc_time, med_id, name, interval, baby=EVERLY, amount=2.5):
    return record("Medication", object_id, utc_time, baby=baby, amount=amount,
                  medicationSelection={"objectID": med_id, "name": name, "unit": "ml", "interval": interval})


def test_next_dose_is_the_last_dose_plus_the_interval_in_minutes(apply, tracker):
    apply(medicine("M1", "2026-10-01 08:00:00", "TYLENOL", "Tylenol", 240))
    dose = tracker.get_next_medicine_dose(EVERLY)
    assert dose["next_dose_at"] == "2026-10-01T12:00:00+00:00"
    assert (dose["medicine_name"], dose["amount"], dose["unit"], dose["interval_minutes"]) == ("Tylenol", 2.5, "ml", 240)
    assert dose["last_given"] == at("2026-10-01 08:00:00")


def test_next_dose_follows_the_most_recent_medicine(apply, tracker):
    apply(medicine("M1", "2026-10-01 08:00:00", "TYLENOL", "Tylenol", 240))
    apply(medicine("M2", "2026-10-01 09:00:00", "MOTRIN", "Motrin", 360, amount=1.25))
    dose = tracker.get_next_medicine_dose(EVERLY)
    assert (dose["medicine_name"], dose["next_dose_at"]) == ("Motrin", "2026-10-01T15:00:00+00:00")


def test_medicine_without_an_interval_has_no_next_dose(apply, tracker):
    apply(medicine("M1", "2026-10-01 08:00:00", "VITD", "Vitamin D", 0))
    dose = tracker.get_next_medicine_dose(EVERLY)
    assert dose["medicine_name"] == "Vitamin D" and dose["next_dose_at"] is None


def test_next_dose_is_per_baby(apply, tracker):
    apply(medicine("M1", "2026-10-01 08:00:00", "TYLENOL", "Tylenol", 240, baby=EVERLY))
    assert tracker.get_next_medicine_dose(TWIN) is None


# --- Upcoming milestones and vaccines ---

def test_upcoming_milestones_are_the_unlogged_ones_youngest_first(apply, tracker):
    apply(selection("MilestoneSelection", "MS-ROLL", "Rolls over", forAge=5))
    apply(selection("MilestoneSelection", "MS-SIT", "Sits up", forAge=6))

    assert [m["name"] for m in tracker.get_upcoming_milestones(EVERLY)] == ["First smile", "Rolls over", "Sits up"]
    first = tracker.get_upcoming_milestones(EVERLY)[0]
    assert (first["id"], first["for_age"]) == (MILESTONE, 2)

    apply(record("Milestone", "LOGGED", "2026-10-01 08:00:00", milestoneType={"objectID": MILESTONE}))
    assert [m["name"] for m in tracker.get_upcoming_milestones(EVERLY)] == ["Rolls over", "Sits up"]
    # The twin hasn't logged it
    assert tracker.get_upcoming_milestones(TWIN)[0]["name"] == "First smile"


def test_a_milestone_made_for_one_baby_is_not_offered_to_the_other(apply, tracker):
    apply(selection("MilestoneSelection", "MS-OWN", "Everly's own", forAge=1, babyID=EVERLY))
    assert "Everly's own" in [m["name"] for m in tracker.get_upcoming_milestones(EVERLY)]
    assert "Everly's own" not in [m["name"] for m in tracker.get_upcoming_milestones(TWIN)]


def test_upcoming_vaccines_are_the_unlogged_ones_youngest_first(apply, tracker):
    apply(selection("VaccineSelection", "V-MMR", "MMR", forAge=12))
    apply(selection("VaccineSelection", "V-ROTA", "Rotavirus", forAge=2))

    assert [v["name"] for v in tracker.get_upcoming_vaccines(EVERLY)] == ["HepB", "Rotavirus", "MMR"]
    apply(record("Vaccine", "SHOT", "2026-10-01 08:00:00", vaccineType={"objectID": VACCINE}))
    assert [v["name"] for v in tracker.get_upcoming_vaccines(EVERLY)] == ["Rotavirus", "MMR"]
    assert tracker.get_upcoming_vaccines(TWIN)[0]["name"] == "HepB"


def test_nothing_upcoming_once_everything_is_logged(apply, tracker):
    apply(record("Milestone", "LOGGED", "2026-10-01 08:00:00", milestoneType={"objectID": MILESTONE}))
    assert tracker.get_upcoming_milestones(EVERLY) == []


# --- Pumped milk inventory ---

def test_inventory_is_everything_pumped_minus_everything_fed(apply, tracker):
    assert tracker.get_pumped_milk_inventory() == {"ml": 0.0, "pumped_ml": 0.0, "fed_ml": 0.0}

    apply(record("Pump", "P1", "2026-10-01 08:00:00", amount=volume(300)))
    apply(record("Pump", "P2", "2026-10-01 12:00:00", amount=volume(4, english=True)))  # 118.294 ml
    # No total: the sides are added
    apply(record("Pump", "P3", "2026-10-01 16:00:00", leftAmount=volume(30), rightAmount=volume(40)))
    # An inventory adjustment (a Label) adds to what is in store
    apply(record("Pump", "ADJ", "2026-10-02 08:00:00", label="InventoryAdjustment", amount=volume(100)))
    apply(record("Pumped", "F1", "2026-10-02 09:00:00", baby=EVERLY, amount=volume(2, english=True)))  # 59.147 ml
    apply(record("Pumped", "F2", "2026-10-02 12:00:00", baby=TWIN, amount=volume(50)))

    inventory = tracker.get_pumped_milk_inventory()
    assert inventory["pumped_ml"] == pytest.approx(588.3, abs=0.05)
    assert inventory["fed_ml"] == pytest.approx(109.1, abs=0.05)
    assert inventory["ml"] == pytest.approx(479.1, abs=0.05)


def test_inventory_can_go_negative(apply, tracker):
    apply(record("Pumped", "F1", "2026-10-02 09:00:00", amount=volume(50)))
    assert tracker.get_pumped_milk_inventory()["ml"] == -50.0


# --- Calendar events ---

def day(hour, minute=0):
    return datetime(2026, 10, 1, hour, minute, tzinfo=UTC)


def test_events_between_covers_feeds_sleeps_baths_visits_and_medicines(apply, tracker):
    apply(record("Formula", "F", "2026-10-01 10:00:00", amount=volume(4, english=True)))
    apply(record("Nursing", "N", "2026-10-01 07:00:00", finishSide=1, leftDuration=12))
    apply(record("Sleep", "S", "2026-10-01 11:00:00", duration=80))
    apply(record("Bath", "B", "2026-10-01 18:00:00", bathType={"objectID": "BT", "name": "Evening bath"}))
    apply(record("DoctorVisit", "D", "2026-10-01 15:00:00", isAppointment=True, symptom="Cough"))
    apply(medicine("M", "2026-10-01 13:00:00", "TYLENOL", "Tylenol", 240))
    apply(record("Formula", "OTHER-BABY", "2026-10-01 10:30:00", baby=TWIN, amount=volume(3, english=True)))
    apply(record("Formula", "OTHER-DAY", "2026-10-02 10:00:00", amount=volume(3, english=True)))

    events = tracker.get_events_between(EVERLY, day(0), day(0) + timedelta(days=1))

    assert [(e["kind"], e["summary"]) for e in events] == [
        ("feeding", "Nursing (12 min)"),
        ("feeding", "Formula 4 oz"),
        ("sleep", "Sleep (1h 20m)"),
        ("medicine", "Medicine: Tylenol 2.5 ml"),
        ("doctor", "Doctor appointment: Cough"),
        ("bath", "Evening bath"),
    ]
    feed, sleep = events[1], events[2]
    assert feed["start"] == day(10) and feed["end"] == day(10, 15)  # 15 minutes
    assert sleep["start"] == day(11) and sleep["end"] == day(12, 20)  # the sleep's own duration
    assert feed["start"].tzinfo is not None


def test_a_sleep_that_began_before_the_range_is_included(apply, tracker):
    apply(record("Sleep", "NIGHT", "2026-09-30 21:00:00", duration=600))  # until 07:00
    apply(record("Sleep", "EARLIER", "2026-09-30 01:00:00", duration=60))
    events = tracker.get_events_between(EVERLY, day(0), day(12))
    assert [(e["summary"], e["end"]) for e in events] == [("Sleep (10h 0m)", day(7))]


def test_a_sleep_in_progress_runs_until_now(apply, tracker):
    start = datetime.now(UTC) - timedelta(hours=2)
    apply(record("Sleep", "NOW", start.strftime("%Y-%m-%d %H:%M:%S"), duration=0))
    events = tracker.get_events_between(EVERLY, start - timedelta(hours=1), start + timedelta(days=1))
    assert [e["summary"] for e in events] == ["Sleep (in progress)"]
    assert events[0]["end"] - events[0]["start"] >= timedelta(hours=2)


def test_an_old_unended_sleep_is_not_shown_as_in_progress(apply, tracker):
    stray = datetime.now(UTC) - timedelta(days=5)
    apply(record("Sleep", "STRAY", stray.strftime("%Y-%m-%d %H:%M:%S"), duration=0))
    # A range after it started: not carried forward as an ever-running event
    assert tracker.get_events_between(EVERLY, stray + timedelta(hours=1), datetime.now(UTC) + timedelta(days=1)) == []
    # In its own range it is just a short event
    events = tracker.get_events_between(EVERLY, stray - timedelta(hours=1), stray + timedelta(hours=1))
    assert [e["summary"] for e in events] == ["Sleep (never ended)"]
    assert events[0]["end"] - events[0]["start"] == timedelta(minutes=1)
