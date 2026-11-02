"""How each record type is stored (records.py, mirroring the app's putValues)."""
import sqlite3

import pytest
from babytracker_client.api import _get_local_timezone_offset_seconds
from helpers import COMMON, EVERLY, IPHONE


def test_temperature_uses_the_apps_columns(apply, query, tracker):
    apply({**COMMON, "BCObjectType": "Temperature", "objectID": "T1",
           "temperature": {"value": 99.1, "englishMeasure": True}})
    assert query("SELECT Temp, IsEnglishScale FROM Temperature WHERE ID='T1'") == [(99.1, 1)]
    assert tracker.get_last_temperature(EVERLY)["temp"] == 99.1


def test_nursing_keeps_finish_side(apply, query):
    apply({**COMMON, "BCObjectType": "Nursing", "objectID": "N1", "finishSide": 2, "leftDuration": 5, "rightDuration": 7})
    assert query("SELECT FinishSide, LeftDuration, RightDuration FROM Nursing WHERE ID='N1'") == [(2, 5, 7)]


@pytest.mark.parametrize("status, amount, stored", [
    (2, 2, (2, 2)),
    ("DiaperStatusMixed", "DiaperAmountHeavy", (2, 3)),  # Android's Gson writes enum names
    (3, 2, (0, 0)),                                       # dry is stored as wet + amount none
    (1, None, (1, 2)),                                    # a missing amount is saved as normal
])
def test_diaper_status_and_amount(apply, query, status, amount, stored):
    apply({**COMMON, "BCObjectType": "Diaper", "objectID": "D", "status": status, "amount": amount})
    assert query("SELECT Status, Amount FROM Diaper WHERE ID='D'") == [stored]


@pytest.mark.parametrize("picture_loaded, pictures, expected", [
    (True, [], 0),
    (False, [], 1),                                     # picture not downloaded yet
    (True, [{"objectID": "p", "deleted": False}], 1),
    (True, [{"objectID": "p", "deleted": True}], 0),    # deleted pictures don't count
])
def test_has_picture_follows_the_app(apply, query, picture_loaded, pictures, expected):
    apply({**COMMON, "BCObjectType": "Diaper", "objectID": "P", "status": 0,
           "pictureLoaded": picture_loaded, "pictureNote": pictures})
    assert query("SELECT HasPicture FROM Diaper WHERE ID='P'") == [(expected,)]


def test_pump_inventory_adjustment_has_no_sides(apply, query):
    apply({"BCObjectType": "Pump", "objectID": "INV", "timestamp": COMMON["timestamp"], "time": COMMON["time"],
           "label": "InventoryAdjustment", "sides": 1,
           "amount": {"value": 300, "englishMeasure": False}, "leftAmount": {"value": 100, "englishMeasure": False}})
    assert query("SELECT Amount, Sides, LeftAmount, Label FROM Pump WHERE ID='INV'") == [(300.0, 0, 0.0, "InventoryAdjustment")]


def test_new_medicine_selection_is_stored_for_lookups(apply, query):
    apply({**COMMON, "BCObjectType": "Medication", "objectID": "M1", "amount": 2.5,
           "medicationSelection": {"objectID": "NEWMED", "name": "Brand New Med", "unit": "ml",
                                   "amountPerTime": 2.5, "interval": 4, "prescription": True}})
    assert query("SELECT MedID, Amount FROM Medicine WHERE ID='M1'") == [("NEWMED", 2.5)]
    assert query("SELECT Name, IsPrescription FROM MedicineSelection WHERE ID='NEWMED'") == [("Brand New Med", 1)]


def test_activity_named_bath_is_kept_as_a_bath(apply, query):
    apply({**COMMON, "BCObjectType": "OtherActivity", "objectID": "OA",
           "desc": {"objectID": "CUSTOM-BATH", "name": "Bath"}, "duration": 10})
    assert query("SELECT DescID FROM Bath WHERE ID='OA'") == [("CUSTOM-BATH",)]


