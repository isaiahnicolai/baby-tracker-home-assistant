"""Downloading and merging other devices' changes (SyncImple / BTDatabaseImple rules)."""
from helpers import EVERLY, IPHONE, OURS, TWIN, b64


def diaper(object_id, status=0, timestamp="2026-10-30 10:00:00 +0000", time="2026-10-30 10:00:00 +0000", baby=EVERLY):
    return {"BCObjectType": "Diaper", "objectID": object_id, "timestamp": timestamp, "time": time,
            "status": status, "amount": 2, "note": "", "pictureLoaded": True, "pictureNote": [],
            "baby": {"objectID": baby}}


def baby(object_id, name, timestamp="2026-10-30 12:00:00 +0000"):
    return {"BCObjectType": "Baby", "objectID": object_id, "name": name, "timestamp": timestamp,
            "dob": "2026-01-01 00:00:00 +0000", "dueDay": "2026-01-01 00:00:00 +0000", "gender": False}


def merge(tracker, record, op):
    return tracker.api.transaction_handler.merge({"SyncID": 1, "OPCode": op, "Transaction": b64(record)})


def progress(query):
    rows = query("SELECT last_sync_id FROM DeviceSyncInfo WHERE device_uuid=?", (IPHONE,))
    return rows[0][0] if rows else 0


def test_paginates_large_histories(tracker, server, query):
    server.publish(IPHONE, [diaper(f"D{i}") for i in range(1, 502)])
    tracker.sync()
    gets = [p for m, p in server.requests if m == "GET" and p.startswith(f"/account/transaction/{IPHONE}")]
    assert gets[:2] == [f"/account/transaction/{IPHONE}/0", f"/account/transaction/{IPHONE}/500"]
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID LIKE 'D%'") == [(501,)]
    assert progress(query) == 501


def test_updates_only_overwrite_older_rows(tracker, server, query):
    server.publish(IPHONE, [diaper("A"), diaper("B")])
    server.publish(IPHONE, [diaper("A", status=2, timestamp="2026-10-30 09:00:00 +0000"),   # stale
                            diaper("B", status=1, timestamp="2026-10-30 11:00:00 +0000")],  # newer
                   op=1)
    tracker.sync()
    assert query("SELECT ID, Status FROM Diaper WHERE ID IN ('A','B') ORDER BY ID") == [("A", 0), ("B", 1)]


def test_a_failing_record_is_retried_then_skipped(tracker, server, query):
    server.publish(IPHONE, [diaper("OK1"), diaper("BAD", time="not a date"), diaper("OK2")])
    tracker.sync()
    # Stops at the failure instead of silently passing it
    assert progress(query) == 1
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID IN ('BAD','OK2')") == [(0,)]
    tracker.sync()
    tracker.sync()
    # After three attempts it is skipped (and logged) so the rest can apply
    assert progress(query) == 3
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='OK2'") == [(1,)]
    # Never stored as 1970
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='BAD'") == [(0,)]


def test_our_own_uploads_coming_back_are_harmless(tracker, server, query):
    tracker.add_diaper(EVERLY, None)
    before = query("SELECT COUNT(*) FROM Diaper")
    server.logs[OURS] = [{k: u[k] for k in ("SyncID", "OPCode", "Transaction")} for u in server.uploads]
    assert tracker.sync()["status"] == "success"
    assert query("SELECT COUNT(*) FROM Diaper") == before


def test_deleting_a_baby_with_records_is_rejected(tracker, query):
    tracker.add_diaper(TWIN, None)
    assert merge(tracker, baby(TWIN, "Ann Marie"), op=2) == "rejected"
    assert query("SELECT COUNT(*) FROM Baby WHERE ID=?", (TWIN,)) == [(1,)]


def test_relive_swallows_the_echoed_delete(tracker, query):
    assert merge(tracker, baby(TWIN, "Ann Marie"), op=3) == "success"
    assert merge(tracker, baby(TWIN, "Ann Marie"), op=2) == "success"
    assert query("SELECT COUNT(*) FROM Baby WHERE ID=?", (TWIN,)) == [(1,)]


def test_conflict_moves_the_losers_records_to_the_winner(tracker, query):
    tracker.add_diaper(TWIN, None)
    tracker.add_diaper(TWIN, None)
    conflict = {"BCObjectType": "ConflictRecord", "winner": baby("WINNER", "Ann Marie"), "loser": baby(TWIN, "Ann Marie")}
    assert merge(tracker, conflict, op=4) == "success"
    assert query("SELECT COUNT(*) FROM Diaper WHERE BabyID='WINNER'") == [(2,)]
    assert query("SELECT COUNT(*) FROM Baby WHERE ID=?", (TWIN,)) == [(0,)]


def test_name_clash_keeps_the_older_baby(tracker, query):
    newer = baby("OTHER-ID", "Everly", timestamp="2030-01-01 00:00:00 +0000")
    assert merge(tracker, newer, op=0) == "rejected"
    assert query("SELECT ID FROM Baby WHERE Name='Everly'") == [(EVERLY,)]


def test_seed_queue_is_not_uploaded_as_ours(app_db, query):
    from babytracker_client import BabyTrackerLocalDatabase
    db = BabyTrackerLocalDatabase(str(app_db))
    db.enqueue_transaction(0, b64(diaper("FROM-SEEDING-PHONE")))
    db.clear_sync_state()
    assert db.get_pending_transactions() == []
