"""Deleting records, the recent list, undo, and a sleep left running."""
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from babytracker_client.cli import main
from helpers import COMMON, EVERLY, MILESTONE, TWIN, VACCINE


def stamp(hours_ago=0.0, minutes_ago=0.0):
    moment = datetime.now(UTC) - timedelta(hours=hours_ago, minutes=minutes_ago)
    return moment.strftime("%Y-%m-%d %H:%M:%S +0000")


def record(object_type, object_id, hours_ago=1.0, baby=EVERLY, **fields):
    return {**COMMON, "BCObjectType": object_type, "objectID": object_id, "time": stamp(hours_ago),
            "baby": {"objectID": baby}, **fields}


def volume(value, english=False):
    return {"value": value, "englishMeasure": english, "BCObjectType": "VolumeMeasure"}


SELECTION = {"timestamp": "2026-01-01 00:00:00 +0000", "newFlage": False}

# One of every kind of record that can be deleted, as another device sends it
EVERY_RECORD = [
    record("Diaper", "R-DIAPER", status=1, amount=3, peeColor=2, pooColor=3, texture=1),
    record("Nursing", "R-NURSING", finishSide=2, leftDuration=10, rightDuration=8, bothDuration=0),
    record("Formula", "R-FORMULA", amount=volume(4, True)),
    record("Pumped", "R-PUMPED", amount=volume(90)),
    record("OtherFeed", "R-FEED", unit="tbsp", amount=volume(2, True),
           feedType={**SELECTION, "objectID": "FOOD", "name": "Banana", "desc": "", "bottle": False}),
    record("Sleep", "R-SLEEP", duration=45),
    record("Temperature", "R-TEMP", temperature={"value": 37.2, "englishMeasure": False}),
    record("Medication", "R-MED", amount=2.5, medicationSelection={
        **SELECTION, "objectID": "TYLENOL", "name": "Tylenol", "unit": "ml", "amountPerTime": 2.5,
        "interval": 4, "prescription": False}),
    record("Bath", "R-BATH", bathType={**SELECTION, "objectID": "SPONGE", "name": "Sponge Bath", "desc": "",
                                       "BCObjectType": "BathDesc"}),
    record("Growth", "R-GROWTH", weight={"value": 4.2, "englishMeasure": False},
           length={"value": 55, "englishMeasure": False}, head={"value": 36, "englishMeasure": False}),
    record("Milestone", "R-MILESTONE", milestoneType={**SELECTION, "objectID": MILESTONE, "name": "First smile",
                                                      "desc": "", "forAge": 2}),
    record("Vaccine", "R-VACCINE", vaccineType={**SELECTION, "objectID": VACCINE, "name": "HepB", "desc": "",
                                                "forAge": 0}),
    record("OtherActivity", "R-ACTIVITY", duration=10, desc={**SELECTION, "objectID": "TUMMY", "name": "Tummy Time",
                                                             "desc": "", "BCObjectType": "OtherActivityDescription"}),
    record("Joy", "R-JOY"),
    record("Journal", "R-JOURNAL", note="first steps"),
    record("DoctorVisit", "R-DOCTOR", isAppointment=False, visitType=1, symptom="cough"),
]
TABLES = {"Medication": "Medicine"}


def rows(path, table, object_id):
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}" WHERE ID = ?', (object_id,))]
    finally:
        conn.close()


@pytest.mark.parametrize("wire", EVERY_RECORD, ids=lambda wire: wire["BCObjectType"])
def test_the_wire_form_of_a_record_stores_back_the_same_row(apply, tracker, app_db, wire):
    """The JSON a delete carries is the record as the apps send it: merged back in, it is the same row."""
    apply(wire)
    table = TABLES.get(wire["BCObjectType"], wire["BCObjectType"])
    before = rows(app_db, table, wire["objectID"])
    assert before

    sent = tracker.db.get_record_wire(wire["BCObjectType"], wire["objectID"], -21600)
    assert sent["objectID"] == wire["objectID"] and sent["BCObjectType"] == wire["BCObjectType"]
    assert sent["baby"]["objectID"] == EVERLY and sent["baby"]["name"] == "Everly"

    tracker.db.delete_record(wire["BCObjectType"], wire["objectID"])
    assert rows(app_db, table, wire["objectID"]) == []
    apply(sent)
    assert rows(app_db, table, wire["objectID"]) == before


