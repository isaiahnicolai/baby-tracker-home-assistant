"""Baths as activities, and never sending a record type an app can't merge.

A built-in Bath record never shows in the apps, and the iPhone app passes a delete of one on as type
"BCObject", which stops every Android phone's sync with "Merge failure".
"""
import pytest

from helpers import AVA, COMMON

SELECTION = {"timestamp": "1970-01-01 00:00:00 +0000", "newFlage": "false"}
BATH_TYPE = {**SELECTION, "objectID": "BATH-TYPE", "name": "Bath", "desc": "",
             "BCObjectType": "OtherActivityDescription"}


def record(object_type, object_id, **fields):
    return {**COMMON, "BCObjectType": object_type, "objectID": object_id, "time": "2026-11-08 22:00:00 +0000",
            "baby": {"objectID": AVA}, **fields}


def test_log_bath_logs_an_activity_of_the_accounts_bath_type(tracker, server, apply, query):
    apply(BATH_TYPE)  # the account's Bath type, as its seed or its own transaction brings it
    server.uploads.clear()

    result = tracker.log_bath(AVA, note="bubbles")

    assert result["status"] == "success"
    [upload] = server.uploads
    sent = upload["record"]
    assert sent["BCObjectType"] == "OtherActivity"
    assert sent["desc"]["objectID"] == "BATH-TYPE" and sent["desc"]["name"] == "Bath"
    assert sent["note"] == "bubbles"


def test_log_bath_without_a_bath_type_says_to_add_one_and_sends_nothing(tracker, server):
    server.uploads.clear()

    result = tracker.log_bath(AVA)

    assert result["status"] == "error" and "named Bath" in result["message"]
    assert server.uploads == []


@pytest.mark.parametrize("object_type", ["Bath", "Joy", "Journal"])
def test_delete_refuses_a_type_the_phones_dont_write(tracker, server, apply, query, object_type):
    apply(record(object_type, "R-1"))
    server.uploads.clear()

    result = tracker.delete_record(object_type, "R-1")

    assert result["status"] == "error" and "can't be deleted" in result["message"]
    assert server.uploads == []
    assert query(f'SELECT COUNT(*) FROM "{object_type}" WHERE ID=?', ("R-1",)) == [(1,)]


@pytest.mark.parametrize(("object_type", "passed_on"), [
    ("Diaper", True), ("OtherActivity", True), ("BCObject", False), ("BathDesc", False),
])
def test_only_types_the_android_app_reads_are_passed_on(tracker, query, object_type, passed_on):
    handler = tracker.api.transaction_handler
    handler._emit = True
    before = query("SELECT COUNT(*) FROM TransactionLog")[0][0]

    handler._echo(2, {"BCObjectType": object_type, "objectID": "X"})

    assert query("SELECT COUNT(*) FROM TransactionLog")[0][0] == before + (1 if passed_on else 0)
