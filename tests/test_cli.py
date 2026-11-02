"""The babytracker command, run against the fake server with an existing local database."""
import json
import shutil

import pytest
from babytracker_client.cli import main
from helpers import EVERLY, TWIN


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


def test_lists_babies(server, state_dir, capsys):
    babies = run(capsys, state_dir, "babies")
    assert sorted(b["name"] for b in babies) == ["Ann Marie", "Everly"]


def test_uses_its_own_persistent_device(server, state_dir, capsys):
    run(capsys, state_dir, "--offline", "babies")
    first = json.loads((state_dir / "state.json").read_text())["device_uuid"]
    run(capsys, state_dir, "--offline", "babies")
    assert json.loads((state_dir / "state.json").read_text())["device_uuid"] == first
    assert first in server.devices


def test_adds_a_diaper_for_the_named_baby(server, state_dir, capsys):
    result = run(capsys, state_dir, "add-diaper", "mixed", "--baby", "ann marie")
    assert result["status"] == "success"
    assert server.uploads[-1]["record"]["baby"]["objectID"] == TWIN
    assert server.uploads[-1]["record"]["status"] == 2


def test_logout_ends_the_server_session_without_syncing(server, state_dir, capsys):
    result = run(capsys, state_dir, "logout")
    assert result["status"] == "success"
    assert ("DELETE", "/session") in server.requests
    assert not [p for m, p in server.requests if p.startswith("/account/transaction")]


def test_requires_a_baby_when_there_are_several(server, state_dir, capsys):
    with pytest.raises(SystemExit, match="--baby is required"):
        main(["--state-dir", str(state_dir), "add-diaper", "wet"])


def test_add_bottle_logs_formula_in_ounces_by_default(server, state_dir, capsys):
    result = run(capsys, state_dir, "add-bottle", "--baby", "everly", "--amount", "4")
    assert result["status"] == "success"
    record = server.uploads[-1]["record"]
    assert record["BCObjectType"] == "Formula"
    assert record["baby"]["objectID"] == EVERLY
    assert record["amount"]["value"] == 4 and str(record["amount"]["englishMeasure"]).lower() == "true"


def test_add_bottle_pumped_in_millilitres(server, state_dir, capsys):
    run(capsys, state_dir, "add-bottle", "--baby", "ann marie", "--amount", "90", "--unit", "ml",
        "--type", "pumped", "--note", "night")
    record = server.uploads[-1]["record"]
    assert record["BCObjectType"] == "Pumped" and record["baby"]["objectID"] == TWIN
    assert record["amount"]["value"] == 90 and str(record["amount"]["englishMeasure"]).lower() == "false"
    assert record["note"] == "night"


def test_add_bottle_needs_a_positive_amount(server, state_dir):
    with pytest.raises(SystemExit):
        main(["--state-dir", str(state_dir), "add-bottle", "--baby", "everly", "--amount", "0"])


def test_add_nursing_records_both_sides(server, state_dir, capsys):
    result = run(capsys, state_dir, "add-nursing", "--baby", "everly", "--left", "10", "--right", "8")
    assert result["status"] == "success"
    record = server.uploads[-1]["record"]
    assert record["BCObjectType"] == "Nursing" and record["baby"]["objectID"] == EVERLY
    assert (record["leftDuration"], record["rightDuration"]) == (10, 8)
    assert record["finishSide"] == 2  # ended on the right unless told otherwise


def test_add_nursing_finish_side_can_be_given(server, state_dir, capsys):
    run(capsys, state_dir, "add-nursing", "--baby", "everly", "--left", "5", "--right", "5", "--finish-side", "left")
    assert server.uploads[-1]["record"]["finishSide"] == 1


def test_add_nursing_needs_a_duration(server, state_dir):
    with pytest.raises(SystemExit, match="--left and/or --right"):
        main(["--state-dir", str(state_dir), "add-nursing", "--baby", "everly"])


def test_insights_for_one_baby_and_for_all(server, state_dir, capsys):
    one = run(capsys, state_dir, "insights", "--baby", "everly")
    assert one["baby_id"] == EVERLY and one["name"] == "Everly"
    assert {"age", "next_feed", "next_sleep", "intake", "diapers", "growth"} <= set(one)

    everyone = run(capsys, state_dir, "--offline", "insights")
    assert sorted(i["name"] for i in everyone) == ["Ann Marie", "Everly"]


def test_next_names_who_is_due_first(server, state_dir, capsys):
    before = run(capsys, state_dir, "next")
    assert before["due_first"] is None  # nothing logged yet
    assert sorted(b["baby"] for b in before["babies"]) == ["Ann Marie", "Everly"]

    run(capsys, state_dir, "--offline", "add-bottle", "--baby", "everly", "--amount", "3")
    after = run(capsys, state_dir, "--offline", "next")
    assert after["due_first"]["baby"] == "Everly"
    assert after["babies"][0]["baby"] == "Everly" and after["babies"][0]["predicted_at"]
    assert after["babies"][1]["predicted_at"] is None
    assert after["babies"][0]["asleep"] is False and after["babies"][0]["next_sleep_at"] is None  # no sleeps logged


