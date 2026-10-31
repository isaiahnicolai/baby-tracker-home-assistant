"""
The rest of the sync protocol: activity pictures, group resets, the merge
echoes the app sends back (conflicts, relives, deletes), join cleanup, logout.
"""
import io
import os
import sqlite3
import zipfile

import pytest

from babytracker_client import AccountResetError, BabyTrackerAPI, BabyTrackerLocalDatabase
from helpers import EMAIL, EVERLY, IPHONE, MILESTONE, OURS, TWIN, b64, unb64
from test_sync import baby, diaper, merge


def picture(object_id, file_name, media_type=0, deleted=False):
    return {"BCObjectType": "Picture", "objectID": object_id, "timestamp": "2026-10-30 12:00:00 +0000",
            "fileName": file_name, "mediaType": media_type, "activityID": "F1", "deleted": deleted,
            "attached": False, "newFlage": False}


def formula(object_id="F1", pictures=(), timestamp="2026-10-30 12:00:00 +0000"):
    return {"BCObjectType": "Formula", "objectID": object_id, "timestamp": timestamp,
            "time": "2026-10-30 11:00:00 +0000", "note": "", "pictureLoaded": True,
            "pictureNote": list(pictures), "baby": {"objectID": EVERLY},
            "amount": {"value": 4, "englishMeasure": True, "BCObjectType": "VolumeMeasure"}}


def pending(tracker):
    """What is queued for upload, decoded: [(OpCode, record)]."""
    return [(op, unb64(b)) for _, op, b in tracker.db.get_pending_transactions()]


# ----- activity pictures ---------------------------------------------------------

def test_merging_an_activity_records_its_pictures_and_queues_the_files(apply, query):
    apply(formula(pictures=[picture("PIC1", "abc"), picture("VID1", "clip", media_type=1)]))
    assert query("SELECT ID, ActivityID, Type, FileName FROM Picture ORDER BY ID") == [
        ("PIC1", "F1", 0, "abc"), ("VID1", "F1", 1, "clip")]
    assert query("SELECT PhotoFile, DownloadCount FROM PhotoDownloadList ORDER BY PhotoFile") == [
        ("abc.jpg", 0), ("abc__thumbnail.jpg", 0), ("clip.mp4", 0), ("clip__thumbnail.jpg", 0)]


def test_a_picture_marked_deleted_is_removed(apply, query):
    apply(formula(pictures=[picture("PIC1", "abc"), picture("PIC2", "def")]))
    apply(formula(pictures=[picture("PIC1", "abc", deleted=True), picture("PIC2", "def")],
                  timestamp="2026-10-30 13:00:00 +0000"), op=1)
    assert query("SELECT ID FROM Picture") == [("PIC2",)]
    assert query("SELECT HasPicture FROM Formula WHERE ID='F1'") == [(1,)]


def test_sync_downloads_the_picture_files(tracker, server, query, tmp_path):
    server.pictures = {"abc.jpg": b"full size", "abc__thumbnail.jpg": b"thumb"}
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "abc")])])
    pictures = tmp_path / "pictures"

    result = tracker.sync(picture_dir=str(pictures))

    assert result["status"] == "success"
    assert result["downloaded_pictures"] == 2
    assert (pictures / "abc.jpg").read_bytes() == b"full size"
    assert (pictures / "abc__thumbnail.jpg").read_bytes() == b"thumb"
    assert query("SELECT COUNT(*) FROM PhotoDownloadList") == [(0,)]


def test_sync_runs_merge_then_photos_then_upload(tracker, server, tmp_path):
    server.online = False
    tracker.add_diaper(EVERLY, None)  # queued, can't be sent yet
    server.online = True
    server.pictures = {"abc.jpg": b"x", "abc__thumbnail.jpg": b"x"}
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "abc")])])
    server.requests.clear()

    tracker.sync(picture_dir=str(tmp_path / "pictures"))

    steps = [(m, "picture" if "/picture/" in p else "transaction") for m, p in server.requests
             if p.startswith(("/account/picture", "/account/transaction"))]
    assert steps[0] == ("GET", "transaction")
    assert steps[-1] == ("POST", "transaction")
    assert [s for s in steps if s[1] == "picture"] and steps.index(("GET", "picture")) < steps.index(("POST", "transaction"))


def test_pictures_are_only_downloaded_when_asked(tracker, server, query):
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "abc")])])
    tracker.sync()
    assert not [p for _, p in server.requests if p.startswith("/account/picture")]
    assert query("SELECT COUNT(*) FROM PhotoDownloadList") == [(2,)]


