"""The babytracker command, run against the fake server with an existing local database."""
import json
import shutil

import pytest

from babytracker_client.cli import main
from helpers import TWIN


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


def test_requires_a_baby_when_there_are_several(server, state_dir, capsys):
    with pytest.raises(SystemExit, match="--baby is required"):
        main(["--state-dir", str(state_dir), "add-diaper", "wet"])
