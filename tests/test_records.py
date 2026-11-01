"""How each record type is stored (records.py, mirroring the app's putValues)."""
import pytest

from babytracker_client.api import _get_local_timezone_offset_seconds
from helpers import EVERLY, b64

COMMON = {"timestamp": "2026-10-30 12:00:00 +0000", "time": "2026-10-30 11:00:00 +0000", "note": "",
          "pictureLoaded": True, "pictureNote": [], "baby": {"objectID": EVERLY}}


@pytest.fixture
def apply(tracker):
    def run(record, op=0):
        result = tracker.api.transaction_handler.merge({"SyncID": 1, "OPCode": op, "Transaction": b64(record)})
        assert result != "error", record
        return result
    return run


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