def test_delete_removes_the_record(apply, query):
    apply({**COMMON, "BCObjectType": "Diaper", "objectID": "GONE", "status": 0})
    apply({**COMMON, "BCObjectType": "Diaper", "objectID": "GONE"}, op=2)
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='GONE'") == [(0,)]


@pytest.mark.parametrize("object_type, table", [("Joy", "Joy"), ("Journal", "Journal")])
def test_joy_and_journal_are_merged_from_other_devices(tracker, server, query, object_type, table):
    server.publish(IPHONE, [{**COMMON, "BCObjectType": object_type, "objectID": "X1", "note": "first giggle",
                             "time": "2026-10-30 10:30:00 +0000"}])
    assert tracker.sync()["status"] == "success"
    rows = query(f"SELECT BabyID, Note, HasPicture, Time FROM {table} WHERE ID='X1'")
    assert rows == [(EVERLY, "first giggle", 0, tracker.db.convert_timestamp("2026-10-30 10:30:00 +0000"))]


def test_nursing_session_is_stored_as_nursing(tracker, server, query):
    server.publish(IPHONE, [{**COMMON, "BCObjectType": "NursingSession", "objectID": "NS1",
                             "finishSide": 1, "leftDuration": 6, "rightDuration": 4}])
    assert tracker.sync()["status"] == "success"
    assert query("SELECT BabyID, FinishSide, LeftDuration, RightDuration FROM Nursing WHERE ID='NS1'") == [(EVERLY, 1, 6, 4)]


@pytest.mark.parametrize("duration, stored", [(45, 45), (-30, 0), (None, 0)])
def test_sleep_duration_is_never_negative(apply, query, duration, stored):
    apply({**COMMON, "BCObjectType": "Sleep", "objectID": "S1", "duration": duration})
    assert query("SELECT Duration FROM Sleep WHERE ID='S1'") == [(stored,)]


def growth(weight=None, length=None, head=None):
    return {**COMMON, "BCObjectType": "Growth", "objectID": "G1",
            **{key: value for key, value in (("weight", weight), ("length", length), ("head", head)) if value is not None}}


def metric(value):
    return {"value": value, "englishMeasure": False}


def english(value):
    return {"value": value, "englishMeasure": True}


COLUMNS = "Weight, Length, Head, IsEnglishWeightScale, IsEnglishLengthScale"


@pytest.mark.parametrize("record, stored", [
    # The length's scale wins over the head's
    (growth(weight=metric(4.2), length=english(21.0), head=metric(35.0)), (4.2, 21.0, 35.0, 0, 1)),
    # Without a length, the head's scale is used
    (growth(weight=english(9.0), head=metric(35.0)), (9.0, 0.0, 35.0, 1, 0)),
    # A zero length is not a measurement: the head decides the scale
    (growth(length=english(0), head=metric(35.0)), (0.0, 0.0, 35.0, 1, 0)),
    # Nothing measured: weight and length scales default to English
    (growth(weight=metric(0)), (0.0, 0.0, 0.0, 1, 1)),
    (growth(weight=metric(-3.0), length=metric(-1.0)), (0.0, 0.0, 0.0, 1, 1)),
    (growth(), (0.0, 0.0, 0.0, 1, 1)),
])
def test_growth_follows_the_apps_scale_rules(apply, query, record, stored):
    apply(record)
    assert query(f"SELECT {COLUMNS} FROM Growth WHERE ID='G1'") == [stored]


def test_dates_accept_the_apps_fallback_formats(tracker):
    parse = tracker.db.convert_timestamp
    assert parse("2026-10-30 13:05:00 +0000") == parse("2026-10-30 01:05:00 PM +0000") == parse("2026-10-30 01:05:00 p.m. +0000")
    with pytest.raises(ValueError):
        parse("not a date")


@pytest.mark.parametrize("zone, offset", [
    ("America/Chicago", -21600), ("America/New_York", -18000), ("Europe/London", 0), ("Asia/Kolkata", 19800),
])
def test_timezone_offset_ignores_dst(zone, offset):
    assert _get_local_timezone_offset_seconds(zone) == offset


# ----- selections and joins that arrive from the phone after setup -----