def test_delete_removes_the_row_and_queues_a_delete_with_the_whole_record(tracker, server, query):
    made = tracker.add_diaper(EVERLY, None, pee=True, poo=True, note="blowout")
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID=?", (made["objectID"],)) == [(1,)]
    server.uploads.clear()

    result = tracker.delete_record("Diaper", made["objectID"])

    assert result == {"status": "success", "object_type": "Diaper", "object_id": made["objectID"], "queued": False}
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID=?", (made["objectID"],)) == [(0,)]
    [upload] = server.uploads
    assert upload["OPCode"] == "2"
    sent = upload["record"]
    assert (sent["BCObjectType"], sent["objectID"], sent["note"], sent["status"]) == ("Diaper", made["objectID"],
                                                                                      "blowout", 2)
    assert sent["baby"]["objectID"] == EVERLY and sent["time"] and sent["timezone"] == -21600
    # Nothing is left waiting to go up
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(0,)]


def test_delete_is_queued_while_offline_and_sent_on_the_next_sync(tracker, server, query):
    made = tracker.add_formula(EVERLY, None, amount=4, is_english_measure=True)
    server.uploads.clear()
    server.online = False

    result = tracker.delete_record("Formula", made["objectID"])

    assert result["status"] == "success" and result["queued"] is True
    assert query("SELECT COUNT(*) FROM Formula") == [(0,)]
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(1,)]
    server.online = True
    assert tracker.sync()["uploaded_transactions"] == 1
    assert [u["OPCode"] for u in server.uploads] == ["2"]


def test_delete_takes_the_types_other_names(tracker, apply, server, query):
    apply(record("Medication", "M", amount=1, medicationSelection={**SELECTION, "objectID": "X", "name": "X"}))
    assert tracker.delete_record("Medicine", "M")["object_type"] == "Medication"
    assert query("SELECT COUNT(*) FROM Medicine") == [(0,)]
    assert server.uploads[-1]["record"]["BCObjectType"] == "Medication"


def test_delete_of_a_pump_session_has_no_baby(tracker, server, query):
    made = tracker.log_pump(None, 15, 10, 60, 40, False, "")
    server.uploads.clear()
    assert tracker.delete_record("Pump", made["objectID"])["status"] == "success"
    sent = server.uploads[-1]["record"]
    assert "baby" not in sent and sent["amount"]["value"] == 100 and sent["leftDuration"] == 15
    assert query("SELECT COUNT(*) FROM Pump") == [(0,)]


def test_deleting_a_local_doctor_visit_is_not_uploaded(tracker, server, query):
    assert tracker.log_doctor_visit(EVERLY, symptom="cough")
    [(visit,)] = query("SELECT ID FROM DoctorVisit")
    result = tracker.delete_record("DoctorVisit", visit)
    assert result["status"] == "success"
    assert query("SELECT COUNT(*) FROM DoctorVisit") == [(0,)]
    assert server.uploads == []


@pytest.mark.parametrize("object_type, object_id", [
    ("Diaper", "NO-SUCH"),
    ("Baby", EVERLY),
    ("MedicationSelection", "X"),
    ("Nonsense", "X"),
])
def test_delete_refuses_what_is_missing_or_not_a_record(tracker, server, query, object_type, object_id):
    result = tracker.delete_record(object_type, object_id)
    assert result["status"] == "error" and result["message"]
    assert server.uploads == []
    assert query("SELECT COUNT(*) FROM Baby") == [(2,)]


def test_delete_needs_a_signed_in_tracker(app_db):
    from babytracker_client import BabyTracker

    assert BabyTracker(db_path=str(app_db)).delete_record("Diaper", "X") == {
        "status": "error", "message": "Not authenticated"}


def test_our_delete_coming_back_from_the_server_changes_nothing(tracker, server, apply, query):
    made = tracker.add_diaper(EVERLY, None)
    tracker.delete_record("Diaper", made["objectID"])
    # The server hands our own upload back (a fresh sync, or an old progress mark)
    server.publish(tracker.api.device_uuid, [server.uploads[-1]["record"]], op=2, start=900)
    assert tracker.sync()["status"] == "success"
    assert query("SELECT COUNT(*) FROM Diaper") == [(0,)]
    assert server.uploads[-1]["OPCode"] == "2" and len(server.uploads) == 2  # not echoed again


def test_a_delete_from_another_device_after_ours_is_ignored(tracker, server, apply, query):
    made = tracker.add_diaper(EVERLY, None)
    tracker.delete_record("Diaper", made["objectID"])
    uploads = len(server.uploads)
    wire = {**EVERY_RECORD[0], "objectID": made["objectID"]}
    assert apply(wire, op=2) == "ignored"
    assert query("SELECT COUNT(*) FROM Diaper") == [(0,)]
    assert len(server.uploads) == uploads


