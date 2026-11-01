"""Solids, activities, and the guarantees the Home Assistant controls rely on: no overlapping writes, patient database connections."""
import sqlite3
import threading
import time

from helpers import EVERLY, TWIN

BANANA = "FOOD-BANANA"
TUMMY = "ACTIVITY-TUMMY"


def test_solids_are_logged_with_the_chosen_food(tracker, server, query, app_db):
    conn = sqlite3.connect(app_db)
    conn.execute("INSERT INTO OtherFeedSelection (ID, Name, IsBottle) VALUES (?, 'Banana', 0)", (BANANA,))
    conn.commit()
    conn.close()

    assert [(f["id"], f["name"]) for f in tracker.get_other_feed_selections()] == [(BANANA, "Banana")]

    result = tracker.add_other_feed(EVERLY, None, BANANA, 2, "tbsp", True, "first taste")
    assert result["status"] == "success"
    record = server.uploads[-1]["record"]
    assert record["BCObjectType"] == "OtherFeed"
    assert record["baby"]["objectID"] == EVERLY and record["feedType"]["objectID"] == BANANA
    assert query("SELECT BabyID, TypeID, Amount, IsEnglishScale, Unit, Note FROM OtherFeed") == [
        (EVERLY, BANANA, 2.0, 1, "tbsp", "first taste")]

    # Metric amounts are stored as such
    tracker.add_other_feed(TWIN, None, BANANA, 30, "g", False)
    assert query("SELECT IsEnglishScale, Unit FROM OtherFeed WHERE BabyID=?", (TWIN,)) == [(0, "g")]


def test_solids_of_an_unknown_food_are_refused_not_invented(tracker, query):
    result = tracker.add_other_feed(EVERLY, None, "FOOD-NOPE", 1, "tbsp", True)
    assert result["status"] == "error"
    assert query("SELECT COUNT(*) FROM OtherFeed") == [(0,)]


def test_an_activity_reuses_the_accounts_description_of_that_name(tracker, server, query, app_db):
    conn = sqlite3.connect(app_db)
    conn.execute("INSERT INTO OtherActivityDesc (ID, Name, Description) VALUES (?, 'Tummy Time', '')", (TUMMY,))
    conn.commit()
    conn.close()

    for _ in range(2):
        assert tracker.add_activity(EVERLY, None, "tummy time", 15)["status"] == "success"
    assert server.uploads[-1]["record"]["desc"]["objectID"] == TUMMY
    assert query("SELECT DescID, Duration FROM OtherActivity") == [(TUMMY, 15), (TUMMY, 15)]
    assert query("SELECT COUNT(*) FROM OtherActivityDesc") == [(1,)]

    # A name the account hasn't used yet gets a description of its own
    assert tracker.add_activity(EVERLY, None, "Reading", 5)["status"] == "success"
    assert query("SELECT Name FROM OtherActivityDesc ORDER BY Name") == [("Reading",), ("Tummy Time",)]


def test_last_activity_is_the_latest_one(tracker):
    assert tracker.get_last_activity(EVERLY) is None
    tracker.add_activity(EVERLY, "2026-03-01 09:00:00 +0000", "Tummy Time", 10)
    tracker.add_activity(EVERLY, "2026-03-01 10:00:00 +0000", "Reading", 5)
    last = tracker.get_last_activity(EVERLY)
    assert (last["activity_name"], last["duration"]) == ("Reading", 5)
    assert tracker.get_last_activity(TWIN) is None


def test_a_sync_and_a_write_never_run_at_the_same_time(tracker):
    active = []
    overlaps = []

    def watched(original):
        def run(*args, **kwargs):
            active.append(1)
            if len(active) > 1:
                overlaps.append(True)
            time.sleep(0.15)  # long enough for the other thread to arrive
            try:
                return original(*args, **kwargs)
            finally:
                active.pop()
        return run

    tracker.api.sync_transactions = watched(tracker.api.sync_transactions)
    tracker.api.post_diaper = watched(tracker.api.post_diaper)

    sync = threading.Thread(target=tracker.sync)
    write = threading.Thread(target=lambda: tracker.add_diaper(EVERLY, None, pee=True))
    sync.start()
    time.sleep(0.05)
    write.start()
    sync.join()
    write.join()

    assert not overlaps
    assert tracker.pending_upload_count() == 0  # and both did their work


def test_connections_wait_for_a_lock_and_use_wal(app_db):
    from babytracker_client import dbconn

    first = dbconn.connect(app_db)
    assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert first.execute("PRAGMA busy_timeout").fetchone()[0] == dbconn.BUSY_TIMEOUT_SECONDS * 1000

    # While one connection holds a write open, another waits for it instead of failing
    first.execute("BEGIN IMMEDIATE")
    first.execute("INSERT INTO OtherFeedSelection (ID, Name, IsBottle) VALUES ('FIRST', 'First', 0)")
    errors = []

    def second_write():
        second = dbconn.connect(app_db)
        try:
            second.execute("INSERT INTO OtherFeedSelection (ID, Name, IsBottle) VALUES ('SECOND', 'Second', 0)")
            second.commit()
        except sqlite3.OperationalError as err:
            errors.append(err)
        finally:
            second.close()

    thread = threading.Thread(target=second_write)
    thread.start()
    time.sleep(0.3)
    assert thread.is_alive()  # waiting, not failed
    first.commit()
    thread.join(timeout=5)
    first.close()

    assert not errors
    check = sqlite3.connect(app_db)
    assert check.execute("SELECT ID FROM OtherFeedSelection ORDER BY ID").fetchall() == [("FIRST",), ("SECOND",)]
    check.close()


def test_a_readers_view_is_not_blocked_by_a_writer(app_db):
    from babytracker_client import dbconn

    writer = dbconn.connect(app_db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO OtherFeedSelection (ID, Name, IsBottle) VALUES ('PENDING', 'Pending', 0)")

    reader = dbconn.connect(app_db)
    started = time.monotonic()
    assert reader.execute("SELECT COUNT(*) FROM Baby").fetchone()[0] == 2
    assert time.monotonic() - started < 1  # WAL: no waiting on the writer
    reader.close()
    writer.rollback()
    writer.close()
