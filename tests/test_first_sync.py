"""
The first sync of an account: joining without replaying the history straight
away, and replaying it a page at a time instead of a commit per record.
"""
import io
import sqlite3
import zipfile

import pytest
from babytracker_client import BabyTracker, BabyTrackerLocalDatabase
from babytracker_client.api import JOIN_PENDING
from helpers import EMAIL, IPHONE, OURS
from test_sync import diaper, progress
from test_sync_complete import pending


def joined_tracker(app_db, server, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(app_db, "EasyLog.db")
    server.seed = buf.getvalue()
    return BabyTracker(db_path=str(tmp_path / "joined.db"), time_zone="America/Chicago")


def test_joining_without_the_history_leaves_it_to_the_first_sync(app_db, server, tmp_path):
    server.publish(IPHONE, [diaper("D1"), diaper("D2")])
    tracker = joined_tracker(app_db, server, tmp_path)

    result = tracker.authenticate(EMAIL, "pw", OURS, sync_history=False)

    assert result["status"] == "success"
    assert tracker.is_authenticated
    # Nothing replayed yet, and the join is recorded as unfinished
    assert tracker.db.get_sync_state(JOIN_PENDING) == "1"
    assert not any(path.endswith("/account/transaction/%s/0" % IPHONE) for _, path in server.requests)

    tracker.sync()

    conn = sqlite3.connect(tracker.db_path)
    assert conn.execute("SELECT COUNT(*) FROM Diaper WHERE ID IN ('D1','D2')").fetchone() == (2,)
    conn.close()
    assert tracker.db.get_sync_state(JOIN_PENDING) is None
    assert tracker.api.transaction_handler.joining is False


def test_the_deferred_replay_still_counts_as_joining_so_nothing_is_echoed(app_db, server, tmp_path):
    """The app sends no conflict/relive/delete echoes while joining; a later replay must not either."""
    server.publish(IPHONE, [diaper("D1")])
    server.publish(IPHONE, [diaper("D1")], op=2)  # a merged delete is normally repeated under our device
    tracker = joined_tracker(app_db, server, tmp_path)
    tracker.authenticate(EMAIL, "pw", OURS, sync_history=False)

    tracker.sync()

    assert pending(tracker) == []
    assert tracker.db.get_sync_state(JOIN_PENDING) is None


def test_a_blocked_replay_keeps_the_join_open(app_db, server, tmp_path):
    server.publish(IPHONE, [diaper("OK1"), diaper("BAD", time="not a date"), diaper("OK2")])
    tracker = joined_tracker(app_db, server, tmp_path)
    tracker.authenticate(EMAIL, "pw", OURS, sync_history=False)

    tracker.sync()
    assert tracker.db.get_sync_state(JOIN_PENDING) == "1"  # stopped at BAD, so not finished
    tracker.sync()
    tracker.sync()  # BAD is skipped on the third attempt
    assert tracker.db.get_sync_state(JOIN_PENDING) is None


def test_a_page_is_one_transaction_but_a_failing_record_is_rolled_back_alone(tracker, server, query):
    server.publish(IPHONE, [diaper("OK1"), diaper("BAD", time="not a date"), diaper("OK2")])
    tracker.sync()
    assert progress(query) == 1
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID='OK1'") == [(1,)]
    assert query("SELECT COUNT(*) FROM Diaper WHERE ID IN ('BAD','OK2')") == [(0,)]


def test_batch_commits_once_and_discards_only_the_marked_item(app_db):
    db = BabyTrackerLocalDatabase(str(app_db))
    with db.batch() as batch:
        with batch.item():
            db.upsert_record("Diaper", {"objectID": "KEEP", "timestamp": "2026-10-30 10:00:00 +0000",
                                        "time": "2026-10-30 10:00:00 +0000", "status": 0, "amount": 2,
                                        "baby": {"objectID": "ID-AVA", "name": "Ava"}})
        with batch.item() as it:
            db.upsert_record("Diaper", {"objectID": "DROP", "timestamp": "2026-10-30 10:00:00 +0000",
                                        "time": "2026-10-30 10:00:00 +0000", "status": 0, "amount": 2,
                                        "baby": {"objectID": "ID-AVA", "name": "Ava"}})
            it.discard()
        # Not visible to another connection until the batch commits
        other = sqlite3.connect(app_db)
        assert other.execute("SELECT COUNT(*) FROM Diaper WHERE ID='KEEP'").fetchone() == (0,)
        other.close()

    conn = sqlite3.connect(app_db)
    assert conn.execute("SELECT ID FROM Diaper WHERE ID IN ('KEEP','DROP')").fetchall() == [("KEEP",)]
    conn.close()
    assert db._batch is None


def test_an_exception_inside_a_batch_rolls_the_page_back(app_db):
    db = BabyTrackerLocalDatabase(str(app_db))
    with pytest.raises(RuntimeError):
        with db.batch() as batch:
            with batch.item():
                db.set_sync_state("Probe", "1")
            raise RuntimeError("boom")
    assert db.get_sync_state("Probe") is None
    assert db._batch is None


def test_connections_use_normal_synchronous_in_wal_mode(app_db):
    from babytracker_client import dbconn
    conn = dbconn.connect(str(app_db))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    conn.close()


def test_needs_first_sync_until_the_history_is_imported(tmp_path, tracker):
    from babytracker_client import BabyTracker
    from babytracker_client.api import JOIN_PENDING

    assert BabyTracker(db_path=str(tmp_path / "none.db")).needs_first_sync() is True  # no database yet
    assert tracker.needs_first_sync() is False  # a joined, fully synced database
    tracker.db.set_sync_state(JOIN_PENDING, "1")  # joined, history not replayed yet
    assert tracker.needs_first_sync() is True