def test_calendar_lists_what_was_logged(server, state_dir, capsys):
    run(capsys, state_dir, "add-bottle", "--baby", "everly", "--amount", "4")
    run(capsys, state_dir, "--offline", "add-nursing", "--baby", "everly", "--left", "12")
    run(capsys, state_dir, "--offline", "add-bottle", "--baby", "ann marie", "--amount", "2")

    events = run(capsys, state_dir, "--offline", "calendar", "--baby", "everly", "--days", "2")

    assert sorted(e["summary"] for e in events) == ["Formula 4 oz", "Nursing (12 min)"]
    assert all(e["kind"] == "feeding" and e["start"] < e["end"] for e in events)


def test_inventory_counts_pumped_feeds_against_the_store(server, state_dir, capsys):
    assert run(capsys, state_dir, "inventory")["ml"] == 0
    run(capsys, state_dir, "--offline", "add-bottle", "--baby", "everly", "--amount", "100", "--unit", "ml",
        "--type", "pumped")
    inventory = run(capsys, state_dir, "--offline", "inventory")
    assert inventory["fed_ml"] == pytest.approx(100, abs=0.1) and inventory["ml"] == pytest.approx(-100, abs=0.1)


def test_create_medicine_and_food(server, state_dir, capsys):
    result = run(capsys, state_dir, "create-medicine", "Tylenol", "--amount", "2.5", "--unit", "ml",
                 "--interval", "6", "--prescription")
    assert result["status"] == "success"
    record = server.uploads[-1]["record"]
    assert record["BCObjectType"] == "MedicationSelection" and record["name"] == "Tylenol"
    assert record["amountPerTime"] == 2.5 and record["unit"] == "ml" and record["interval"] == 6
    assert record["prescription"] is True
    result = run(capsys, state_dir, "create-food", "Banana")
    assert result["status"] == "success"
    assert server.uploads[-1]["record"]["BCObjectType"] == "OtherFeedSelection"
    assert server.uploads[-1]["record"]["bottle"] is False


# ===== The interactive shell =====

def shell(state_dir):
    """A shell over the fake account, connected offline (no sync)."""
    import argparse

    from babytracker_client.cli import _connect, make_shell
    args = argparse.Namespace(state_dir=str(state_dir), email=None, time_zone="America/Chicago", offline=True)
    return make_shell(_connect(args), args)


def test_shell_runs_the_same_commands(server, state_dir, capsys):
    app = shell(state_dir)
    app.onecmd_plus_hooks("babies")
    assert sorted(b["name"] for b in json.loads(capsys.readouterr().out)) == ["Ann Marie", "Everly"]


def test_shell_accepts_the_hyphenated_command_names(server, state_dir, capsys):
    app = shell(state_dir)
    app.onecmd_plus_hooks('add-diaper mixed --baby "ann marie"')
    assert json.loads(capsys.readouterr().out)["status"] == "success"
    assert server.uploads[-1]["record"]["baby"]["objectID"] == TWIN
    assert server.uploads[-1]["record"]["status"] == 2


def test_shell_set_baby_stands_in_for_the_option(server, state_dir, capsys):
    app = shell(state_dir)
    app.onecmd_plus_hooks("set baby Everly")
    capsys.readouterr()
    app.onecmd_plus_hooks("add_diaper wet")
    assert json.loads(capsys.readouterr().out)["status"] == "success"
    assert server.uploads[-1]["record"]["baby"]["objectID"] == EVERLY
    assert app.baby_names() == ["Everly", "Ann Marie"] or sorted(app.baby_names()) == ["Ann Marie", "Everly"]


def test_shell_reports_errors_without_leaving(server, state_dir, capsys):
    app = shell(state_dir)
    stop = app.onecmd_plus_hooks("last diaper --baby nobody")
    captured = capsys.readouterr()
    assert stop is False
    assert "No baby named 'nobody'" in captured.err
    stop = app.onecmd_plus_hooks("add_diaper wet")  # two babies, none chosen
    assert stop is False
    assert "--baby is required" in capsys.readouterr().err


def test_shell_help_lists_the_commands_and_logout_leaves(server, state_dir, capsys):
    app = shell(state_dir)
    app.onecmd_plus_hooks("help")
    out = capsys.readouterr().out
    assert "add_diaper" in out and "insights" in out and "alias" not in out
    assert "Baby Tracker" in out
    app.onecmd_plus_hooks("help add-diaper")
    assert "{wet,dirty,mixed,dry}" in capsys.readouterr().out
    assert app.onecmd_plus_hooks("logout") is True
    assert ("DELETE", "/session") in server.requests