def test_a_file_that_keeps_failing_is_dropped_after_ten_attempts(tracker, server, query, tmp_path):
    server.pictures = {"abc__thumbnail.jpg": b"thumb"}  # the full size picture 404s
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "abc")])])
    pictures = str(tmp_path / "pictures")

    for attempt in range(1, 10):
        tracker.sync(picture_dir=pictures)
        assert query("SELECT PhotoFile, DownloadCount FROM PhotoDownloadList") == [("abc.jpg", attempt)]
    tracker.sync(picture_dir=pictures)
    assert query("SELECT COUNT(*) FROM PhotoDownloadList") == [(0,)]

    tries = [p for _, p in server.requests if p == "/account/picture/abc.jpg"]
    assert len(tries) == 10
    tracker.sync(picture_dir=pictures)
    assert len([p for _, p in server.requests if p == "/account/picture/abc.jpg"]) == 10
    # The thumbnail was fine all along
    assert os.path.exists(os.path.join(pictures, "abc__thumbnail.jpg"))


def test_going_offline_does_not_use_up_attempts(tracker, server, query, tmp_path):
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "abc")])])
    pictures = str(tmp_path / "pictures")
    tracker.sync(picture_dir=pictures)  # downloads fail: 404
    server.online = False
    result = tracker.sync(picture_dir=pictures)
    assert result["status"] == "error"
    assert query("SELECT DownloadCount FROM PhotoDownloadList ORDER BY PhotoFile") == [(1,), (1,)]


def test_deleting_the_activity_removes_its_pictures_and_files(tracker, server, query, tmp_path):
    server.pictures = {"abc.jpg": b"x", "abc__thumbnail.jpg": b"x"}
    activity = formula(pictures=[picture("PIC1", "abc")])
    server.publish(IPHONE, [activity])
    pictures = tmp_path / "pictures"
    tracker.sync(picture_dir=str(pictures))
    assert query("SELECT COUNT(*) FROM Picture") == [(1,)]

    server.publish(IPHONE, [activity], op=2)
    tracker.sync(picture_dir=str(pictures))

    assert query("SELECT COUNT(*) FROM Picture") == [(0,)]
    assert query("SELECT COUNT(*) FROM Formula WHERE ID='F1'") == [(0,)]
    assert list(pictures.iterdir()) == []


def test_deleting_an_activity_drops_its_queued_downloads(apply, query):
    activity = formula(pictures=[picture("PIC1", "abc")])
    apply(activity)
    apply(activity, op=2)
    assert query("SELECT COUNT(*) FROM Picture") == [(0,)]
    assert query("SELECT COUNT(*) FROM PhotoDownloadList") == [(0,)]


def test_picture_names_cannot_escape_the_picture_folder(tracker, server, tmp_path):
    server.pictures = {"../evil.jpg": b"x"}
    server.publish(IPHONE, [formula(pictures=[picture("PIC1", "../evil")])])
    pictures = tmp_path / "pictures"
    tracker.sync(picture_dir=str(pictures))
    assert not (tmp_path / "evil.jpg").exists()


def test_baby_picture_gets_a_jpg_extension_unless_it_has_one(tracker, server, tmp_path):
    server.pictures = {"BABYPIC.jpg": b"j" * 200, "other.png": b"p" * 200}
    saved = tracker.download_baby_picture("BABYPIC", str(tmp_path))
    assert os.path.basename(saved) == "BABYPIC.jpg"
    saved = tracker.download_baby_picture("other.png", str(tmp_path))
    assert os.path.basename(saved) == "other.png"
    asked = [p for _, p in server.requests if p.startswith("/account/picture/")]
    assert asked == ["/account/picture/BABYPIC.jpg", "/account/picture/other.png"]


# ----- picture upload --------------------------------------------------------------

