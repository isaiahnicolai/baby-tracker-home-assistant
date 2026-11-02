"""Attaching photos to entries (BabyTracker.add_joy / attach_photo) the way the app does."""
import os

import pytest
from helpers import AVA

pytest.importorskip("PIL")

from babytracker_client.photos import PhotoError  # noqa: E402
from PIL import Image  # noqa: E402


def make_image(path, fmt="PNG", size=(800, 600)):
    Image.new("RGB", size, (200, 40, 40)).save(path, fmt)
    return str(path)


def uploaded_names(server):
    """File names of the multipart uploads the server received, in order."""
    names = []
    for headers, body in server.picture_uploads:
        assert headers["Content-Type"].startswith("multipart/form-data")
        text = body[:300].decode("latin-1")
        names.append(text.split('filename="', 1)[1].split('"', 1)[0])
    return names


@pytest.fixture
def pics(tmp_path):
    return str(tmp_path / "pictures")


def test_joy_with_a_photo_has_the_apps_wire_format(tracker, server, query, tmp_path, pics):
    source = make_image(tmp_path / "snap.png")
    result = tracker.add_joy(AVA, note="first smile", photo_path=source, picture_dir=pics)
    assert result["status"] == "success" and result["queued"] is False

    record = server.uploads[-1]["record"]
    assert (record["BCObjectType"], record["note"], record["baby"]["objectID"]) == ("Joy", "first smile", AVA)
    assert record["pictureLoaded"] is True and len(record["pictureNote"]) == 1
    picture = record["pictureNote"][0]
    assert picture["BCObjectType"] == "Picture"
    assert picture["activityID"] == record["objectID"] == result["objectID"]
    assert picture["mediaType"] == "MediaTypePicture" and picture["deleted"] is False
    assert picture["objectID"] == picture["fileName"]

    # The files: <fileName>.jpg and <fileName>__thumbnail.jpg, both real JPEGs
    name = picture["fileName"]
    assert sorted(os.listdir(pics)) == sorted([f"{name}.jpg", f"{name}__thumbnail.jpg"])
    with Image.open(os.path.join(pics, f"{name}.jpg")) as full:
        assert full.format == "JPEG" and full.size == (800, 600)
    with Image.open(os.path.join(pics, f"{name}__thumbnail.jpg")) as thumb:
        assert thumb.format == "JPEG" and max(thumb.size) == 400 and thumb.size == (400, 300)

    # Both files were uploaded, before the record
    assert uploaded_names(server) == [f"{name}.jpg", f"{name}__thumbnail.jpg"]
    assert server.requests.index(("POST", "/account/picture")) < server.requests.index(("POST", "/account/transaction"))
    assert query("SELECT COUNT(*) FROM PhotoList") == [(0,)]

    # Stored locally like a record that came from the phone
    assert query("SELECT HasPicture FROM Joy WHERE ID=?", (result["objectID"],)) == [(1,)]
    assert query("SELECT ID, ActivityID, Type, FileName FROM Picture") == [(name, result["objectID"], 0, name)]
    assert query("SELECT COUNT(*) FROM PhotoDownloadList") == [(0,)]


def test_the_new_photo_is_the_latest_picture(tracker, tmp_path, pics):
    tracker.add_joy(AVA, note="older", photo_path=make_image(tmp_path / "a.png"), picture_dir=pics,
                    time_str="2026-10-30 08:00:00 +0000")
    newer = tracker.add_joy(AVA, note="newer", photo_path=make_image(tmp_path / "b.png"), picture_dir=pics,
                            time_str="2026-10-30 09:00:00 +0000")
    latest = tracker.get_latest_picture(AVA)  # the folder the write used is remembered
    assert latest["object_id"] == newer["objectID"] and latest["object_type"] == "Joy"
    assert latest["note"] == "newer"
    assert os.path.isfile(latest["path"]) and latest["path"].endswith(".jpg")
    assert os.path.isfile(latest["thumbnail_path"])
    assert [p["note"] for p in tracker.get_pictures(AVA, picture_dir=pics)] == ["newer", "older"]