# --- recent records and undo ---

def test_recent_records_run_newest_first_across_types(tracker, apply):
    apply(record("Diaper", "D1", hours_ago=5, status=0, amount=2))
    apply(record("Nursing", "N1", hours_ago=1, leftDuration=10, rightDuration=8))
    apply(record("Formula", "F1", hours_ago=3, amount=volume(4, True)))
    apply(record("Sleep", "S1", hours_ago=2, duration=45))
    apply(record("Temperature", "T1", hours_ago=4, temperature={"value": 37.2, "englishMeasure": False}))
    apply(record("Diaper", "OTHER", hours_ago=0.1, baby=TWIN, status=0, amount=2))

    recent = tracker.get_recent_records(EVERLY)

    assert [(item["object_type"], item["object_id"], item["kind"]) for item in recent] == [
        ("Nursing", "N1", "nursing L 10 / R 8"),
        ("Sleep", "S1", "sleep 45 min"),
        ("Formula", "F1", "formula 4 oz"),
        ("Temperature", "T1", "temperature 37.2 C"),
        ("Diaper", "D1", "wet diaper"),
    ]
    assert set(recent[0]) == {"object_type", "object_id", "time", "kind", "note"}


def test_recent_records_time_is_aware_and_in_the_trackers_zone(tracker, apply):
    apply(record("Diaper", "D1", hours_ago=1, status=0, amount=2, note="hi"))
    [item] = tracker.get_recent_records(EVERLY)
    moment = datetime.fromisoformat(item["time"])
    assert moment.utcoffset() is not None
    assert abs(datetime.now(UTC) - moment - timedelta(hours=1)) < timedelta(minutes=1)
    assert moment.utcoffset() in (timedelta(hours=-5), timedelta(hours=-6))  # America/Chicago
    assert item["note"] == "hi"


def test_recent_records_limit_and_window(tracker, apply):
    for index in range(5):
        apply(record("Journal", f"J{index}", hours_ago=index * 10 + 1))
    assert [item["object_id"] for item in tracker.get_recent_records(EVERLY, limit=2)] == ["J0", "J1"]
    assert [item["object_id"] for item in tracker.get_recent_records(EVERLY, within_hours=25)] == ["J0", "J1", "J2"]
    assert tracker.get_recent_records(EVERLY, limit=0) == []
    assert tracker.get_recent_records("NO-SUCH-BABY") == []


def test_recent_records_label_every_kind(tracker, apply):
    for wire in EVERY_RECORD:
        apply(wire)
    apply(record("Diaper", "DRY", status=0, amount=0))
    apply(record("Sleep", "OPEN", hours_ago=0.5, duration=0))
    kinds = {item["object_id"]: item["kind"] for item in tracker.get_recent_records(EVERLY, limit=50)}
    assert kinds == {
        "R-DIAPER": "poopy diaper", "DRY": "dry diaper", "R-NURSING": "nursing L 10 / R 8",
        "R-FORMULA": "formula 4 oz", "R-PUMPED": "pumped milk 90 ml", "R-FEED": "banana 2 tbsp",
        "R-SLEEP": "sleep 45 min", "OPEN": "sleep in progress", "R-TEMP": "temperature 37.2 C",
        "R-MED": "medicine tylenol 2.5 ml", "R-BATH": "bath sponge bath",
        "R-GROWTH": "growth 4.2 kg, 55 cm, head 36 cm", "R-MILESTONE": "milestone first smile",
        "R-VACCINE": "vaccine hepb", "R-ACTIVITY": "tummy time 10 min", "R-JOY": "joy", "R-JOURNAL": "journal",
        "R-DOCTOR": "doctor visit: cough",
    }


def test_pump_sessions_are_not_listed_because_they_have_no_baby(tracker):
    tracker.log_pump(None, 15, 10, 60, 40, False, "")
    assert tracker.get_recent_records(EVERLY) == []


def test_undo_deletes_the_newest_record_across_types(tracker, server, apply, query):
    apply(record("Diaper", "OLD", hours_ago=3, status=0, amount=2))
    apply(record("Formula", "NEWEST", hours_ago=0.2, amount=volume(120)))
    apply(record("Nursing", "MIDDLE", hours_ago=1, leftDuration=5))
    apply(record("Diaper", "SIBLING", hours_ago=0.01, baby=TWIN, status=0, amount=2))

    result = tracker.undo_last(EVERLY)

    assert result["status"] == "success"
    assert result["deleted"]["object_id"] == "NEWEST" and result["deleted"]["kind"] == "formula 120 ml"
    assert result["deleted"]["object_type"] == "Formula"
    assert query("SELECT COUNT(*) FROM Formula") == [(0,)]
    assert query("SELECT COUNT(*) FROM Diaper") == [(2,)] and query("SELECT COUNT(*) FROM Nursing") == [(1,)]
    assert server.uploads[-1]["OPCode"] == "2" and server.uploads[-1]["record"]["objectID"] == "NEWEST"

    # Again: the next one goes
    assert tracker.undo_last(EVERLY)["deleted"]["object_id"] == "MIDDLE"