def test_upload_picture_posts_multipart_form_data(tracker, server, tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8JPEGDATA")

    assert tracker.api.upload_picture(str(photo)) is True

    headers, body = server.picture_uploads[0]
    boundary = "__BABY_TRACKER_BOUNDARY____Photo__"
    assert headers["Content-Type"] == f"multipart/form-data; boundary={boundary}"
    assert f"--{boundary}".encode() in body and f"--{boundary}--".encode() in body
    assert b'name="picture"' in body and b'filename="photo.jpg"' in body
    assert b"Content-Type: image/jpeg" in body and b"\xff\xd8JPEGDATA" in body


# ----- group reset -----------------------------------------------------------------

def test_login_to_a_different_account_is_a_group_reset(tracker, server):
    server.account_id = 2
    with pytest.raises(AccountResetError):
        tracker.api.login(EMAIL, "pw", OURS)
    # and syncing does not carry on regardless
    server.expire_session_once = True
    with pytest.raises(AccountResetError):
        tracker.sync()


def test_clearing_sync_state_lets_the_new_account_in(tracker, server):
    server.account_id = 2
    with pytest.raises(AccountResetError):
        tracker.api.login(EMAIL, "pw", OURS)
    tracker.db.clear_sync_state()
    assert tracker.api.login(EMAIL, "pw", OURS)
    assert tracker.db.get_account_id() == "2"


def test_force_resync_rejoins_a_reset_group(tracker, server, app_db):
    server.account_id = 2
    with pytest.raises(AccountResetError):
        tracker.api.login(EMAIL, "pw", OURS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(app_db, "EasyLog.db")
    server.seed = buf.getvalue()

    result = tracker.force_resync(EMAIL, "pw", OURS)

    assert result["status"] == "success"
    assert tracker.db.get_account_id() == "2"


def test_the_first_login_records_the_account(tracker):
    assert tracker.db.get_account_id() == "1"


# ----- merge echoes ------------------------------------------------------------------

def test_losing_a_name_clash_uploads_a_conflict_record(tracker, apply, server):
    newer = baby("OTHER-ID", "Everly", timestamp="2030-01-01 00:00:00 +0000")
    assert apply(newer) == "rejected"
    tracker.api.upload_pending()

    sent = server.uploads[-1]
    assert sent["OPCode"] == "4"
    record = sent["record"]
    assert record["BCObjectType"] == "ConflictRecord"
    assert record["winner"]["objectID"] == EVERLY and record["winner"]["name"] == "Everly"
    assert record["winner"]["BCObjectType"] == "Baby"
    assert record["loser"]["objectID"] == "OTHER-ID"
    assert record["objectID"] and record["timestamp"]


def test_a_selection_name_clash_uploads_a_conflict_record_too(tracker, apply, server):
    newer = {"BCObjectType": "MilestoneSelection", "objectID": "OTHER-MS", "name": "First smile",
             "timestamp": "2030-01-01 00:00:00 +0000", "forAge": 2}
    assert apply(newer) == "rejected"
    tracker.api.upload_pending()

    record = server.uploads[-1]["record"]
    assert server.uploads[-1]["OPCode"] == "4"
    assert record["winner"]["BCObjectType"] == "MilestoneSelection"
    assert record["winner"]["objectID"] == MILESTONE and record["winner"]["forAge"] == 2
    assert record["loser"]["objectID"] == "OTHER-MS"


def test_a_refused_delete_uploads_a_relive(tracker, apply, server):
    tracker.add_diaper(TWIN, None)
    server.uploads.clear()
    assert apply(baby(TWIN, "Ann Marie"), op=2) == "rejected"
    tracker.api.upload_pending()

    sent = server.uploads[-1]
    assert sent["OPCode"] == "3"
    assert sent["record"]["BCObjectType"] == "Baby"
    assert sent["record"]["objectID"] == TWIN and sent["record"]["name"] == "Ann Marie"
    assert "dob" in sent["record"] and "gender" in sent["record"]


def test_a_merged_delete_is_uploaded_again(tracker, server, query):
    server.publish(IPHONE, [diaper("D1")])
    tracker.sync()
    server.uploads.clear()
    server.publish(IPHONE, [diaper("D1")], op=2)

    tracker.sync()

    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='D1'") == [(0,)]
    assert [(u["OPCode"], u["record"]["objectID"], u["record"]["BCObjectType"]) for u in server.uploads] == [
        ("2", "D1", "Diaper")]


def test_a_delete_that_changed_nothing_is_not_repeated(apply, tracker):
    assert apply(diaper("NEVER-HAD-IT"), op=2) == "ignored"
    assert pending(tracker) == []


def test_a_delete_swallowed_by_a_relive_is_not_repeated(apply, tracker):
    apply(baby(TWIN, "Ann Marie"), op=3)
    assert apply(baby(TWIN, "Ann Marie"), op=2) == "success"
    assert pending(tracker) == []


def test_nothing_is_echoed_while_joining(tracker, apply):
    tracker.api.transaction_handler.joining = True
    apply(diaper("D1"))
    apply(diaper("D1"), op=2)
    apply(baby("OTHER-ID", "Everly", timestamp="2030-01-01 00:00:00 +0000"))
    tracker.add_diaper(TWIN, None)
    tracker.api.upload_pending()
    apply(baby(TWIN, "Ann Marie"), op=2)
    assert pending(tracker) == []


def test_our_own_transactions_coming_back_are_not_echoed(tracker, server, query):
    server.publish(OURS, [diaper("D1")])
    tracker.sync()
    server.publish(OURS, [diaper("D1")], op=2)
    server.uploads.clear()
    tracker.sync()
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='D1'") == [(0,)]
    assert server.uploads == []


def test_our_own_relive_coming_back_does_not_arm_the_next_delete(tracker, server, query):
    server.publish(OURS, [baby(TWIN, "Ann Marie")], op=3)
    tracker.sync()
    assert query("SELECT COUNT(*) FROM ReliveList") == [(0,)]


def test_joining_a_group_does_not_echo(app_db, server, tmp_path):
    """join_group merges with the flag set, and clears it afterwards."""
    from babytracker_client import BabyTracker
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(app_db, "EasyLog.db")
    server.seed = buf.getvalue()
    server.publish(IPHONE, [diaper("D1")])
    server.publish(IPHONE, [diaper("D1")], op=2)

    tracker = BabyTracker(db_path=str(tmp_path / "joined.db"), time_zone="America/Chicago")
    assert tracker.authenticate(EMAIL, "pw", OURS)["status"] == "success"

    assert pending(tracker) == []
    assert tracker.api.transaction_handler.joining is False


# ----- join cleanup and seed -------------------------------------------------------------

def test_clearing_sync_state_empties_every_table_the_app_clears(app_db, query):
    conn = sqlite3.connect(app_db)
    conn.execute("INSERT INTO PhotoList VALUES ('a.jpg')")
    conn.execute("INSERT INTO MergedTransaction VALUES ('SEEDING-DEVICE', 12)")
    conn.execute("INSERT INTO ReliveList VALUES ('X')")
    conn.execute("INSERT INTO PhotoDownloadList VALUES ('b.jpg', 3)")
    conn.execute("INSERT INTO TransactionLog (OpCode, Log) VALUES (0, 'x')")
    conn.commit()
    conn.close()

    BabyTrackerLocalDatabase(str(app_db)).clear_sync_state()

    for table in ("PhotoList", "MergedTransaction", "ReliveList", "PhotoDownloadList", "TransactionLog"):
        assert query(f"SELECT COUNT(*) FROM {table}") == [(0,)], table


def seed_zip(app_db, tmp_path, entries):
    """A seed zip holding copies of the database whose babies are named by `entries` {zip path: baby name}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, name in entries.items():
            copy = tmp_path / ("seed-" + path.replace("/", "_"))
            conn = sqlite3.connect(app_db)
            conn.backup(sqlite3.connect(copy))
            conn.close()
            db = sqlite3.connect(copy)
            db.execute("DELETE FROM Baby WHERE ID != ?", (EVERLY,))
            db.execute("UPDATE Baby SET Name = ?", (name,))
            db.commit()
            db.close()
            z.write(copy, path)
    return buf.getvalue()


def seeded_baby(server, tmp_path):
    api = BabyTrackerAPI(db_path=str(tmp_path / "joined.db"))
    api.login(EMAIL, "pw", OURS)
    return api.download_seed_data()["baby_info"]["name"]


def test_the_seed_database_is_easylog_db(app_db, server, tmp_path):
    server.seed = seed_zip(app_db, tmp_path, {"aaa.db": "Wrong", "nested/EasyLog.db": "Right", "zzz.db": "Wrong"})
    assert seeded_baby(server, tmp_path) == "Right"


def test_any_db_will_do_when_there_is_no_easylog_db(app_db, server, tmp_path):
    server.seed = seed_zip(app_db, tmp_path, {"other.db": "Fallback"})
    assert seeded_baby(server, tmp_path) == "Fallback"


# ----- logout --------------------------------------------------------------------------------

def test_logout_deletes_the_session(tracker, server):
    assert tracker.api.logout() is True
    assert ("DELETE", "/session") in server.requests
    assert tracker.api.session_id is None and not tracker.api.is_authenticated