def test_joy_without_a_photo(tracker, server, query):
    result = tracker.add_joy(AVA, note="giggles")
    assert result["status"] == "success"
    assert server.uploads[-1]["record"]["pictureNote"] == []
    assert server.picture_uploads == []
    assert query("SELECT HasPicture FROM Joy") == [(0,)]


def test_a_jpeg_that_fits_is_copied_as_is(tracker, tmp_path, pics):
    source = make_image(tmp_path / "ok.jpg", "JPEG")
    tracker.add_joy(AVA, photo_path=source, picture_dir=pics)
    stored = next(f for f in os.listdir(pics) if not f.endswith("__thumbnail.jpg"))
    assert open(os.path.join(pics, stored), "rb").read() == open(source, "rb").read()


def test_a_large_photo_is_scaled_down(tracker, tmp_path, pics):
    tracker.add_joy(AVA, photo_path=make_image(tmp_path / "big.png", size=(3000, 1500)), picture_dir=pics)
    stored = next(f for f in os.listdir(pics) if not f.endswith("__thumbnail.jpg"))
    with Image.open(os.path.join(pics, stored)) as full:
        assert full.size == (2048, 1024)


def test_offline_keeps_the_files_pending_and_sync_retries_before_the_record(tracker, server, query, tmp_path, pics):
    server.online = False
    result = tracker.add_joy(AVA, photo_path=make_image(tmp_path / "snap.png"), picture_dir=pics)
    assert result["status"] == "success" and result["queued"] is True
    assert len(query("SELECT PhotoFile FROM PhotoList")) == 2
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(1,)]
    assert server.picture_uploads == [] and server.uploads == []

    server.online = True
    server.requests.clear()
    sync = tracker.sync()
    assert sync["uploaded_transactions"] == 1
    name = server.uploads[-1]["record"]["pictureNote"][0]["fileName"]
    assert uploaded_names(server) == [f"{name}.jpg", f"{name}__thumbnail.jpg"]
    posts = [path for method, path in server.requests if method == "POST"]
    assert posts == ["/account/picture", "/account/picture", "/account/transaction"]
    assert query("SELECT COUNT(*) FROM PhotoList") == [(0,)]


def test_a_failed_upload_keeps_the_record_queued_too(tracker, server, query, tmp_path, pics, monkeypatch):
    def refuse(path):
        raise Exception("503")
    monkeypatch.setattr(tracker.api, "upload_picture", refuse)
    result = tracker.add_joy(AVA, photo_path=make_image(tmp_path / "snap.png"), picture_dir=pics)
    assert result["queued"] is True
    assert server.uploads == []  # the record waits for its files
    assert query("SELECT COUNT(*) FROM TransactionLog") == [(1,)]


def test_a_vanished_queued_file_is_dropped_not_stuck(tracker, server, query, tmp_path, pics):
    server.online = False
    tracker.add_joy(AVA, photo_path=make_image(tmp_path / "snap.png"), picture_dir=pics)
    for name in os.listdir(pics):
        os.remove(os.path.join(pics, name))
    server.online = True
    assert tracker.sync()["uploaded_transactions"] == 1
    assert query("SELECT COUNT(*) FROM PhotoList") == [(0,)]