def test_undo_leaves_records_outside_the_window(tracker, server, apply, query):
    apply(record("Diaper", "OLD", hours_ago=30, status=0, amount=2))
    assert tracker.undo_last(EVERLY) == {"status": "error", "message": "Nothing to undo"}
    assert query("SELECT COUNT(*) FROM Diaper") == [(1,)]
    assert server.uploads == []
    assert tracker.undo_last(EVERLY, within_hours=48)["deleted"]["object_id"] == "OLD"
    assert tracker.undo_last(TWIN)["message"] == "Nothing to undo"


# --- the command line ---

@pytest.fixture
def state_dir(tmp_path, app_db, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    shutil.copy(app_db, state / "babytracker.db")
    monkeypatch.setenv("BABYTRACKER_EMAIL", "me@example.com")
    monkeypatch.setenv("BABYTRACKER_PASSWORD", "pw")
    return state


def run(capsys, state_dir, *args):
    main(["--state-dir", str(state_dir), "--time-zone", "America/Chicago", *args])
    return json.loads(capsys.readouterr().out)


def earlier(state_dir, table, minutes=10):
    """Move everything in a table back in time (the commands stamp records to the second)."""
    conn = sqlite3.connect(state_dir / "babytracker.db")
    conn.execute(f"UPDATE {table} SET Time = Time - ?", (minutes * 60,))
    conn.commit()
    conn.close()


def test_cli_recent_lists_what_delete_takes(server, state_dir, capsys):
    run(capsys, state_dir, "add-diaper", "wet", "--baby", "everly")
    earlier(state_dir, "Diaper")
    run(capsys, state_dir, "--offline", "add-nursing", "--baby", "everly", "--left", "12")
    recent = run(capsys, state_dir, "--offline", "recent", "--baby", "everly", "--limit", "5")
    assert [(item["object_type"], item["kind"]) for item in recent] == [("Nursing", "nursing L 12"),
                                                                       ("Diaper", "wet diaper")]


def test_cli_delete_needs_yes(server, state_dir, capsys):
    made = run(capsys, state_dir, "add-diaper", "wet", "--baby", "everly")
    with pytest.raises(SystemExit, match="--yes"):
        main(["--state-dir", str(state_dir), "--offline", "delete", "Diaper", made["objectID"]])
    assert [item["object_id"] for item in run(capsys, state_dir, "--offline", "recent", "--baby", "everly")] == [
        made["objectID"]]

    result = run(capsys, state_dir, "--offline", "delete", "Diaper", made["objectID"], "--yes")
    assert result["status"] == "success" and result["object_id"] == made["objectID"]
    assert server.uploads[-1]["OPCode"] == "2"
    assert run(capsys, state_dir, "--offline", "recent", "--baby", "everly") == []


def test_cli_delete_of_an_unknown_record_fails(server, state_dir, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--state-dir", str(state_dir), "--offline", "delete", "Diaper", "NO-SUCH", "--yes"])
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_cli_undo_shows_then_deletes(server, state_dir, capsys):
    run(capsys, state_dir, "add-diaper", "wet", "--baby", "everly")
    earlier(state_dir, "Diaper")
    made = run(capsys, state_dir, "--offline", "add-bottle", "--baby", "everly", "--amount", "3")

    with pytest.raises(SystemExit, match="--yes"):
        main(["--state-dir", str(state_dir), "--offline", "undo", "--baby", "everly"])
    assert json.loads(capsys.readouterr().out)["would_delete"]["object_id"] == made["objectID"]

    result = run(capsys, state_dir, "--offline", "undo", "--baby", "everly", "--yes")
    assert result["status"] == "success" and result["deleted"]["object_id"] == made["objectID"]
    assert [item["kind"] for item in run(capsys, state_dir, "--offline", "recent", "--baby", "everly")] == [
        "wet diaper"]


def test_cli_undo_with_nothing_to_undo(server, state_dir, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--state-dir", str(state_dir), "--offline", "undo", "--baby", "everly", "--yes"])
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["message"] == "Nothing to undo"
