"""Logging records: the right baby, the app's formats, and the upload queue."""
from datetime import UTC

from helpers import EVERLY, IPHONE, MILESTONE, OURS, TWIN, VACCINE


def test_keeps_its_own_device_identity(tracker):
    # Older versions adopted another device's UUID (usually a phone)
    assert tracker.api.device_uuid == OURS


def test_records_go_to_the_chosen_baby(tracker, server, query):
    result = tracker.add_diaper(TWIN, None, pee=True, poo=True)
    assert result["status"] == "success"
    assert server.uploads[-1]["record"]["baby"]["objectID"] == TWIN
    assert server.uploads[-1]["record"]["status"] == 2
    # Applied locally straight away, not on the next sync
    assert query("SELECT BabyID, Status FROM Diaper WHERE ID=?", (result["objectID"],)) == [(TWIN, 2)]


def test_sleep_end_stays_with_its_baby(tracker, server):
    assert tracker.log_sleep_event(TWIN, is_start=True)["status"] == "success"
    assert tracker.log_sleep_event(TWIN, is_start=False)["status"] == "success"
    end = server.uploads[-1]
    assert end["OPCode"] == "1"
    assert end["record"]["baby"]["objectID"] == TWIN


def test_unknown_baby_is_refused_not_invented(tracker, server):
    result = tracker.add_diaper("NO-SUCH-BABY", None)
    assert result["status"] == "error"
    assert "not found" in result["message"]
    assert server.uploads == []


def test_dry_diaper_is_stored_the_apps_way(tracker, query):
    result = tracker.add_diaper(EVERLY, None, pee=False, poo=False)
    # Diaper.putValues: dry is wet with amount None; colours/texture unset = 5
    assert query("SELECT Status, Amount, PeeColor, PooColor, Texture FROM Diaper WHERE ID=?",
                 (result["objectID"],)) == [(0, 0, 5, 5, 5)]
    assert tracker.get_last_diaper(EVERLY)["status"] == "Dry"


def test_offline_records_are_queued_then_uploaded_in_order(tracker, server, query):
    server.online = False
    first = tracker.add_diaper(EVERLY, None, pee=True)
    second = tracker.add_diaper(TWIN, None, poo=True, pee=False)
    assert first["status"] == second["status"] == "success"
    assert first["queued"] and second["queued"]
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(2,)]

    server.online = True
    assert tracker.sync()["uploaded_transactions"] == 2
    # SyncIDs continue past both the server's count (7) and the seed's counter (43)
    assert [u["SyncID"] for u in server.uploads] == [44, 45]
    assert [u["record"]["objectID"] for u in server.uploads] == [first["objectID"], second["objectID"]]
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(0,)]


def test_session_expiry_logs_in_again(tracker, server):
    server.expire_session_once = True
    assert tracker.add_diaper(EVERLY, None)["status"] == "success"
    assert len(server.uploads) == 1


def test_pump_has_no_baby(tracker, server, query):
    result = tracker.log_pump(None, 15, 10, 60, 40, False, "")
    sent = server.uploads[-1]["record"]
    assert "baby" not in sent
    assert sent["amount"] == {"englishMeasure": False, "value": 100.0}
    assert query("SELECT LeftAmount, RightAmount, LeftDuration FROM Pump WHERE ID=?",
                 (result["objectID"],)) == [(60.0, 40.0, 15)]


def test_growth_uses_measures_and_omits_unset_values(tracker, server, query):
    result = tracker.log_growth(TWIN, 12.5, 23, 0, True, True, "")
    sent = server.uploads[-1]["record"]
    assert sent["weight"] == {"englishMeasure": True, "value": 12.5}
    assert "head" not in sent
    assert query("SELECT BabyID, Weight, Length, Head FROM Growth WHERE ID=?",
                 (result["objectID"],)) == [(TWIN, 12.5, 23.0, 0)]