def test_attach_to_an_existing_diaper(tracker, server, query, tmp_path, pics):
    diaper = tracker.add_diaper(AVA, None, pee=True, poo=True, note="big one")
    result = tracker.attach_photo("Diaper", diaper["objectID"], make_image(tmp_path / "d.png"), picture_dir=pics)
    assert result["status"] == "success" and result["queued"] is False

    update = server.uploads[-1]
    assert update["OPCode"] == "1"  # an UPDATE of the same record
    record = update["record"]
    assert (record["BCObjectType"], record["objectID"], record["note"], record["status"]) == (
        "Diaper", diaper["objectID"], "big one", 2)
    assert record["timestamp"] > server.uploads[-2]["record"]["timestamp"]  # newer, or it would be ignored
    assert [p["activityID"] for p in record["pictureNote"]] == [diaper["objectID"]]
    name = record["pictureNote"][0]["fileName"]
    assert result["pictureID"] == record["pictureNote"][0]["objectID"] == name
    assert uploaded_names(server) == [f"{name}.jpg", f"{name}__thumbnail.jpg"]
    assert query("SELECT HasPicture, Status, Note FROM Diaper WHERE ID=?", (diaper["objectID"],)) == [(1, 2, "big one")]

    # A second photo keeps the first
    again = tracker.attach_photo("Diaper", diaper["objectID"], make_image(tmp_path / "d2.png"), picture_dir=pics)
    assert again["status"] == "success"
    assert len(server.uploads[-1]["record"]["pictureNote"]) == 2
    assert server.uploads[-1]["record"]["pictureNote"][0]["fileName"] == name
    assert query("SELECT COUNT(*) FROM Picture WHERE ActivityID=?", (diaper["objectID"],)) == [(2,)]
    assert tracker.get_latest_picture(AVA)["object_id"] == diaper["objectID"]


def test_attach_refuses_what_cannot_have_a_photo(tracker, server, tmp_path, pics):
    image = make_image(tmp_path / "x.png")
    assert tracker.attach_photo("Diaper", "NOPE", image, picture_dir=pics)["status"] == "error"
    assert tracker.attach_photo("Baby", AVA, image, picture_dir=pics)["status"] == "error"
    assert tracker.attach_photo("Nonsense", "X", image, picture_dir=pics)["status"] == "error"
    assert server.uploads == [] and server.picture_uploads == []
    assert not os.path.exists(pics)


def test_a_file_that_is_not_an_image_is_an_error_and_leaves_nothing(tracker, server, tmp_path, pics):
    bad = tmp_path / "notes.txt"
    bad.write_text("not an image")
    result = tracker.add_joy(AVA, photo_path=str(bad), picture_dir=pics)
    assert result["status"] == "error" and "image" in result["message"]
    assert server.uploads == [] and os.listdir(pics) == []


def test_no_picture_folder_is_a_clear_error(tracker, tmp_path):
    result = tracker.add_joy(AVA, photo_path=make_image(tmp_path / "x.png"))
    assert result["status"] == "error" and "picture folder" in result["message"]


def test_a_known_wire_decodes_back_to_the_picture_entries(tracker, server, tmp_path, pics):
    """The entry we send is what records.picture_entries reads on the other devices."""
    from babytracker_client import records
    tracker.add_joy(AVA, photo_path=make_image(tmp_path / "x.png"), picture_dir=pics)
    record = server.uploads[-1]["record"]
    entries = records.picture_entries(record)
    assert [(e["Type"], e["deleted"]) for e in entries] == [(0, False)]
    assert entries[0]["FileName"] == record["pictureNote"][0]["fileName"]


def test_pillow_missing_is_explained(monkeypatch, tmp_path):
    import builtins
    real_import = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    from babytracker_client import photos
    with pytest.raises(PhotoError, match="Pillow"):
        photos.import_photo(str(tmp_path / "x.png"), str(tmp_path / "out"))


def test_cli_adds_a_joy_with_a_photo_and_attaches_one(server, tmp_path, app_db, monkeypatch, capsys):
    import json
    import shutil

    from babytracker_client.cli import main
    state = tmp_path / "state"
    state.mkdir()
    shutil.copy(app_db, state / "babytracker.db")
    monkeypatch.setenv("BABYTRACKER_EMAIL", "me@example.com")
    monkeypatch.setenv("BABYTRACKER_PASSWORD", "pw")

    def run(*args):
        main(["--state-dir", str(state), "--time-zone", "America/Chicago", *args])
        return json.loads(capsys.readouterr().out)

    image = make_image(tmp_path / "x.png")
    joy = run("add-joy", "--baby", "ava", "--note", "smile", "--photo", image)
    assert joy["status"] == "success"
    assert len(os.listdir(state / "pictures")) == 2
    diaper = run("add-diaper", "wet", "--baby", "ava")
    attached = run("attach-photo", "Diaper", diaper["objectID"], image)
    assert attached["status"] == "success"
    assert len(server.picture_uploads) == 4