NEW_SELECTIONS = [
    ("SleepDesc", "SleepDesc"),
    ("SleepLocationSelection", "SleepLocationSelection"),
    ("FeedDesc", "FeedDesc"),
    ("AllergenSourceSelection", "AllergenSourceSelection"),
    ("SickDesc", "SickDesc"),
    ("OtherActivityLocationSelection", "OtherActivityLocationSelection"),
    ("DoctorSelection", "DoctorSelection"),
]


@pytest.mark.parametrize("object_type, table", NEW_SELECTIONS)
def test_new_selection_types_are_stored(apply, query, object_type, table):
    apply({"BCObjectType": object_type, "objectID": "SEL1", "timestamp": COMMON["timestamp"],
           "name": "Crib", "desc": "by the window"})
    assert query(f"SELECT Name, Description FROM {table} WHERE ID='SEL1'") == [("Crib", "by the window")]


def test_doctor_selection_keeps_clinic_details(apply, query, tracker):
    apply({"BCObjectType": "DoctorSelection", "objectID": "DOC1", "timestamp": COMMON["timestamp"],
           "name": "Dr. Lee", "address": "1 Main St", "clinicName": "Kids Clinic", "phoneNumber": "555-0100"})
    assert query("SELECT Address, ClinicName, PhoneNumber FROM DoctorSelection WHERE ID='DOC1'") == [
        ("1 Main St", "Kids Clinic", "555-0100")]
    wire = tracker.db.get_named_wire("DoctorSelection", "DOC1")
    assert (wire["name"], wire["address"], wire["clinicName"], wire["phoneNumber"]) == (
        "Dr. Lee", "1 Main St", "Kids Clinic", "555-0100")


def test_selection_wire_names_of_the_ios_classes_are_aliases(apply, query):
    apply({"BCObjectType": "SleepLocation", "objectID": "SL", "timestamp": COMMON["timestamp"], "name": "Pram"})
    assert query("SELECT Name FROM SleepLocationSelection WHERE ID='SL'") == [("Pram",)]


def test_a_sleep_stores_its_location_and_description(apply, query, tracker):
    apply({**COMMON, "BCObjectType": "Sleep", "objectID": "S1", "duration": 40,
           "location": {"objectID": "LOC", "name": "Crib", "timestamp": COMMON["timestamp"]},
           "desc": {"objectID": "SD", "name": "Rocked", "timestamp": COMMON["timestamp"]}})
    assert query("SELECT LocationID, DescID FROM Sleep WHERE ID='S1'") == [("LOC", "SD")]
    # the nested selections are stored too, so names resolve
    assert query("SELECT Name FROM SleepLocationSelection WHERE ID='LOC'") == [("Crib",)]
    wire = tracker.db.get_record_wire("Sleep", "S1")
    assert wire["locationID"] == "LOC" and wire["desc"]["name"] == "Rocked"
    # a phone that sends plain IDs works too
    apply({**COMMON, "BCObjectType": "Sleep", "objectID": "S2", "locationID": "LOC", "descID": "SD"})
    assert query("SELECT LocationID, DescID FROM Sleep WHERE ID='S2'") == [("LOC", "SD")]


def test_feed_description_is_stored_on_every_feed_kind(apply, query):
    desc = {"objectID": "FD", "name": "Spit up", "timestamp": COMMON["timestamp"]}
    for kind, table in (("Nursing", "Nursing"), ("Formula", "Formula"), ("Pumped", "Pumped")):
        apply({**COMMON, "BCObjectType": kind, "objectID": f"F-{kind}", "desc": desc,
               "amount": {"value": 3, "englishMeasure": True}})
        assert query(f"SELECT DescID FROM {table} WHERE ID='F-{kind}'") == [("FD",)]
    assert query("SELECT Name FROM FeedDesc") == [("Spit up",)]