def test_milestone_and_vaccine_use_the_apps_field_names(tracker, server, query):
    milestone = tracker.log_milestone(TWIN, MILESTONE, "")
    assert server.uploads[-1]["record"]["milestoneType"]["objectID"] == MILESTONE
    vaccine = tracker.log_vaccine(TWIN, VACCINE, "")
    assert server.uploads[-1]["record"]["vaccineType"]["objectID"] == VACCINE
    assert query("SELECT MilestoneSelectionID FROM Milestone WHERE ID=?", (milestone["objectID"],)) == [(MILESTONE,)]
    assert query("SELECT VaccID, DocVisitID FROM Vaccine WHERE ID=?", (vaccine["objectID"],)) == [(VACCINE, "NotUsed")]


def test_timezone_is_the_standard_offset(tracker, server):
    tracker.add_diaper(EVERLY, None)
    # America/Chicago without DST, like Java's TimeZone.getRawOffset
    assert server.uploads[-1]["record"]["timezone"] == -21600


def test_other_devices_sync_position_is_untouched(tracker, query):
    tracker.add_diaper(EVERLY, None)
    assert query("SELECT last_sync_id FROM DeviceSyncInfo WHERE device_uuid=?", (IPHONE,)) in ([], [(0,)])


def test_sleep_can_be_dated_when_it_happened(tracker, server, query):
    from datetime import datetime, timedelta

    fell_asleep = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    assert tracker.log_sleep_event(TWIN, is_start=True, time=fell_asleep)["status"] == "success"
    assert query("SELECT Time, Duration FROM Sleep WHERE BabyID=? ORDER BY Time DESC LIMIT 1",
                 (TWIN,)) == [(fell_asleep.timestamp(), 0)]

    # The end can be given as the sync format's text, and works out the duration from the start
    woke = (fell_asleep + timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M:%S +0000")
    assert tracker.log_sleep_event(TWIN, is_start=False, time=woke)["status"] == "success"
    assert server.uploads[-1]["record"]["duration"] == 90
    assert server.uploads[-1]["record"]["time"] == "2026-03-01 09:00:00 +0000"


def test_sleep_cannot_end_before_it_started(tracker):
    from datetime import datetime, timedelta

    started = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    assert tracker.log_sleep_event(TWIN, is_start=True, time=started)["status"] == "success"
    result = tracker.log_sleep_event(TWIN, is_start=False, time=started - timedelta(minutes=5))
    assert result["status"] == "error"


def test_a_sleep_ended_within_its_first_minute_is_still_ended(tracker, server, query):
    import time

    assert tracker.log_sleep_event(TWIN, is_start=True)["status"] == "success"
    time.sleep(1.1)  # an update only replaces a record with an older timestamp
    assert tracker.log_sleep_event(TWIN, is_start=False)["status"] == "success"
    # Duration 0 would mean "still sleeping"
    assert server.uploads[-1]["record"]["duration"] == 1
    assert query("SELECT Duration FROM Sleep WHERE BabyID=?", (TWIN,)) == [(1,)]
    assert tracker.is_currently_sleeping(TWIN) is False


def test_ending_a_sleep_rounds_to_the_nearest_minute(tracker, server):
    from datetime import datetime, timedelta

    started = datetime.now(UTC) - timedelta(minutes=10, seconds=40)
    assert tracker.log_sleep_event(TWIN, is_start=True, time=started)["status"] == "success"
    assert tracker.log_sleep_event(TWIN, is_start=False)["status"] == "success"
    assert server.uploads[-1]["record"]["duration"] == 11


def test_an_old_unended_sleep_is_not_closed_by_a_new_wake_up(tracker):
    from datetime import datetime, timedelta

    stray = datetime.now(UTC) - timedelta(days=3)
    assert tracker.log_sleep_event(TWIN, is_start=True, time=stray)["status"] == "success"
    result = tracker.log_sleep_event(TWIN, is_start=False)
    assert result["status"] == "error"
    assert "No active sleep" in result["message"]


def test_a_medicine_is_posted_with_its_own_prescription_flag(tracker, apply, server):
    for object_id, prescription in (("MED-RX", True), ("MED-OTC", False)):
        apply({"BCObjectType": "MedicationSelection", "objectID": object_id, "name": object_id,
               "timestamp": "2026-10-30 12:00:00 +0000", "prescription": prescription, "amountPerTime": 2.5,
               "unit": "ml", "interval": 240})

    for med_id, prescription in (("MED-RX", True), ("MED-OTC", False)):
        assert tracker.add_medicine(EVERLY, None, med_id=med_id, amount=2.5)["status"] == "success"
        selection = server.uploads[-1]["record"]["medicationSelection"]
        assert selection["objectID"] == med_id and selection["prescription"] is prescription


def test_pending_upload_count_is_what_has_not_been_sent(tracker, server):
    assert tracker.pending_upload_count() == 0
    server.online = False
    tracker.add_diaper(EVERLY, None, pee=True)
    tracker.add_diaper(TWIN, None, pee=True)
    assert tracker.pending_upload_count() == 2
    server.online = True
    tracker.sync()
    assert tracker.pending_upload_count() == 0


def test_a_new_medicine_is_posted_as_the_app_would_and_lands_in_the_table(tracker, server, query):
    result = tracker.create_medicine("Tylenol", amount_per_time=2.5, unit="ml", interval_hours=6, prescription=True)
    assert result["status"] == "success"
    assert len(server.uploads) == 1
    record = server.uploads[0]["record"]
    assert record.pop("timestamp")
    assert record == {
        "BCObjectType": "MedicationSelection", "objectID": result["objectID"], "newFlage": "true",
        "name": "Tylenol", "desc": "", "prescription": True, "amountPerTime": 2.5, "unit": "ml", "interval": 6,
    }
    assert query("SELECT Name, IsPrescription, AmountPerTime, Unit, Interval FROM MedicineSelection WHERE ID=?",
                 (result["objectID"],)) == [("Tylenol", 1, 2.5, "ml", 6)]

    # It is then offered for logging
    assert [m["name"] for m in tracker.get_medicine_selections()] == ["Tylenol"]
    assert tracker.add_medicine(EVERLY, None, med_id=result["objectID"], amount=2.5)["status"] == "success"
    assert server.uploads[-1]["record"]["medicationSelection"]["objectID"] == result["objectID"]


def test_a_new_food_is_posted_as_the_app_would_and_lands_in_the_table(tracker, server, query):
    result = tracker.create_food("Mango", is_bottle=True)
    assert result["status"] == "success"
    assert len(server.uploads) == 1
    record = server.uploads[0]["record"]
    assert record.pop("timestamp")
    assert record == {
        "BCObjectType": "OtherFeedSelection", "objectID": result["objectID"], "newFlage": "true",
        "name": "Mango", "desc": "", "bottle": True,
    }
    assert query("SELECT Name, IsBottle FROM OtherFeedSelection WHERE ID=?", (result["objectID"],)) == [("Mango", 1)]
    assert [f["name"] for f in tracker.get_other_feed_selections()] == ["Mango"]
    assert tracker.add_other_feed(EVERLY, None, feed_type_id=result["objectID"], amount=1)["status"] == "success"


def test_creating_a_selection_that_exists_posts_nothing(tracker, server):
    first = tracker.create_medicine("Tylenol")
    food = tracker.create_food("Mango")
    posted = len(server.uploads)
    again = tracker.create_medicine("  tylenol ")
    assert again["status"] == "success" and again["objectID"] == first["objectID"]
    assert "already existed" in again["message"]
    again = tracker.create_food("MANGO")
    assert again["status"] == "success" and again["objectID"] == food["objectID"]
    assert len(server.uploads) == posted


def test_a_selection_needs_a_name(tracker, server):
    for create in (tracker.create_medicine, tracker.create_food):
        assert create("   ")["status"] == "error"
    assert server.uploads == []
