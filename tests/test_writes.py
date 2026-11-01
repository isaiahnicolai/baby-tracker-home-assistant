"""Logging records: the right baby, the app's formats, and the upload queue."""
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