def test_doctor_visit_medicine_is_a_plain_join_record(apply, query):
    apply({"BCObjectType": "DoctorVisitMedicine", "objectID": "DVM", "timestamp": COMMON["timestamp"],
           "doctorVisitID": "VISIT", "medID": "MED"})
    assert query("SELECT DoctorVisitID, MedID FROM DoctorVisitMedicine WHERE ID='DVM'") == [("VISIT", "MED")]
    apply({"BCObjectType": "DoctorVisitMedicine", "objectID": "DVM", "timestamp": COMMON["timestamp"]}, op=2)
    assert query("SELECT * FROM DoctorVisitMedicine") == []


def test_doctor_visit_medicine_protects_its_medicine(apply, query):
    apply({"BCObjectType": "MedicationSelection", "objectID": "MED", "timestamp": COMMON["timestamp"],
           "name": "Amoxicillin"})
    apply({"BCObjectType": "DoctorVisitMedicine", "objectID": "DVM", "timestamp": COMMON["timestamp"],
           "doctorVisitID": "VISIT", "medID": "MED"})
    assert apply({"BCObjectType": "MedicationSelection", "objectID": "MED", "timestamp": COMMON["timestamp"]},
                 op=2) == "rejected"
    assert query("SELECT COUNT(*) FROM MedicineSelection WHERE ID='MED'") == [(1,)]


@pytest.mark.parametrize("selection, name, record", [
    ("SleepDesc", "Rocked", {"BCObjectType": "Sleep", "descID": "SEL"}),
    ("SleepLocationSelection", "Crib", {"BCObjectType": "Sleep", "locationID": "SEL"}),
    ("FeedDesc", "Burped", {"BCObjectType": "Formula", "descID": "SEL", "amount": {"value": 1, "englishMeasure": True}}),
    ("FeedDesc", "Burped", {"BCObjectType": "Nursing", "descID": "SEL"}),
    ("OtherActivityLocationSelection", "Park", {"BCObjectType": "OtherActivity", "locationID": "SEL"}),
    ("DoctorSelection", "Dr. Lee", {"BCObjectType": "DoctorVisit", "doctorID": "SEL"}),
])
def test_a_selection_in_use_is_not_deleted(apply, query, selection, name, record):
    apply({"BCObjectType": selection, "objectID": "SEL", "timestamp": COMMON["timestamp"], "name": name})
    apply({**COMMON, **record, "objectID": "R1"})
    assert apply({"BCObjectType": selection, "objectID": "SEL", "timestamp": COMMON["timestamp"]},
                 op=2) == "rejected"
    assert query(f"SELECT COUNT(*) FROM {selection} WHERE ID='SEL'") == [(1,)]


def test_an_unused_new_selection_is_deleted(apply, query):
    apply({"BCObjectType": "SleepDesc", "objectID": "SEL", "timestamp": COMMON["timestamp"], "name": "Rocked"})
    assert apply({"BCObjectType": "SleepDesc", "objectID": "SEL", "timestamp": COMMON["timestamp"]}, op=2) == "success"
    assert query("SELECT COUNT(*) FROM SleepDesc") == [(0,)]


def test_an_allergen_source_in_use_is_not_deleted(apply, app_db):
    apply({"BCObjectType": "AllergenSourceSelection", "objectID": "SRC", "timestamp": COMMON["timestamp"],
           "name": "Peanut"})
    conn = sqlite3.connect(app_db)
    conn.execute("INSERT INTO Allergen (ID, Time, BabyID, SourceID, Severity) VALUES ('A1', 1, ?, 'SRC', 1)", (EVERLY,))
    conn.commit()
    conn.close()
    assert apply({"BCObjectType": "AllergenSourceSelection", "objectID": "SRC", "timestamp": COMMON["timestamp"]},
                 op=2) == "rejected"


def test_a_clashing_new_selection_name_keeps_the_older(apply, query):
    apply({"BCObjectType": "SleepLocationSelection", "objectID": "OLD", "timestamp": "2026-01-01 00:00:00 +0000",
           "name": "Crib"})
    result = apply({"BCObjectType": "SleepLocationSelection", "objectID": "NEW",
                    "timestamp": "2026-10-01 00:00:00 +0000", "name": "Crib"})
    assert result == "rejected"
    assert query("SELECT ID FROM SleepLocationSelection") == [("OLD",)]
