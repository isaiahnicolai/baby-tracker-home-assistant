"""
Shared fixtures for the client tests.

`app_db` is a database with the Baby Tracker app's real schema
(fixtures/app_schema.sql, no data) holding two babies. `server` stands in
for prodapp.babytrackers.com so nothing touches the network.
"""
import json
import pathlib
import sqlite3

import pytest
import requests

from helpers import EMAIL, EVERLY, IPHONE, MILESTONE, OURS, TWIN, VACCINE, b64, unb64  # noqa: F401

SCHEMA = pathlib.Path(__file__).parent / "fixtures" / "app_schema.sql"


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode()
        self.headers = {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeServer:
    """The sync server: devices, per-device transaction logs, and uploads."""

    def __init__(self):
        self.online = True
        self.devices = {OURS: 7, IPHONE: 0}  # server already holds 7 of our transactions
        self.logs = {}                       # device -> [{SyncID, OPCode, Transaction}]
        self.uploads = []
        self.requests = []
        self.expire_session_once = False
        self.reject_login = False

    def post_session(self, session, url, headers=None, json=None, timeout=None):
        assert timeout, "login must use a timeout"
        if self.reject_login:
            return Response(401, {})
        session.cookies.set("PHPSESSID", "session")
        self.devices.setdefault(json["Device"]["DeviceUUID"], 0)
        return Response(200, {"AccountID": 1})

    def request(self, session, method, url, timeout=None, **kwargs):
        assert timeout, f"{method} {url} must use a timeout"
        path = url.split(".com", 1)[1]
        self.requests.append((method, path))
        if not self.online:
            raise requests.ConnectionError("offline")
        if self.expire_session_once:
            self.expire_session_once = False
            return Response(401, {})
        if path == "/account/device":
            return Response(200, [{"DeviceUUID": d, "LastSyncID": n} for d, n in self.devices.items()])
        if method == "POST" and path == "/account/transaction":
            body = kwargs["json"]
            self.uploads.append({**body, "record": unb64(body["Transaction"])})
            self.devices[OURS] = body["SyncID"]
            return Response(201, {})
        if method == "GET" and path.startswith("/account/transaction/"):
            _, _, _, device, start = path.split("/")
            items = [t for t in self.logs.get(device, []) if t["SyncID"] > int(start)]
            return Response(200, items[:500])
        raise AssertionError(f"unexpected request {method} {path}")

    def publish(self, device, records, op=0, start=None):
        """Add records to a device's log on the server."""
        log = self.logs.setdefault(device, [])
        sync_id = start or (log[-1]["SyncID"] + 1 if log else 1)
        for record in records:
            log.append({"SyncID": sync_id, "OPCode": op, "Transaction": b64(record)})
            sync_id += 1
        self.devices[device] = log[-1]["SyncID"]


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(requests.Session, "post", lambda s, url, **kw: fake.post_session(s, url, **kw))
    monkeypatch.setattr(requests.Session, "request", lambda s, method, url, **kw: fake.request(s, method, url, **kw))
    return fake


@pytest.fixture
def app_db(tmp_path):
    path = tmp_path / "baby_tracker.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO Baby (ID, Timestamp, Name, DOB, DueDay, Gender, Picture) VALUES (?, 1.7e9, ?, 1.7e9, 1.7e9, 0, '')",
        [(EVERLY, "Everly"), (TWIN, "Ann Marie")],
    )
    conn.execute("INSERT INTO MilestoneSelection (ID, Timestamp, Name, Description, ForAge) VALUES (?, 0, 'First smile', '', 2)", (MILESTONE,))
    conn.execute("INSERT INTO VaccineSelection (ID, Timestamp, Name, Description, ForAge) VALUES (?, 0, 'HepB', '', 0)", (VACCINE,))
    # A seed download carries the seeding device's upload counter
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('TransactionLog', 43)")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def query(app_db):
    def run(sql, params=()):
        conn = sqlite3.connect(app_db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return run


@pytest.fixture
def tracker(app_db, server):
    from babytracker_client import BabyTracker

    tracker = BabyTracker(db_path=str(app_db), time_zone="America/Chicago")
    assert tracker.authenticate(EMAIL, "pw", OURS)["status"] == "success"
    return tracker
