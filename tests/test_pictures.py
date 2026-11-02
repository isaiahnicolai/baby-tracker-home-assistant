"""The newest pictures of a baby (BabyTracker.get_pictures / get_latest_picture)."""
from helpers import COMMON, AVA, TWIN


def picture(object_id, file_name=None, media_type=0, deleted=False, stamp="2026-10-30 12:00:00 +0000"):
    return {"objectID": object_id, "timestamp": stamp, "mediaType": media_type, "fileName": file_name or object_id,
            "deleted": deleted}


def entry(kind, object_id, time, pictures, baby=AVA, **fields):
    return {**COMMON, "BCObjectType": kind, "objectID": object_id, "time": time, "baby": {"objectID": baby},
            "pictureNote": pictures, **fields}


def test_no_pictures_is_none_and_empty(tracker):
    assert tracker.get_latest_picture(AVA) is None
    assert tracker.get_pictures(AVA) == []


def test_latest_picture_is_the_newest_entrys(apply, tracker, tmp_path):
    pics = tmp_path / "pics"
    pics.mkdir()
    (pics / "P-OLD.jpg").write_bytes(b"old")
    (pics / "P-NEW.jpg").write_bytes(b"new")
    (pics / "P-NEW__thumbnail.jpg").write_bytes(b"thumb")
    apply(entry("Joy", "J-OLD", "2026-10-30 08:00:00 +0000", [picture("P-OLD")]))
    apply(entry("Joy", "J-NEW", "2026-10-30 11:00:00 +0000", [picture("P-NEW")], note="first steps"))
    apply(entry("Joy", "J-NONE", "2026-10-30 11:30:00 +0000", []))  # newer but without a picture

    latest = tracker.get_latest_picture(AVA, picture_dir=str(pics))
    assert latest["picture_id"] == "P-NEW"
    assert (latest["object_type"], latest["kind"]) == ("Joy", "joy")
    assert latest["object_id"] == "J-NEW" and latest["path"].endswith("P-NEW.jpg")
    assert latest["thumbnail_path"].endswith("P-NEW__thumbnail.jpg")
    assert latest["note"] == "first steps"
    assert latest["time"].startswith("2026-10-30T06:00:00")

    listed = tracker.get_pictures(AVA, limit=10, picture_dir=str(pics))
    assert [p["picture_id"] for p in listed] == ["P-NEW", "P-OLD"]
    assert listed[1]["thumbnail_path"] is None
    assert tracker.get_pictures(AVA, limit=1, picture_dir=str(pics))[0]["picture_id"] == "P-NEW"


def test_files_not_downloaded_yet_have_no_path(apply, tracker, tmp_path):
    apply(entry("Diaper", "D1", "2026-10-30 08:00:00 +0000", [picture("P1")], status=1))
    latest = tracker.get_latest_picture(AVA, picture_dir=str(tmp_path))
    assert latest["picture_id"] == "P1"
    assert latest["path"] is None and latest["thumbnail_path"] is None
    assert latest["object_type"] == "Diaper" and latest["kind"] == "poopy diaper"


def test_the_sync_picture_directory_is_the_default(apply, tracker, tmp_path):
    (tmp_path / "P1.jpg").write_bytes(b"x")
    apply(entry("Joy", "J1", "2026-10-30 08:00:00 +0000", [picture("P1")]))
    tracker.db.picture_dir = str(tmp_path)
    assert tracker.get_latest_picture(AVA)["path"] == str(tmp_path / "P1.jpg")


def test_pictures_are_per_baby_and_found_on_any_activity_table(apply, tracker, tmp_path):
    apply(entry("Joy", "J1", "2026-10-30 08:00:00 +0000", [picture("P1")]))
    apply(entry("OtherActivity", "OA1", "2026-10-30 09:00:00 +0000", [picture("P2")], baby=TWIN, duration=10,
                desc={"objectID": "TT", "name": "Tummy Time"}))
    assert tracker.get_latest_picture(AVA)["object_type"] == "Joy"
    twin = tracker.get_latest_picture(TWIN)
    assert (twin["object_type"], twin["kind"]) == ("OtherActivity", "tummy time 10 min")


def test_several_pictures_on_one_entry_and_videos_and_deleted(apply, tracker, tmp_path):
    apply(entry("Joy", "J1", "2026-10-30 08:00:00 +0000", [
        picture("P1", stamp="2026-10-30 09:00:00 +0000"),
        picture("P2", stamp="2026-10-30 10:00:00 +0000"),
        picture("V1", media_type=1),
        picture("GONE", deleted=True),
    ]))
    listed = tracker.get_pictures(AVA, picture_dir=str(tmp_path))
    assert [p["picture_id"] for p in listed] == ["P2", "P1"]


def test_deleting_the_entry_drops_its_picture(apply, tracker):
    apply(entry("Joy", "J1", "2026-10-30 08:00:00 +0000", [picture("P1")]))
    apply({**COMMON, "BCObjectType": "Joy", "objectID": "J1"}, op=2)
    assert tracker.get_latest_picture(AVA) is None
